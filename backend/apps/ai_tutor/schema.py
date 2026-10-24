import json
import math
import re

SCHEMA_VERSION = "math-analysis-v1"
CATEGORIES = (
    "concept",
    "formula",
    "calculation",
    "reading",
    "missing_step",
    "diagram",
    "transfer",
    "unknown",
)


def string_schema(maximum, minimum=0):
    return {"type": "string", "minLength": minimum, "maxLength": maximum}


def list_schema(count, length):
    return {"type": "array", "maxItems": count, "items": string_schema(length, 1)}


PROPERTIES = {
    "schema_version": {"const": SCHEMA_VERSION},
    "verification_status": {"const": "unverified"},
    "understanding": string_schema(2000, 1),
    "error_location": string_schema(1000),
    "answer_candidate": string_schema(1500),
    "conditions": list_schema(12, 400),
    "solution_steps": list_schema(12, 800),
    "knowledge_points": list_schema(12, 80),
    "uncertainties": list_schema(12, 400),
    "review_items": list_schema(12, 400),
    "root_causes": {
        "type": "array",
        "minItems": 1,
        "maxItems": 5,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["category", "evidence", "confidence"],
            "properties": {
                "category": {"enum": list(CATEGORIES)},
                "evidence": string_schema(600, 1),
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
    "hints": {
        "type": "array",
        "minItems": 1,
        "maxItems": 3,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["level", "text"],
            "properties": {
                "level": {"type": "integer", "minimum": 1, "maximum": 3},
                "text": string_schema(600, 1),
            },
        },
    },
}
JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": SCHEMA_VERSION,
    "type": "object",
    "additionalProperties": False,
    "properties": PROPERTIES,
    "required": list(PROPERTIES),
}


def safe_text(value, maximum, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError("Invalid text")
    if re.search(r"</?[A-Za-z][^>]*>|javascript\s*:|data\s*:\s*text/html", value, re.I):
        raise ValueError("Executable markup is not accepted")
    if re.search(
        r"智商低|天生笨|学习障碍|多动症|注意力缺陷|永远学不会|没有数学天赋|"
        r"\blow IQ\b|\bADHD\b|\bdyscalculia\b",
        value,
        re.I,
    ):
        raise ValueError("Unsupported learner diagnosis or trait label")
    return value


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Unexpected schema fields")


def text_list(value, count, length):
    if not isinstance(value, list) or len(value) > count:
        raise ValueError("Invalid list")
    for item in value:
        safe_text(item, length)


def validate(value, *, has_student_work):
    exact(
        value,
        (
            "schema_version",
            "understanding",
            "conditions",
            "solution_steps",
            "error_location",
            "root_causes",
            "knowledge_points",
            "hints",
            "uncertainties",
            "review_items",
            "answer_candidate",
            "verification_status",
        ),
    )
    if value["schema_version"] != SCHEMA_VERSION or value["verification_status"] != "unverified":
        raise ValueError("Unverified analysis required")
    if not has_student_work and value["error_location"]:
        raise ValueError("Error location requires student work")
    for name, maximum in (
        ("understanding", 2000),
        ("error_location", 1000),
        ("answer_candidate", 1500),
    ):
        safe_text(value[name], maximum, empty=name != "understanding")
    for name, count, maximum in (
        ("conditions", 12, 400),
        ("solution_steps", 12, 800),
        ("knowledge_points", 12, 80),
        ("uncertainties", 12, 400),
        ("review_items", 12, 400),
    ):
        text_list(value[name], count, maximum)
    if not isinstance(value["root_causes"], list) or not 1 <= len(value["root_causes"]) <= 5:
        raise ValueError("Root cause candidates required")
    for cause in value["root_causes"]:
        exact(cause, ("category", "evidence", "confidence"))
        if cause["category"] not in CATEGORIES or (
            not has_student_work and cause["category"] != "unknown"
        ):
            raise ValueError("Unsupported root cause claim")
        safe_text(cause["evidence"], 600)
        confidence = cause["confidence"]
        if (
            type(confidence) not in (int, float)
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Invalid confidence")
    hints = value["hints"]
    if not isinstance(hints, list) or not 1 <= len(hints) <= 3:
        raise ValueError("One to three hints required")
    for index, hint in enumerate(hints, 1):
        exact(hint, ("level", "text"))
        if type(hint["level"]) is not int or hint["level"] != index:
            raise ValueError("Hints must reveal in order")
        safe_text(hint["text"], 600)
    if len(json.dumps(value, ensure_ascii=False)) > 24000:
        raise ValueError("Analysis exceeds total limit")
    return value
