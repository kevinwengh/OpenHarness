"""Safe JSON-value interpolation for automation step arguments."""

from __future__ import annotations

import json
import re
from typing import Any

MAX_TEMPLATE_DEPTH = 24
MAX_RENDERED_BYTES = 256 * 1024
_FULL_REFERENCE = re.compile(r"^\$\{((?:event|run|steps)(?:\.[A-Za-z0-9_-]+)+)\}$")
_REFERENCE = re.compile(r"\$\{((?:event|run|steps)(?:\.[A-Za-z0-9_-]+)+)\}")


class TemplateRenderError(ValueError):
    """Raised before an action executes when a workflow template is invalid."""


def render_template(
    template: Any,
    context: dict[str, Any],
    *,
    max_rendered_bytes: int = MAX_RENDERED_BYTES,
) -> Any:
    """Render references recursively while preserving whole-value JSON types."""

    rendered = _render(template, context, depth=0)
    try:
        encoded = json.dumps(
            rendered,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TemplateRenderError(f"rendered value is not JSON serializable: {exc}") from exc
    if len(encoded) > max_rendered_bytes:
        raise TemplateRenderError(f"rendered value exceeds {max_rendered_bytes} bytes")
    return rendered


def _render(template: Any, context: dict[str, Any], *, depth: int) -> Any:
    """Recursively render a JSON template while enforcing nesting depth."""

    if depth > MAX_TEMPLATE_DEPTH:
        raise TemplateRenderError(f"template exceeds nesting depth {MAX_TEMPLATE_DEPTH}")
    if isinstance(template, dict):
        if any(not isinstance(key, str) for key in template):
            raise TemplateRenderError("template objects require string keys")
        return {
            key: _render(value, context, depth=depth + 1)
            for key, value in template.items()
        }
    if isinstance(template, list):
        return [_render(value, context, depth=depth + 1) for value in template]
    if not isinstance(template, str):
        return template
    full = _FULL_REFERENCE.fullmatch(template)
    if full:
        return _resolved(context, full.group(1))

    def replace(match: re.Match[str]) -> str:
        """Render one embedded scalar reference as deterministic text."""

        value = _resolved(context, match.group(1))
        if isinstance(value, (dict, list)):
            raise TemplateRenderError(
                f"reference {match.group(1)!r} is structured and must occupy the whole value"
            )
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    rendered = _REFERENCE.sub(replace, template)
    if "${" in rendered:
        raise TemplateRenderError("template contains an invalid or unsupported reference")
    return rendered


def _resolved(context: dict[str, Any], path: str) -> Any:
    """Resolve one validated reference path or raise a render error."""

    sentinel = object()
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            current = sentinel
            break
        current = current[part]
    if current is sentinel:
        raise TemplateRenderError(f"template reference {path!r} does not exist")
    return current
