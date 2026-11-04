"""Read analysis activity and queue retries; never invoke models in requests."""
from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator
from classifier.config import MODEL
from detection.worker import enqueue
from fastapi import APIRouter, HTTPException, Query, Response
from backend.signals import database
from backend.live import laminar_url

router = APIRouter(tags=['Signal activity'])


@router.get('/api/signal-runs')
def list_runs(response: Response, limit: int = Query(50, ge=1, le=200),
              offset: int = Query(0, ge=0), signal_id: UUID | None = None):
    response.headers['Cache-Control'] = 'no-store'
    with database(read_only=True) as conn:
        rows = conn.execute('''SELECT r.id, r.turn_id, r.signal_id, r.signal_version,
            r.status, r.model, r.error, r.created_at, r.finished_at,
            review.human_label, review.updated_at AS reviewed_at,
            s.name AS signal_name, t.trace_id, t.conversation_id,
            t.item->'turns'->-1->>'user' AS user_message,
            (SELECT count(*) FROM signal_events e WHERE e.run_id=r.id) AS event_count
            FROM signal_runs r JOIN signals s ON s.id=r.signal_id
            JOIN turns t ON t.id=r.turn_id
            LEFT JOIN signal_run_reviews review ON review.run_id=r.id
            WHERE (%s::uuid IS NULL OR r.signal_id=%s)
            ORDER BY r.created_at DESC, r.id DESC LIMIT %s OFFSET %s''',
            (signal_id, signal_id, limit, offset)).fetchall()
        return [{**r, 'laminar_url': laminar_url(r['trace_id']) if r['trace_id'] else None} for r in rows]


@router.get('/api/signal-events')
def list_events(response: Response, limit: int = Query(50, ge=1, le=200),
                offset: int = Query(0, ge=0), run_id: UUID | None = None):
    response.headers['Cache-Control'] = 'no-store'
    with database(read_only=True) as conn:
        rows = conn.execute('''SELECT e.*, r.turn_id, r.signal_id, r.signal_version,
            s.name AS signal_name, t.trace_id
            FROM signal_events e JOIN signal_runs r ON r.id=e.run_id
            JOIN signals s ON s.id=r.signal_id JOIN turns t ON t.id=r.turn_id
            WHERE (%s::uuid IS NULL OR e.run_id=%s)
            ORDER BY e.created_at DESC, e.id DESC LIMIT %s OFFSET %s''',
            (run_id, run_id, limit, offset)).fetchall()
        return [{**r, 'laminar_url': laminar_url(r['trace_id']) if r['trace_id'] else None} for r in rows]


@router.post('/api/signal-runs/{run_id}/retry', status_code=202)
def queue_retry(run_id: UUID):
    with database() as conn, conn.transaction():
        row = conn.execute("SELECT status FROM signal_runs WHERE id=%s FOR UPDATE", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Run not found.')
        if row['status'] != 'failed':
            raise HTTPException(409, 'Only failed runs can be retried.')
        conn.execute("UPDATE signal_runs SET status='pending', error=NULL, finished_at=NULL WHERE id=%s", (run_id,))
    return {'id': run_id, 'status': 'pending'}


class BackfillRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    since: datetime

    @field_validator('since')
    @classmethod
    def valid_since(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('since must include a timezone')
        if value > datetime.now(timezone.utc):
            raise ValueError('since cannot be in the future')
        return value


@router.post('/api/signals/{signal_id}/backfill', status_code=202)
def queue_backfill(signal_id: UUID, body: BackfillRequest):
    with database() as conn, conn.transaction():
        # Serialize with definition edits so the returned version is the one queued.
        signal = conn.execute('SELECT enabled FROM signals WHERE id=%s FOR UPDATE', (signal_id,)).fetchone()
        if signal is None:
            raise HTTPException(404, 'Signal not found.')
        if not signal['enabled']:
            raise HTTPException(409, 'Enable and save this Signal before requesting a backfill.')
        version = conn.execute('SELECT max(version) AS version FROM signal_versions WHERE signal_id=%s', (signal_id,)).fetchone()['version']
        queued = enqueue(conn, body.since, MODEL, signal_id=signal_id)
    return {'signal_id': signal_id, 'signal_version': version, 'queued_runs': queued, 'since': body.since}


@router.get('/api/signal-health')
def signal_health(response: Response, period: Literal['24h', '7d', '30d', 'all'] = '7d'):
    """Current run states across all versions, grouped by creation time."""
    response.headers['Cache-Control'] = 'no-store'
    end = datetime.now(timezone.utc)
    start = None if period == 'all' else end - timedelta(days={'24h': 1, '7d': 7, '30d': 30}[period])
    with database(read_only=True) as conn:
        rows = conn.execute("""WITH selected AS (
            SELECT * FROM signal_runs WHERE (%s::timestamptz IS NULL OR created_at >= %s)
                AND created_at <= %s
        ), events AS (
            SELECT e.run_id, count(*) AS findings FROM signal_events e
            JOIN selected r ON r.id=e.run_id GROUP BY e.run_id
        )
        SELECT s.id, s.name, s.enabled,
            count(r.id) FILTER (WHERE r.status='succeeded') AS completed,
            count(r.id) FILTER (WHERE r.status='pending') AS queued,
            count(r.id) FILTER (WHERE r.status='running') AS running,
            count(r.id) FILTER (WHERE r.status='failed') AS failed,
            coalesce(sum(e.findings), 0)::bigint AS findings,
            max(r.finished_at) AS last_completion
        FROM signals s LEFT JOIN selected r ON r.signal_id=s.id
        LEFT JOIN events e ON e.run_id=r.id
        GROUP BY s.id ORDER BY lower(s.name), s.id""", (start, start, end)).fetchall()
    def rate(row):
        finished = row['completed'] + row['failed']
        return row['completed'] / finished if finished else None
    totals = {key: sum(row[key] for row in rows)
              for key in ('completed', 'queued', 'running', 'failed', 'findings')}
    totals['success_rate'] = rate(totals)
    totals['last_completion'] = max((r['last_completion'] for r in rows
                                     if r['last_completion']), default=None)
    return {'period': period, 'start': start, 'end': end, 'totals': totals,
            'signals': [{**row, 'success_rate': rate(row)} for row in rows]}


class RunReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    human_label: bool | None


@router.put('/api/signal-runs/{run_id}/review')
def save_run_review(run_id: UUID, body: RunReviewRequest):
    with database() as conn, conn.transaction():
        run = conn.execute('SELECT status FROM signal_runs WHERE id=%s FOR UPDATE', (run_id,)).fetchone()
        if run is None:
            raise HTTPException(404, 'Run not found.')
        if run['status'] != 'succeeded':
            raise HTTPException(409, 'Only completed analyses can be reviewed.')
        if body.human_label is None:
            conn.execute('DELETE FROM signal_run_reviews WHERE run_id=%s', (run_id,))
            return {'run_id': run_id, 'human_label': None, 'reviewed_at': None}
        row = conn.execute("""INSERT INTO signal_run_reviews(run_id, human_label)
            VALUES (%s,%s) ON CONFLICT (run_id) DO UPDATE
            SET human_label=EXCLUDED.human_label, updated_at=now()
            RETURNING human_label, updated_at AS reviewed_at""", (run_id, body.human_label)).fetchone()
        return {'run_id': run_id, **row}
