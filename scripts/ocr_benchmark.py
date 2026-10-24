"""Score authorized OCR evaluation files; never invokes a provider."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from apps.ocr.benchmark import evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.dataset, args.predictions):
        if path.stat().st_size > 12_000_000:
            parser.error("Evaluation file exceeds 12 MB")
    report = evaluate(
        json.loads(args.dataset.read_text(encoding="utf-8")),
        json.loads(args.predictions.read_text(encoding="utf-8")),
    )
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"status": report["status"], "samples": report["sample_count"]}))
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
