# Signal configuration API

These endpoints manage configuration only. They do not retrieve traces, enqueue
analysis, invoke a model, or change the existing frustration classifier.

Install the updated `requirements.txt` and apply the database migration documented
in [migrations/README.md](../migrations/README.md) before using them on an existing
database. Run the existing API on port 8100. Interactive documentation is at
`http://localhost:8100/docs`.

| Method | Path | Response |
| --- | --- | --- |
| POST | `/api/signals` | 201: new Signal with version 1; Location header |
| GET | `/api/signals` | 200: array, newest Signals first, latest configuration included |
| GET | `/api/signals/{id}` | 200: Signal with its latest configuration |
| PATCH | `/api/signals/{id}` | 200: updated Signal with its latest configuration |
| GET | `/api/signals/{id}/versions` | 200: immutable configurations, newest version first |

## Create

```bash
curl -X POST http://localhost:8100/api/signals \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Agent Failure Detector",
    "description": "Finds significant problems in agent runs.",
    "instruction": "Find significant mistakes and unsupported claims. Exclude minor mistakes successfully corrected.",
    "output_schema": {
      "type": "object",
      "properties": {"issue_type": {"type": "string"}},
      "required": ["issue_type"],
      "additionalProperties": false
    }
  }'
```

`name`, `instruction`, and `output_schema` are required. `description` defaults to
an empty string; `enabled` defaults to false. An explicit boolean `enabled` may
also be supplied. The server generates the UUID. Model choice is shared and is
not a configurable API field.

Create, detail, update, and list entries have these fields:

```json
{
  "id": "a2e3c4a5-4c4c-4d4d-8e8e-010203040506",
  "name": "Agent Failure Detector",
  "description": "Finds significant problems in agent runs.",
  "enabled": false,
  "created_at": "2026-10-30T00:00:00Z",
  "version": 1,
  "instruction": "Find significant mistakes and unsupported claims.",
  "output_schema": {"type": "object"},
  "version_created_at": "2026-10-30T00:00:00Z"
}
```

The example is illustrative; timestamps and IDs are generated at creation.
Version-history entries contain `signal_id`, `version`, `instruction`,
`output_schema`, and `created_at`.

## Update and validation rules

- PATCH accepts any subset of the creation fields. Omit unchanged fields;
  explicit nulls and unknown fields are rejected with 422. An empty patch is a no-op.
- Names and instructions are trimmed and must be nonblank. Descriptions may be empty.
- Names are case-sensitive and unique. Duplicate names return 409.
- Name, description, and enabled changes do not create a version.
- A changed instruction or schema creates one new version. Resubmitting an
  equivalent JSON object or the same instruction does not create one.
- Metadata and configuration changes in one request are committed together.
  A failure rolls back the entire request. Concurrent edits are serialized per Signal.
- `output_schema` must be an object schema with `type: object`. It describes
  only the custom event `payload`; the engine will own the standard event fields.
- JSON Schema syntax is validated (Draft 2020-12 by default, or a recognized
  declared dialect). This does not yet check provider-specific structured-output
  support, resolve referenced schemas, or validate generated event payloads.
- Missing UUIDs return 404; malformed UUIDs and invalid bodies return 422.
- Database configuration/connectivity or missing tables return an actionable 503
  without exposing credentials or SQL internals.
- GET endpoints use read-only transactions and send `Cache-Control: no-store`.

The greatest saved version is current. There is no deletion or version rollback
endpoint in this step. Enabling a Signal saves the setting; automatic analysis
will be implemented separately.

## Tests

Run `python -m unittest discover -s tests -v`. Database API tests require a
disposable `TEST_DATABASE_URL`; they create and remove their own schema and use
synthetic definitions. They cover versioning, concurrency, validation, duplicate
names, missing records, transaction rollback, and read-only GET requests.

## Dashboard activity APIs

- `GET /api/signal-runs?limit=50&offset=0`: newest runs with Signal name/version,
  target user message, status, model, safe error, event count and Laminar trace link.
  Optional `signal_id` filters a definition.
- `GET /api/signal-events?limit=50&offset=0`: newest events including payload,
  citations, Signal name/version and trace link. Optional `run_id` filters a run.
- `POST /api/signal-runs/{id}/retry`: atomically changes a failed run to pending
  and clears its error/completion time. Returns 202; missing ID returns 404 and
  any nonfailed state returns 409. Repeated requests cannot queue it twice.
  Input snapshot, version and model are preserved. No provider request occurs.

List endpoints use read-only connections, return arrays, and set Cache-Control:
no-store. Limit is 1–200; offset is nonnegative. They omit the raw input snapshot.
The worker must be running to process dashboard retries.

The frontend's **Signals** tab provides definition creation/editing and an enabled
checkbox, plus Runs and Events views with paging and manual refresh. Editing an
instruction/schema creates a version; changing metadata or enabled does not.
Run cards link to their events and offer Retry analysis only for failures. Event
cards show summary/severity/evidence, expandable custom fields and citations, and
View trace when LMNR_UI_PROJECT_URL is configured. An empty successful run stays
visible with zero events. Backfills remain CLI-only and explicit.

## Frontend backfills

`POST /api/signals/{id}/backfill` accepts `{"since":"2026-10-31T00:00:00+08:00"}`.
The date must include a timezone and cannot be in the future. An enabled Signal
is required (409 if disabled, 404 if missing). The endpoint queues its latest
saved version for live turns synced on or after `since` (turns.created_at).
It returns 202 with `signal_id`, `signal_version`, `since`, and `queued_runs`.
Runs already present for the same turn/Signal/version are skipped, including
failed runs (use Retry analysis for those). Only the selected Signal is queued;
old runs and events are preserved. The definition is locked during selection to
keep its version consistent with concurrent edits. No model calls occur in the
request; the detection worker must be running to process the pending queue.

In Signals → Definitions, use **Analyze previous conversations**, select an
enabled Signal, choose a local start date/time, and click **Queue backfill**.
The browser converts the local timestamp to UTC. Save definition edits first.
Review progress in Runs, then View events. Zero queued runs means no eligible
synced turns or all matching turns already have runs for that version.

## Signal health

`GET /api/signal-health?period=7d` returns reporting boundaries, totals, and per-Signal counts for completed, queued, running, failed analyses and findings, plus success rate and most recent completion. Allowed periods: `24h`, `7d` (default), `30d`, `all`. Includes disabled Signals and all versions; runs are selected by creation time. Success rate is successful / (successful + failed), or null with no finished runs. Most recent completion includes successful and failed runs. Retries update current status rather than preserving attempt history. This read-only endpoint measures processing reliability, not detection accuracy or worker availability.

## Run human labels

`GET /api/signal-runs` includes nullable `human_label` and `reviewed_at` fields.
`PUT /api/signal-runs/{run_id}/review` accepts `{"human_label": true}` (issue),
`false` (no issue), or `null` (reset to unreviewed). Only successful runs can be
reviewed; other states return 409 and missing runs return 404. One shared editable
label is stored per run, including runs without findings. Labels do not alter
model findings or trigger model calls. Outcomes compare presence of findings
with the human label; unreviewed and unfinished runs are not assessed.
