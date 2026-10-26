# Signals prototype

A Signals feature (named behaviors detected in LLM conversations, like User Frustration) built on top of an
unmodified, self-hosted [Laminar](https://github.com/lmnr-ai/lmnr). We talk to Laminar only as a service:
traces go in through its SDK, come back out through its SQL API, and our own pipeline classifies, stores and shows them.

## Layout

| Folder | What's in it |
| --- | --- |
| `sync/` | Track A: poll Laminar's SQL API and reconstruct conversations |
| `classifier/` | Track B: classify conversations, store results, show them |
| `docs/` | The seam contract (conversation shape) and decisions |
| `eval/labeling/` | Terminal tools for hand-labeling the evaluation sample |
| `eval/labels/` | Our label files and agreement reports |
| `eval/sample-key.csv` | Scenario and dev/test split for each sampled turn; open only after labeling |

The synthetic traffic comes from a separate app (park_demo), which plays the customer whose traces we read.

## Labeling the sample

See [`eval/labeling/README.md`](eval/labeling/README.md).
