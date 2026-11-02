"""Activity API uses isolated test schemas and never calls a model."""
import os
import unittest
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from backend.app import app
import test_detection as fixtures


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Set TEST_DATABASE_URL')
class ActivityTests(fixtures.WorkerTests):
    # Reuse fixture only, not the worker test methods.
    test_success_dedup_and_no_findings = None
    test_failure_atomicity_retry_and_interruption = None

    def setUp(self):
        super().setUp()
        self.enterContext(patch('backend.signal_activity.database', self.database))
        self.enterContext(patch('openai.OpenAI', side_effect=AssertionError('No models in API')))
        self.client = TestClient(app)

    def database(self, **kwargs):
        from contextlib import nullcontext
        return nullcontext(self.conn)

    def test_configuration_to_worker_to_dashboard(self):
        from detection.worker import process
        self.enterContext(patch('backend.signals.database', self.database))
        updated = self.client.patch(f'/api/signals/{self.sid}', json={'instruction':'Find booking failures carefully'})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()['version'], 2)
        rid = self.queue()
        process(self.conn, self.laminar, rid, lambda *args: [fixtures.finding()])
        runs = self.client.get('/api/signal-runs').json()
        self.assertEqual(runs[0]['status'], 'succeeded')
        self.assertEqual(runs[0]['signal_version'], 2)
        self.assertEqual(runs[0]['event_count'], 1)
        self.assertEqual(self.client.get('/api/signal-events').json()[0]['summary'], 'Booking failed.')

    def test_runs_events_and_queued_retry(self):
        rid = self.queue()
        self.conn.execute("UPDATE signal_runs SET status='failed',finished_at=now(),error='Test failure'")
        self.conn.execute('''INSERT INTO signal_events(id,run_id,summary,severity,evidence,payload)
            VALUES(%s,%s,'Issue','warning','Evidence',%s)''', (uuid4(),rid,Jsonb({'kind':'booking'})))
        runs = self.client.get('/api/signal-runs')
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(runs.headers['cache-control'], 'no-store')
        self.assertEqual(runs.json()[0]['event_count'], 1)
        self.assertEqual(runs.json()[0]['user_message'], 'Book campsite')
        events = self.client.get('/api/signal-events', params={'run_id':str(rid)}).json()
        self.assertEqual(events[0]['summary'], 'Issue')
        self.assertEqual(events[0]['payload'], {'kind':'booking'})
        self.assertEqual(self.client.get('/api/signal-events',params={'run_id':str(uuid4())}).json(), [])
        # Real failed runs never have events. Remove the synthetic event before retry.
        self.conn.execute('DELETE FROM signal_events')
        self.assertEqual(self.client.post(f'/api/signal-runs/{rid}/retry').status_code,202)
        self.assertEqual(self.conn.execute('SELECT status FROM signal_runs').fetchone()['status'],'pending')
        self.assertEqual(self.client.post(f'/api/signal-runs/{rid}/retry').status_code,409)
        self.assertEqual(self.client.post(f'/api/signal-runs/{uuid4()}/retry').status_code,404)
        self.assertEqual(self.client.get('/api/signal-runs?limit=201').status_code,422)
        self.assertEqual(self.client.get('/api/signal-events?offset=-1').status_code,422)

    def test_backfill_queues_selected_latest_version_without_duplicates(self):
        from datetime import datetime, timezone
        since = '2000-01-01T00:00:00Z'
        url = f'/api/signals/{self.sid}/backfill'
        # An existing run for version 1 must survive and not block version 2.
        original = self.queue()
        self.conn.execute("INSERT INTO signal_versions VALUES (%s,2,'New detector',%s,now())", (self.sid, Jsonb(fixtures.SCHEMA)))
        other = uuid4()
        self.conn.execute("INSERT INTO signals(id,name,enabled) VALUES (%s,'Other',true)", (other,))
        self.conn.execute("INSERT INTO signal_versions VALUES (%s,1,'Other',%s,now())", (other, Jsonb(fixtures.SCHEMA)))
        response = self.client.post(url, json={'since': since})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()['queued_runs'], 1)
        self.assertEqual(response.json()['signal_version'], 2)
        self.assertEqual(self.client.post(url, json={'since': since}).json()['queued_runs'], 0)
        rows = self.conn.execute('SELECT signal_id,status FROM signal_runs').fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['signal_id'] == self.sid and row['status'] == 'pending' for row in rows))
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM signal_events').fetchone()['n'], 0)
        self.assertIsNotNone(self.conn.execute('SELECT id FROM signal_runs WHERE id=%s', (original,)).fetchone())

    def test_backfill_rejects_disabled_missing_and_invalid_dates(self):
        url = f'/api/signals/{self.sid}/backfill'
        self.conn.execute('UPDATE signals SET enabled=false')
        self.assertEqual(self.client.post(url,json={'since':'2000-01-01T00:00:00Z'}).status_code,409)
        self.assertEqual(self.client.post(f'/api/signals/{uuid4()}/backfill',json={'since':'2000-01-01T00:00:00Z'}).status_code,404)
        for body in ({}, {'since':'bad'}, {'since':'2000-01-01T00:00:00'}, {'since':'2999-01-01T00:00:00Z'}, {'since':'2000-01-01T00:00:00Z','extra':True}):
            self.assertEqual(self.client.post(url,json=body).status_code,422)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM signal_runs').fetchone()['n'],0)
