"""文本型工具调用的参数类型修正。

文本格式（anthropic 风格 <invoke>/<parameter>、DSML、call:tool{args}）只携带字符串，
而工具签名可能是 int/bool/list。若不做修正，"x": "608" 传进期望 int 的 browser_page
会直接崩。这里只做保守转换：转不了就原样返回，让工具自己报可读错误。
"""
from ethan.tools.registry import _coerce_by_schema


def test_integer_coerced_from_string():
    assert _coerce_by_schema("608", {"type": "integer"}) == 608
    assert _coerce_by_schema("-3", {"type": "integer"}) == -3
    assert _coerce_by_schema(" 42 ", {"type": "integer"}) == 42


def test_integer_unparsable_left_alone():
    assert _coerce_by_schema("abc", {"type": "integer"}) == "abc"
    assert _coerce_by_schema("", {"type": "integer"}) == ""


def test_number_coerced():
    assert _coerce_by_schema("1.5", {"type": "number"}) == 1.5
    assert _coerce_by_schema("2", {"type": "number"}) == 2.0


def test_boolean_only_known_literals():
    assert _coerce_by_schema("true", {"type": "boolean"}) is True
    assert _coerce_by_schema("False", {"type": "boolean"}) is False
    assert _coerce_by_schema("1", {"type": "boolean"}) is True
    # 关键：任意非空串不能被当成 True
    assert _coerce_by_schema("yes please", {"type": "boolean"}) == "yes please"
    assert _coerce_by_schema("yes", {"type": "boolean"}) == "yes"


def test_string_untouched():
    assert _coerce_by_schema("608", {"type": "string"}) == "608"


def test_array_object_from_json_string():
    assert _coerce_by_schema("[1,2]", {"type": "array"}) == [1, 2]
    assert _coerce_by_schema('{"a": 1}', {"type": "object"}) == {"a": 1}
    # 形状不对 → 原样返回
    assert _coerce_by_schema('"just a string"', {"type": "array"}) == '"just a string"'
    assert _coerce_by_schema("[1,2]", {"type": "object"}) == "[1,2]"


def test_non_string_values_untouched():
    """原生 tool_calls 已带正确类型，不能被二次转换破坏。"""
    assert _coerce_by_schema(608, {"type": "integer"}) == 608
    assert _coerce_by_schema(True, {"type": "boolean"}) is True
    assert _coerce_by_schema([1, 2], {"type": "array"}) == [1, 2]


def test_missing_or_composite_schema_untouched():
    """缺少 type / 复合 schema（anyOf）时不做猜测。"""
    assert _coerce_by_schema("608", {}) == "608"
    assert _coerce_by_schema("608", {"anyOf": [{"type": "integer"}, {"type": "string"}]}) == "608"
    assert _coerce_by_schema("608", None) == "608"
