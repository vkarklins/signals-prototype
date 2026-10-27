# Signals prototype

A Signals feature (named behaviors detected in LLM conversations, like User Frustration) built on top of an
unmodified, self-hosted [Laminar](https://github.com/lmnr-ai/lmnr). We talk to Laminar only as a service:
traces go in through its SDK, come back out through its SQL API, and our own pipeline classifies, stores and shows them.

## Layout

| Folder | What's in it |
| --- | --- |
| `sync/` | Track A: poll Laminar's SQL API and reconstruct conversations |
| `classifier/` | Track B: classify conversations, store results, show them |
| `backend/` | Read-only Python API for saved evaluation results |
| `frontend/` | React evaluation dashboard; see its README for setup |
| `docs/` | The seam contract (conversation shape) and decisions |
| `eval/labeling/` | Terminal tools for hand-labeling the evaluation sample |
| `eval/labels/` | Our label files and agreement reports |
| `eval/sample-key.csv` | Scenario and dev/test split for each sampled turn; open only after labeling |

The synthetic traffic comes from a separate app (park_demo), which plays the customer whose traces we read.

## Labeling the sample

See [`eval/labeling/README.md`](eval/labeling/README.md).

## Evaluation dashboard

See [`frontend/README.md`](frontend/README.md) to configure Postgres, save classifier scores, and run the API and React page. The dashboard loads results automatically without file uploads.

## Database on macOS, Windows, or Linux

Install [Docker with Compose](https://docs.docker.com/compose/install/) and start Docker. Create a root `.env` from `.env.example`, keeping any existing API key. Set `POSTGRES_PASSWORD` and the matching password in `DATABASE_URL`, then run:

```bash
docker compose up -d --wait db
```

This creates the database and tables on the first startup. Postgres is available on `localhost:5433`; data persists in a Docker volume. See the [dashboard setup](frontend/README.md#set-up-the-database) for connection settings and commands to stop or inspect the database.
