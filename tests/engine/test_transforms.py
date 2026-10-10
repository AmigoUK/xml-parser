import pytest

from app.engine.transforms import REGISTRY, TransformContext, TransformError, apply_chain
from app.engine.tree import Node, SourceTree


def test_simple_chain():
    assert apply_chain(" 0% ", ["trim", "strip_percent", "decimal"]) == "0"
    assert apply_chain("abc", ["upper"]) == "ABC"
    assert apply_chain(None, ["trim"]) is None


def test_strip_ai_prefix():
    assert apply_chain("0105909999000013", ["strip_ai_prefix"]) == "05909999000013"
    assert apply_chain("5909999000013", ["strip_ai_prefix"]) == "5909999000013"


def test_gs1_transform():
    code = "01059099990000131527070910L2607"
    assert apply_chain(code, [{"gs1": "10"}]) == "L2607"
    assert apply_chain(code, [{"gs1": "15"}]) == "2027-07-09"
    assert apply_chain(code, [{"gs1": "01"}]) == "05909999000013"
    with pytest.raises(TransformError):
        apply_chain(code, [{"gs1": "17"}])


def test_date_and_map_and_convert():
    assert apply_chain("09-10-26", [{"date": "%d-%m-%y"}]) == "2026-10-09"
    assert apply_chain("6", [{"map": {"6": "przelew", "1": "gotówka"}}]) == "przelew"
    assert apply_chain("x", [{"map": {"6": "przelew"}}]) == "x"
    assert apply_chain("2,5", [{"convert": "12"}]) == "30"
    assert apply_chain("10", ["negate"]) == "-10"


def test_regex_split_constant():
    assert apply_chain("FV 123/2026", [{"regex_extract": {"pattern": r"(\d+)/", "group": 1}}]) == "123"
    assert apply_chain("00-952 Przykładowo", [{"split": {"sep": " ", "index": 0}}]) == "00-952"
    assert apply_chain(None, [{"constant": "PLN"}]) == "PLN"
    with pytest.raises(TransformError):
        apply_chain("x", [{"regex_extract": {"pattern": "a" * 201}}])


def test_concat_uses_context():
    root = Node("R")
    root.add(Node("A", "ul. X"))
    root.add(Node("B", "1"))
    ctx = TransformContext(tree=SourceTree(root, "xml"))
    assert apply_chain(None, [{"concat": {"paths": ["R/A", "R/B"], "sep": " "}}], ctx) == "ul. X 1"


def test_unknown_transform():
    with pytest.raises(TransformError, match="Nieznana transformacja"):
        apply_chain("x", ["eval"])


def test_registry_whitelist():
    assert set(REGISTRY) == {
        "trim", "upper", "lower", "decimal", "strip_percent", "date", "regex_extract", "map",
        "convert", "constant", "concat", "split", "negate", "gs1", "strip_ai_prefix",
    }
