import json
from frontend.main import _parse_a2ui_from_text, _clean_text_around_a2ui
from app.a2ui_utils import _surface_is_renderable, _component_ids_and_refs


def test_parse_a2ui_from_tags():
    text = '<a2ui-json>[{"beginRendering": {"root": "r1", "surfaceId": "s1"}}]</a2ui-json>'
    parsed = _parse_a2ui_from_text(text)
    assert len(parsed) == 1
    assert parsed[0]["beginRendering"]["root"] == "r1"

    clean = _clean_text_around_a2ui(text)
    assert clean == ""


def test_parse_a2ui_from_markdown():
    text = """Here is your card:
```json
[
  {"beginRendering": {"root": "r1", "surfaceId": "s1"}},
  {"surfaceUpdate": {"surfaceId": "s1", "components": [{"id": "r1", "component": {"Card": {"child": "c1"}}}]}}
]
```
Let me know if you need anything else!"""
    parsed = _parse_a2ui_from_text(text)
    assert len(parsed) == 2
    assert parsed[0]["beginRendering"]["root"] == "r1"

    clean = _clean_text_around_a2ui(text)
    assert "Here is your card:" in clean
    assert "Let me know if you need anything else!" in clean
    assert "beginRendering" not in clean


def test_surface_is_renderable():
    messages = [
        {"beginRendering": {"root": "r1", "surfaceId": "s1"}},
        {"surfaceUpdate": {"surfaceId": "s1", "components": [{"id": "r1", "component": {"Card": {"child": "c1"}}}]}}
    ]
    assert _surface_is_renderable(messages) is True

    ids, refs = _component_ids_and_refs(messages[1]["surfaceUpdate"]["components"])
    assert "r1" in ids
    assert "c1" in refs
