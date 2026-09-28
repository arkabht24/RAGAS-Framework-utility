"""Declarative JSON request/response mapping utilities."""

from __future__ import annotations

import re
from typing import Any

from jsonpath_ng import parse


TOKEN = re.compile(r"{{\s*([\w.]+)\s*}}")


def _lookup(case: dict[str, Any], path: str) -> Any:
    value: Any = case
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(f"Dataset field '{path}' is not present in this case.")
        value = value[part]
    return value


def render_template(value: Any, case: dict[str, Any]) -> Any:
    """Render {{ dataset.field }} placeholders without evaluating code."""
    if isinstance(value, dict):
        return {key: render_template(item, case) for key, item in value.items()}
    if isinstance(value, list):
        return [render_template(item, case) for item in value]
    if not isinstance(value, str):
        return value
    complete = TOKEN.fullmatch(value)
    if complete:
        return _lookup(case, complete.group(1))
    return TOKEN.sub(lambda match: str(_lookup(case, match.group(1))), value)


def extract(payload: Any, json_path: str | None, *, many: bool = False) -> Any:
    """Extract one field or a list using a JSONPath expression."""
    if not json_path:
        return [] if many else None
    matches = [match.value for match in parse(json_path).find(payload)]
    if many:
        return matches
    return matches[0] if matches else None


def normalize_contexts(values: list[Any]) -> list[str]:
    """Keep only text evidence; never invent context from citations."""
    return [value for value in values if isinstance(value, str) and value.strip()]
