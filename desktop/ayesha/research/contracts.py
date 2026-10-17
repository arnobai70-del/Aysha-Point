"""Research contracts: the JSON Schemas in `contracts/research/` and a small validator for exactly the keywords they use.

Why a built-in validator: the base install stays dependency-free (no jsonschema package), and the schemas stay the
single source of truth. `unsupported_keywords` lets the tests prove no schema relies on a keyword this validator
would silently ignore. Research schemas carry their own versions (`research.<name>/1`), independent of the live
signal schema 1.1 and phone wire format 4, which they never touch.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "contracts" / "research"
SCHEMAS = {
    "research.config/1": "research-config.schema.json",
    "research.market_bar/1": "market-bar.schema.json",
    "research.quality_report/1": "quality-report.schema.json",
    "research.dataset_manifest/1": "dataset-manifest.schema.json",
    "research.candidate/1": "research-candidate.schema.json",
    "research.result/1": "research-result.schema.json",
    "research.strategy/1": "strategy-plugin.schema.json",
    "research.model_card/1": "model-card.schema.json",
    "research.comparison/1": "comparison.schema.json",
    "research.news-snapshot/1": "news-snapshot.schema.json",
    "research.feed-audit/1": "feed-audit.schema.json",
}
SUPPORTED = {"$schema", "$id", "$comment", "title", "description", "examples", "default", "type", "enum", "const",
             "required", "properties", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
             "minimum", "maximum", "exclusiveMinimum", "minLength", "maxLength", "pattern", "format"}
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
    "null": lambda v: v is None,
}


class ContractError(ValueError):
    """An instance does not satisfy its research contract."""


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    if name not in SCHEMAS:
        raise KeyError(f"unknown research contract {name!r}")
    return json.loads((SCHEMA_DIR / SCHEMAS[name]).read_text(encoding="utf-8"))


def utc_ok(v: str) -> bool:
    if not _UTC.match(v):
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _same(a: Any, b: Any) -> bool:
    """JSON equality: true is not 1, false is not 0."""
    return type(a) is type(b) and a == b if isinstance(a, bool) or isinstance(b, bool) else a == b


def _check(v: Any, s: dict[str, Any], path: str, errs: list[str]) -> None:
    if "const" in s and not _same(v, s["const"]):
        errs.append(f"{path}: must be {s['const']!r}")
        return
    if "enum" in s and not any(_same(v, x) for x in s["enum"]):
        errs.append(f"{path}: {v!r} not one of {s['enum']}")
        return
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_TYPES[t](v) for t in types):
            errs.append(f"{path}: expected {'/'.join(types)}, got {type(v).__name__}")
            return
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            errs.append(f"{path}: {v} < minimum {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errs.append(f"{path}: {v} > maximum {s['maximum']}")
        if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
            errs.append(f"{path}: {v} <= {s['exclusiveMinimum']}")
    if isinstance(v, str):
        if "minLength" in s and len(v) < s["minLength"]:
            errs.append(f"{path}: shorter than {s['minLength']}")
        if "maxLength" in s and len(v) > s["maxLength"]:
            errs.append(f"{path}: longer than {s['maxLength']}")
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: does not match {s['pattern']}")
        if s.get("format") == "utc-date-time" and not utc_ok(v):
            errs.append(f"{path}: not a UTC time like 2026-01-05T10:00:00Z")
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            errs.append(f"{path}: fewer than {s['minItems']} items")
        if "maxItems" in s and len(v) > s["maxItems"]:
            errs.append(f"{path}: more than {s['maxItems']} items")
        if s.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
            errs.append(f"{path}: items not unique")
        if "items" in s:
            for i, x in enumerate(v):
                _check(x, s["items"], f"{path}[{i}]", errs)
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}: missing {k!r}")
        props = s.get("properties", {})
        extra = s.get("additionalProperties", True)
        for k, x in v.items():
            if k in props:
                _check(x, props[k], f"{path}.{k}", errs)
            elif extra is False:
                errs.append(f"{path}: unexpected field {k!r}")
            elif isinstance(extra, dict):
                _check(x, extra, f"{path}.{k}", errs)


def validate(instance: Any, name: str) -> list[str]:
    errs: list[str] = []
    _check(instance, load_schema(name), "$", errs)
    return errs


def check(instance: Any, name: str) -> Any:
    errs = validate(instance, name)
    if errs:
        raise ContractError(f"{name}: " + "; ".join(errs[:8]) + (f" (+{len(errs) - 8} more)" if len(errs) > 8 else ""))
    return instance


def unsupported_keywords(schema: Any, path: str = "$") -> list[str]:
    """Keywords this validator does not implement (must be empty for every research schema)."""
    out: list[str] = []
    if isinstance(schema, dict):
        for k, v in schema.items():
            if k not in SUPPORTED:
                out.append(f"{path}.{k}")
            if k == "properties":
                for pk, pv in v.items():
                    out += unsupported_keywords(pv, f"{path}.properties.{pk}")
            elif k in ("items", "additionalProperties") and isinstance(v, dict):
                out += unsupported_keywords(v, f"{path}.{k}")
    return out
