"""Read analysis activity and queue retries; never invoke models in requests."""
from datetime import datetime, timezone
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
            s.name AS signal_name, t.trace_id, t.conversation_id,
            t.item->'turns'->-1->>'user' AS user_message,
            (SELECT count(*) FROM signal_events e WHERE e.run_id=r.id) AS event_count
            FROM signal_runs r JOIN signals s ON s.id=r.signal_id
            JOIN turns t ON t.id=r.turn_id
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
