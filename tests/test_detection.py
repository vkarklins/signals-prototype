import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock
from uuid import uuid4
from datetime import datetime, timezone

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from detection.engine import reconstruct, validate_output
from detection.worker import enqueue, process, retry, recover

TRACE, ROOT, CHILD = [str(uuid4()) for _ in range(3)]
SCHEMA = {'type': 'object', 'required': ['kind'], 'properties': {'kind': {'type': 'string'}}, 'additionalProperties': False}


def spans():
    return [{'trace_id': TRACE, 'span_id': sid, 'parent_span_id': parent,
             'start_time': '2026-10-30 00:00:00.000001', 'end_time': '2026-10-30 00:00:01',
             'input': '{"messages":["first","second"]}', 'output': 'failed'}
            for sid, parent in [(CHILD, ROOT), (ROOT, None)]]


def finding(**changes):
    return {'summary': 'Booking failed.', 'severity': 'warning', 'evidence': 'Tool returned failed.',
            'supporting_span_ids': [CHILD], 'payload': {'kind': 'booking'}, **changes}


class EvidenceTests(unittest.TestCase):
    def test_tree_order_gaps_and_cycles(self):
        result = reconstruct(spans(), TRACE)
        root = next(s for s in result['spans'] if s['span_id'] == ROOT)
        self.assertEqual(root['children'], [CHILD])
        self.assertEqual(root['input']['messages'], ['first', 'second'])
        rows = spans()
        rows[0]['parent_span_id'] = str(uuid4())
        rows[0]['start_time'] = None
        self.assertEqual(len(reconstruct(rows, TRACE)['warnings']), 2)
        rows = spans()
        rows[1]['parent_span_id'] = CHILD
        with self.assertRaises(ValueError):
            reconstruct(rows, TRACE)
        with self.assertRaises(ValueError):
            reconstruct([], TRACE)

    def test_validation_multiple_empty_and_bad_findings(self):
        snapshot = {'trace': reconstruct(spans(), TRACE)}
        self.assertEqual(validate_output('{"findings":[]}', snapshot, SCHEMA), [])
        self.assertEqual(len(validate_output(json.dumps({'findings': [finding(), finding(supporting_span_ids=None)]}), snapshot, SCHEMA)), 2)
        for change in ({'payload': {}}, {'supporting_span_ids': [str(uuid4())]},
                       {'supporting_span_ids': []}, {'severity': 'bad'}, {'summary': '  '}):
            with self.subTest(change=change), self.assertRaises(Exception):
                validate_output(json.dumps({'findings': [finding(**change)]}), snapshot, SCHEMA)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Set TEST_DATABASE_URL')
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True, row_factory=dict_row)
        self.addCleanup(self.conn.close)
        self.schema = 'detection_' + uuid4().hex
        self.conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.conn.execute, sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        self.conn.execute((Path(__file__).resolve().parents[1] / 'schema.sql').read_text())
        item = {'contract': 'v1', 'conversation_id': 'demo', 'target_turn': 0,
                'turns': [{'trace_id': TRACE, 'user': 'Book campsite', 'reply': 'Booked!'}]}
        self.conn.execute("INSERT INTO turns(source,item,turn_ended_at) VALUES ('live',%s,now())", (Jsonb(item),))
        self.sid = uuid4()
        self.conn.execute("INSERT INTO signals(id,name,enabled) VALUES (%s,'Detector',true)", (self.sid,))
        self.conn.execute("INSERT INTO signal_versions VALUES (%s,1,'Find failed bookings',%s,now())", (self.sid, Jsonb(SCHEMA)))
        self.laminar = Mock()
        self.laminar.query.return_value = spans()

    def queue(self):
        enqueue(self.conn, datetime(2000, 1, 1, tzinfo=timezone.utc), 'shared-model')
        return self.conn.execute('SELECT id FROM signal_runs').fetchone()['id']

    def test_success_dedup_and_no_findings(self):
        rid = self.queue()
        self.assertEqual(enqueue(self.conn, datetime(2000,1,1,tzinfo=timezone.utc), 'shared-model'), 0)
        process(self.conn, self.laminar, rid, lambda *args: [finding(), finding(supporting_span_ids=None)])
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM signal_events').fetchone()['n'], 2)
        self.assertEqual(self.conn.execute('SELECT status FROM signal_runs').fetchone()['status'], 'succeeded')
        self.conn.execute("INSERT INTO signal_versions VALUES (%s,2,'New instruction',%s,now())", (self.sid, Jsonb(SCHEMA)))
        enqueue(self.conn, datetime(2000,1,1,tzinfo=timezone.utc), 'shared-model')
        second = self.conn.execute('SELECT id FROM signal_runs WHERE signal_version=2').fetchone()['id']
        process(self.conn, self.laminar, second, lambda *args: [])
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM signal_events').fetchone()['n'], 2)

    def test_failure_atomicity_retry_and_interruption(self):
        rid = self.queue()
        process(self.conn, self.laminar, rid, lambda *args: [finding(), finding(severity='invalid')])
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM signal_events').fetchone()['n'], 0)
        self.assertEqual(self.conn.execute('SELECT status FROM signal_runs').fetchone()['status'], 'failed')
        retry(self.conn, rid)
        process(self.conn, self.laminar, rid, lambda *args: [])
        self.assertEqual(self.laminar.query.call_count, 1)
        with self.assertRaises(ValueError):
            retry(self.conn, rid)
        self.conn.execute("UPDATE signal_runs SET status='running',finished_at=NULL")
        recover(self.conn)
        self.assertEqual(self.conn.execute('SELECT status FROM signal_runs').fetchone()['status'], 'failed')
