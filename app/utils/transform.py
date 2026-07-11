"""Payload transformation utilities for SafeRoute API.

Provides reusable functions for:
- Parsing webhook payloads (JSON, form-urlencoded)
- Resolving dot-notation paths in nested data structures
- Rendering template strings with {{field.path}} placeholders
"""

from __future__ import annotations
import json
import logging
import re
from typing import Any
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

# Regex for template placeholders: {{field.path}}
_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def resolve_dot_path(data: Any, path: str) -> Any:
    """Resolve a dot-separated path against a nested data structure.

    Supports dict keys and integer list indices. Returns ``None`` if any
    segment is missing rather than raising.

    Examples:
        >>> resolve_dot_path({"a": {"b": 1}}, "a.b")
        1
        >>> resolve_dot_path({"items": [10, 20]}, "items.0")
        10
        >>> resolve_dot_path({}, "missing.key")
        None

    Args:
        data: The root dict or list.
        path: Dot-separated field path.

    Returns:
        The resolved value or ``None``.
    """
    current = data
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def render_template(template: str, payload: dict[str, Any]) -> str:
    """Render a template string by replacing ``{{field.path}}`` placeholders.

    Uses :func:`resolve_dot_path` for nested access. Missing fields are
    replaced with an empty string.

    Args:
        template: The template string with ``{{...}}`` placeholders.
        payload: The parsed webhook payload.

    Returns:
        The rendered string.
    """

    def replacer(match: re.Match[str]) -> str:
        path = match.group(1)
        value = resolve_dot_path(payload, path)
        if value is None:
            return ""
        return str(value)

    return _TEMPLATE_PATTERN.sub(replacer, template)


def parse_payload(body: bytes, content_type: str) -> Any:
    """Parse the incoming request body into a dictionary.

    Supports JSON and form-urlencoded payloads. Falls back to an empty
    dict on parse failure.

    Args:
        body: Raw request body bytes.
        content_type: The ``Content-Type`` header value.

    Returns:
        Parsed payload as a dictionary.
    """
    if not body:
        return {}

    try:
        if "application/json" in content_type:
            return json.loads(body)

        # If content-type is missing, try JSON first, then fall back to form data.
        try:
            return json.loads(body)
        except Exception:
            try:
                decoded = body.decode("utf-8", errors="replace")
            except Exception as decode_exc:
                logger.warning("Failed to decode request body: %s", decode_exc)
                return {}
            return {k: v[0] for k, v in parse_qs(decoded).items()}
    except Exception as exc:
        logger.warning("Failed to parse payload: %s", exc)
        return {}
