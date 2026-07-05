from __future__ import annotations

import pytest

from openharness.automation.templates import TemplateRenderError, render_template


def test_template_preserves_whole_value_types_and_renders_embedded_scalars() -> None:
    context = {
        "event": {"payload": {"labels": ["one", "two"], "active": True}},
        "run": {"id": "run-1"},
        "steps": {"assess": {"output": {"summary": "Production down", "count": 2}}},
    }
    template = {
        "labels": "${event.payload.labels}",
        "message": "${steps.assess.output.summary} (${steps.assess.output.count})",
        "active": "${event.payload.active}",
    }

    assert render_template(template, context) == {
        "labels": ["one", "two"],
        "message": "Production down (2)",
        "active": True,
    }


def test_template_rejects_missing_or_embedded_structured_reference() -> None:
    context = {"event": {"payload": {"labels": ["one"]}}, "run": {}, "steps": {}}
    with pytest.raises(TemplateRenderError, match="does not exist"):
        render_template("${event.payload.missing}", context)
    with pytest.raises(TemplateRenderError, match="must occupy the whole value"):
        render_template("labels=${event.payload.labels}", context)


def test_template_rejects_unsupported_reference_and_output_overflow() -> None:
    context = {"event": {"payload": {"text": "long"}}, "run": {}, "steps": {}}
    with pytest.raises(TemplateRenderError, match="invalid or unsupported"):
        render_template("${secrets.token}", context)
    with pytest.raises(TemplateRenderError, match="exceeds 4 bytes"):
        render_template("${event.payload.text}", context, max_rendered_bytes=4)


def test_template_rejects_non_json_numbers_and_object_keys() -> None:
    with pytest.raises(TemplateRenderError, match="JSON serializable"):
        render_template(float("nan"), {"event": {}, "run": {}, "steps": {}})
    with pytest.raises(TemplateRenderError, match="string keys"):
        render_template({1: "value"}, {"event": {}, "run": {}, "steps": {}})
