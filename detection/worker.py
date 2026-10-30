"""Serial worker; database advisory lock prevents simultaneous worker instances."""
import json
from uuid import uuid4
from psycopg.types.json import Jsonb
from detection.engine import TRACE_SQL, reconstruct, analyze, validate_output, ENGINE_INSTRUCTION

LOCK_ID = 739150221


def enqueue(conn, since, model):
    """Only current enabled versions; historical selection must be explicit."""
    return conn.execute('''INSERT INTO signal_runs
        (id, turn_id, signal_id, signal_version, model)
        SELECT gen_random_uuid(), t.id, s.id, v.version, %s
        FROM turns t CROSS JOIN signals s
        JOIN LATERAL (SELECT version FROM signal_versions WHERE signal_id=s.id
                      ORDER BY version DESC LIMIT 1) v ON true
        WHERE t.source='live' AND t.created_at >= %s AND s.enabled
        ON CONFLICT (turn_id, signal_id, signal_version) DO NOTHING''',
        (model, since)).rowcount


def process(conn, laminar, run_id, analyzer=analyze):
    row = conn.execute('''SELECT r.*, t.item, t.trace_id, v.instruction, v.output_schema
        FROM signal_runs r JOIN turns t ON t.id=r.turn_id
        JOIN signal_versions v ON v.signal_id=r.signal_id AND v.version=r.signal_version
        WHERE r.id=%s''', (run_id,)).fetchone()
    if row is None or row['status'] != 'pending':
        raise ValueError('Run must exist and be pending')
    conn.execute("UPDATE signal_runs SET status='running' WHERE id=%s", (run_id,))
    try:
        snapshot = row['input_snapshot']
        if snapshot is None:
            snapshot = {'engine_instruction': ENGINE_INSTRUCTION, 'signal_instruction': row['instruction'],
                        'output_schema': row['output_schema'], 'model': row['model'], 'conversation': row['item'], 'target_turn_id': row['turn_id'],
                        'trace': reconstruct(laminar.query(TRACE_SQL, {'trace': str(row['trace_id'])}), row['trace_id'])}
            conn.execute('UPDATE signal_runs SET input_snapshot=%s WHERE id=%s', (Jsonb(snapshot), run_id))
        findings = analyzer(snapshot, row['instruction'], row['output_schema'], row['model'])
        findings = validate_output(json.dumps({'findings': findings}), snapshot, row['output_schema'])
        with conn.transaction():
            for finding in findings:
                conn.execute('''INSERT INTO signal_events
                    (id,run_id,summary,severity,evidence,supporting_span_ids,payload)
                    VALUES (%s,%s,%s,%s,%s,%s::uuid[],%s)''',
                    (uuid4(), run_id, finding['summary'], finding['severity'], finding['evidence'],
                     finding['supporting_span_ids'], Jsonb(finding['payload'])))
            conn.execute("UPDATE signal_runs SET status='succeeded', error=NULL, finished_at=now() WHERE id=%s", (run_id,))
    except Exception as error:
        # Avoid persisting credentials or full sensitive provider error bodies.
        conn.execute("UPDATE signal_runs SET status='failed', error=%s, finished_at=now() WHERE id=%s",
                     (f'{type(error).__name__}: analysis failed; check trace availability, schema and model configuration.', run_id))


def retry(conn, run_id):
    row = conn.execute("""UPDATE signal_runs SET status='pending', error=NULL, finished_at=NULL
        WHERE id=%s AND status='failed' RETURNING id""", (run_id,)).fetchone()
    if row is None:
        raise ValueError('Only failed runs can be retried')


def recover(conn):
    # Safe only while holding the exclusive worker lock.
    conn.execute("""UPDATE signal_runs SET status='failed', finished_at=now(),
        error='Worker interrupted; manually retry this run.' WHERE status='running'""")
