"""Unit tests: strict JSON extraction + protocol validation."""

import pytest

from agent_controller import extract_json, validate_action


# --------------------------- extraction ---------------------------
def test_extract_plain_json():
    obj, err = extract_json('{"action": "final", "answer": "hi"}')
    assert err is None
    assert obj["action"] == "final"


def test_extract_with_code_fence():
    raw = '```json\n{"action": "final", "answer": "42"}\n```'
    obj, err = extract_json(raw)
    assert err is None
    assert obj["answer"] == "42"


def test_extract_with_surrounding_prose():
    raw = 'Sure! Here is the result:\n{"action": "tool", "tool": "calculate", "arguments": {"expression": "2+2"}}\nThanks.'
    obj, err = extract_json(raw)
    assert err is None
    assert obj["tool"] == "calculate"


def test_extract_nested_braces_and_strings():
    raw = '{"action": "final", "answer": "use {curly} braces \\"safely\\""}'
    obj, err = extract_json(raw)
    assert err is None
    assert "curly" in obj["answer"]


def test_extract_empty():
    obj, err = extract_json("")
    assert obj is None and err


def test_extract_no_json():
    obj, err = extract_json("no json here at all")
    assert obj is None and err


def test_extract_broken_json():
    obj, err = extract_json('{"action": "final", "answer": }')
    assert obj is None and err


# --------------------------- protocol validation ---------------------------
def test_validate_final():
    kind, payload, err = validate_action({"action": "final", "answer": "ok"})
    assert kind == "final" and payload == "ok" and err is None


def test_validate_tool():
    kind, payload, err = validate_action(
        {"action": "tool", "tool": "calculate", "arguments": {"expression": "1+1"}})
    assert kind == "tool"
    assert payload["tool"] == "calculate"
    assert payload["arguments"]["expression"] == "1+1"


@pytest.mark.parametrize("obj", [
    {"action": "banana"},
    {"action": "tool"},                       # missing tool name
    {"action": "tool", "tool": 123},          # bad tool type
    {"action": "final"},                      # missing answer
    {"action": "tool", "tool": "x", "arguments": "not-an-object"},
    ["not", "a", "dict"],
])
def test_validate_rejects_bad(obj):
    kind, _payload, err = validate_action(obj)
    assert kind is None and err
