"""Run with python -m detection.run --help."""
import argparse
import os
import time
from datetime import datetime, timezone
from uuid import UUID

from dotenv import load_dotenv
from classifier.config import MODEL
from eval.storage import connect_database
from sync.laminar import LaminarSQL
from detection.worker import LOCK_ID, enqueue, process, recover, retry


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError('Include a timezone, such as Z or +08:00')
    return result


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Analyze live turns with configured Signals')
    sub = parser.add_subparsers(dest='command', required=True)
    watch = sub.add_parser('watch', help='Analyze turns arriving after startup')
    watch.add_argument('--since', type=timestamp, help='Resume from an explicit timestamp')
    watch.add_argument('--once', action='store_true')
    watch.add_argument('--interval', type=float, default=10)
    backfill = sub.add_parser('backfill', help='Analyze historical live turns from a timestamp')
    backfill.add_argument('--since', type=timestamp, required=True)
    again = sub.add_parser('retry', help='Retry a failed run with its original version, model and saved input')
    again.add_argument('run_id', type=UUID)
    sub.add_parser('status', help='Show recent runs and failure details')
    args = parser.parse_args()
    if args.command == 'watch' and args.interval <= 0:
        parser.error('--interval must be positive')
    with connect_database() as conn:
        if args.command == 'status':
            for row in conn.execute('SELECT id, turn_id, signal_id, signal_version, status, error FROM signal_runs ORDER BY created_at DESC LIMIT 50'):
                print(dict(row))
            return
        if not conn.execute('SELECT pg_try_advisory_lock(%s) AS locked', (LOCK_ID,)).fetchone()['locked']:
            raise RuntimeError('Another detection worker is already running')
        recover(conn)
        laminar = LaminarSQL(os.environ['LMNR_PROJECT_API_KEY'],
                             os.environ.get('LMNR_BASE_URL', 'http://localhost'),
                             int(os.environ.get('LMNR_HTTP_PORT', '8000')))
        try:
            if args.command == 'retry':
                retry(conn, args.run_id)
                process(conn, laminar, args.run_id)
                return
            since = args.since or datetime.now(timezone.utc)
            while True:
                enqueue(conn, since, MODEL)
                pending = conn.execute("SELECT id FROM signal_runs WHERE status='pending' ORDER BY created_at, id").fetchall()
                for row in pending:
                    process(conn, laminar, row['id'])
                if args.command == 'backfill' or args.once:
                    break
                time.sleep(args.interval)
        finally:
            laminar.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
