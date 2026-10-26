# eval/evaluate_frustration.py
import json
from pathlib import Path

from classifier.frustration import classify

GOLD = Path(__file__).parent / "gold" / "frustration-v2.jsonl"


def evaluate(split="dev", threshold=0.5):
    cases = [
        json.loads(line)
        for line in GOLD.read_text().splitlines()
        if line and json.loads(line)["split"] == split
    ]

    results = [
        (
            case["expected"] == "yes",
            classify(case["conversation"]) >= threshold,
        )
        for case in cases
    ]

    hits = sum(expected and predicted for expected, predicted in results)
    misses = sum(expected and not predicted for expected, predicted in results)
    false_alarms = sum(not expected and predicted for expected, predicted in results)

    precision = hits / (hits + false_alarms) if hits + false_alarms else 0
    recall = hits / (hits + misses) if hits + misses else 0

    print(f"{split}: {len(cases)} cases, threshold {threshold}")
    print(f"Hits: {hits} | Misses: {misses} | False alarms: {false_alarms}")
    print(f"Precision: {precision:.2f} | Recall: {recall:.2f}")


if __name__ == "__main__":
    evaluate()  # Tune with dev first.
    # After tuning, run evaluate(split="test") once for the final check.
