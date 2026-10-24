"""Offline scoring only. No network, image upload, or vendor inference."""

import re
import statistics
import unicodedata
from collections import Counter

STRATA = ("grade_band", "writing", "question_type", "quality")
TOKEN = re.compile(r"\\[a-zA-Z]+|\d+(?:\.\d+)?|[^\w\s]|[a-zA-Z]+", re.UNICODE)


def normalized(value):
    return "".join(unicodedata.normalize("NFC", value).split())


def distance(left, right):
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        next_row = [i]
        for j, b in enumerate(right, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = next_row
    return row[-1]


def region_iou(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    intersection = max(0, min(a[0] + a[2], b[0] + b[2]) - x) * max(
        0, min(a[1] + a[3], b[1] + b[3]) - y
    )
    return intersection / (a[2] * a[3] + b[2] * b[3] - intersection)


def region_matches(expected, actual):
    # Maximum bipartite matching; greedy overlap can undercount neighboring questions.
    assigned = {}

    def match(index, visited):
        for j, box in enumerate(actual):
            if j in visited or region_iou(expected[index], box) < 0.5:
                continue
            visited.add(j)
            if j not in assigned or match(assigned[j], visited):
                assigned[j] = index
                return True
        return False

    return sum(match(i, set()) for i in range(len(expected)))


def evaluate(dataset, predictions):
    samples = dataset.get("samples", [])
    if not isinstance(samples, list) or len(samples) > 1000:
        raise ValueError("samples must be a list of at most 1000 items")
    actual = {}
    for item in predictions.get("samples", []):
        if item["id"] in actual:
            raise ValueError("duplicate prediction id")
        actual[item["id"]] = item
    reasons, scores, ids, hashes = set(), [], set(), set()
    scored_ids = []
    stratified = {key: {} for key in STRATA}
    if not dataset.get("dataset_version") or not predictions.get("run_metadata"):
        reasons.add("DATASET_AND_RUN_VERSION_REQUIRED")
    counts = {key: Counter() for key in STRATA}
    for sample in samples:
        identifier = sample["id"]
        if identifier in ids or not re.fullmatch(r"[a-f0-9]{64}", sample.get("sha256", "")):
            raise ValueError("duplicate id or invalid image sha256")
        ids.add(identifier)
        if sample["sha256"] in hashes:
            raise ValueError("duplicate image in evaluation set")
        hashes.add(sample["sha256"])
        for key in STRATA:
            value = sample.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("missing sample stratum")
            counts[key][value] += 1
        if not all(sample.get(key) is True for key in ("authorized", "deidentified")):
            reasons.add("UNAUTHORIZED_OR_IDENTIFIABLE_SAMPLE")
        if sample.get("synthetic") is not False or not sample.get("authorization_ref"):
            reasons.add("REAL_AUTHORIZED_SAMPLES_REQUIRED")
        prediction = actual.get(identifier)
        if prediction is None:
            reasons.add("MISSING_PREDICTIONS")
            continue
        expected, result = sample["expected_text"], prediction["text"]
        if any(not isinstance(s, str) or not 1 <= len(s) <= 4000 for s in (expected, result)):
            raise ValueError("text length must be 1..4000")
        expected, result = normalized(expected), normalized(result)
        if not expected:
            raise ValueError("empty reference text")
        formulas, recognized = sample["formulas"], prediction["formulas"]
        if (
            not isinstance(formulas, list)
            or not isinstance(recognized, list)
            or max(len(formulas), len(recognized)) > 40
        ):
            raise ValueError("formula list must contain at most 40 formulas")
        if any(not isinstance(f, str) or len(f) > 1000 for f in formulas + recognized):
            raise ValueError("invalid formula")
        ft, rt = TOKEN.findall(" ".join(formulas)), TOKEN.findall(" ".join(recognized))
        expected_boxes, boxes = sample["regions"], prediction["regions"]
        for group in (expected_boxes, boxes):
            if not isinstance(group, list) or len(group) > 40:
                raise ValueError("invalid regions")
            for box in group:
                if (
                    not isinstance(box, list)
                    or len(box) != 4
                    or any(type(v) is not int for v in box)
                    or min(box[:2]) < 0
                    or min(box[2:]) <= 0
                ):
                    raise ValueError("regions use nonnegative integer x,y and positive w,h")
        seconds = prediction.get("correction_seconds")
        if type(seconds) not in (int, float) or not 0 <= seconds <= 86400:
            raise ValueError("human correction_seconds required")
        scores.append(
            {
                "cer": distance(expected, result) / len(expected),
                "formula_token_error": distance(ft, rt) / max(1, len(ft)),
                "key_symbol_error": distance(TOKEN.findall(expected), TOKEN.findall(result))
                / max(1, len(TOKEN.findall(expected))),
                "segmentation_recall": region_matches(expected_boxes, boxes) / len(expected_boxes)
                if expected_boxes
                else 1.0,
                "correction_seconds": seconds,
            }
        )
        scored_ids.append(identifier)
        for key in STRATA:
            stratified[key].setdefault(sample[key], []).append(scores[-1])
    if not samples:
        reasons.add("NO_SAMPLES")
    if set(actual) - ids:
        raise ValueError("prediction contains unknown sample ids")
    thresholds = dataset.get("thresholds", {})
    limits = ("cer", "formula_token_error", "key_symbol_error", "correction_seconds")
    valid_limits = all(
        type(thresholds.get(key)) in (float, int) and thresholds[key] >= 0 for key in limits
    )
    recall = thresholds.get("segmentation_recall")
    coverage = dataset.get("minimum_per_stratum", {})
    if (
        not dataset.get("threshold_approval_ref")
        or not valid_limits
        or type(recall) not in (float, int)
        or not 0 <= recall <= 1
        or set(coverage) != set(STRATA)
    ):
        reasons.add("APPROVED_THRESHOLDS_AND_COVERAGE_REQUIRED")
    for key in STRATA:
        required = coverage.get(key, {})
        if not isinstance(required, dict) or not required:
            reasons.add("STRATA_COVERAGE_INCOMPLETE")
            continue
        for value, minimum in required.items():
            if type(minimum) is not int or minimum < 1 or counts[key][value] < minimum:
                reasons.add("STRATA_COVERAGE_INCOMPLETE")
    metrics = {key: statistics.mean(s[key] for s in scores) for key in scores[0]} if scores else {}
    if scores:
        metrics["correction_seconds"] = statistics.median(s["correction_seconds"] for s in scores)
    status = (
        "BLOCKED"
        if reasons
        else "PASS"
        if all(metrics[k] <= thresholds[k] for k in limits)
        and metrics["segmentation_recall"] >= recall
        else "FAIL"
    )
    return {
        "status": status,
        "reasons": sorted(reasons),
        "sample_count": len(samples),
        "scored_count": len(scores),
        "metrics": metrics,
        "dataset_version": dataset.get("dataset_version"),
        "run_metadata": predictions.get("run_metadata"),
        "stratified_metrics": {
            key: {
                value: {metric: statistics.mean(s[metric] for s in group) for metric in group[0]}
                for value, group in values.items()
            }
            for key, values in stratified.items()
        },
        "failure_cases": [
            {"id": identifier, **score}
            for identifier, score in zip(scored_ids, scores, strict=True)
            if score["cer"] > 0
            or score["formula_token_error"] > 0
            or score["segmentation_recall"] < 1
        ],
        "strata_counts": {key: dict(value) for key, value in counts.items()},
        "scope": "offline supplied predictions; not proof of live provider integration",
    }
