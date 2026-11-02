# Signal detection worker

This worker is separate from User Frustration. It writes `signal_runs` and
`signal_events`; it does not modify `results`. Apply migration 001 before use
(see migrations/README.md), install requirements.txt, and configure DATABASE_URL,
OPENAI_API_KEY, LMNR_PROJECT_API_KEY, LMNR_BASE_URL and LMNR_HTTP_PORT in .env.
Enable a Signal through the configuration API before starting.

From the project root, with the project virtual environment active:

```sh
python -m detection.run watch
python -m detection.run status
python -m detection.run retry <run-uuid>
python -m detection.run backfill --since 2026-10-30T00:00:00+08:00
```

`watch` polls every 10 seconds. Its fixed selection boundary defaults to startup
time (turns.created_at, the time a turn reached our database). Existing historical
turns are excluded. Resume after downtime using `watch --since <timestamp>`;
the timestamp is not automatically persisted. `--once` performs a single pass.
Backfill explicitly selects live turns from its timestamp through the present.
Gold evaluation rows are excluded. Commands print recent run status through
`status`; failures are not automatically retried. The worker does not run inside
the API server or start automatically with Docker Compose yet.

Each poll selects the latest version of enabled Signals. Existing run uniqueness
prevents duplicate work for a turn/version. Configuration changes can create new
runs for turns inside the selected time window. Disabling a Signal prevents new
runs; it does not cancel already queued work. One shared model is imported from
classifier/config.py and recorded per run. The frustration classifier is unchanged.

A session-level Postgres advisory lock permits only one worker command at a time
(status is read-only and does not acquire it). At startup, abandoned running jobs
become failed and can be retried manually. Pending jobs survive restarts. Retrying
keeps the original run ID, version, and model; it reuses saved evidence, fetching
Laminar again only if evidence was never saved. A successful run cannot be retried.

## Evidence and output

The worker fetches all spans in the target trace using Laminar's existing SQL
client. It retains parent IDs, timestamps, inputs/outputs and ordered message
arrays. Explicit child-ID lists encode the tree without duplicating span content.
Sibling ordering is by UTC start timestamp then span ID (tie breaker only).
Concurrent spans are not assigned a causal order. Missing parents or timestamps
are flagged; wrong-trace IDs, duplicate IDs, cycles and empty trace results fail.
A completed trace is assumed based on the upstream sync settling policy; missing
or late-exported spans cannot always be detected. Prior conversation turns come
from turns.item and are context, not sources of target-trace span citations.

The snapshot stores conversation context, reconstructed trace, engine instruction,
Signal instruction, custom output schema and model. The model is asked for JSON
with a `findings` array; an empty array means successful analysis with no events.
Each finding contains:

```json
{
  "summary": "The assistant claimed a booking succeeded despite a failed tool call.",
  "severity": "warning",
  "evidence": "The booking tool returned failed before the assistant said Booked.",
  "supporting_span_ids": ["00000000-0000-0000-0000-000000000001"],
  "payload": {"claimed_action": "Book campsite"}
}
```

The payload must match the Signal's output_schema. Standard fields and any cited
UUIDs are validated too. Span IDs may be null for compatibility; a supplied list
must be nonempty and belong to the target trace. All findings must validate before
any are saved. Events and successful run completion commit together. Failures
record a safe error category separately; provider bodies and credentials are not
stored in errors. Snapshot data itself contains conversation/tool content.

The Responses API is used in JSON-object mode with local JSON Schema validation,
so custom schemas need not meet provider-specific strict-schema restrictions.
External schema references are not fetched; use self-contained schemas. Invalid,
refused, incomplete or oversized model responses fail instead of becoming no-match
runs. Large traces are sent whole for now; span search and automatic truncation
are deferred. Model/JSON-mode support still requires verification with your actual
provider credentials. Tests use simulated model and Laminar responses, never paid
requests. Valid citations establish provenance, not correctness; human review
remains necessary.

## Verification

```sh
TEST_DATABASE_URL='<disposable-test-database>' python -m unittest discover -s tests -v
```

Tests create isolated schemas. No application database migration is applied by the
worker tests. The dashboard displays saved runs and events.

The dashboard now exposes Signals, Runs and Events under the Signals navigation
tab. Its Retry analysis action queues the original failed run for this worker;
keep `python -m detection.run watch` running to process queued retries. Refresh
loads current status. This UI does not start the worker or apply migrations.

Backfills are also available in Signals → Definitions → Analyze previous
conversations. This queues only the selected enabled Signal and does not require
stopping watch mode. The CLI backfill command still requires exclusive worker
access and selects all enabled Signals.
