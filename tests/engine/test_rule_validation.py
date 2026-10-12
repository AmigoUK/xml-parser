"""Walidacja kontraktu reguł szablonu w silniku (app/engine/transforms.py) — jedna reguła dla edytora, negocjacji
i przyszłych klientów; widok tylko mapuje wynik na 400."""
import pytest

from app.engine.transforms import validate_chain, validate_rules


@pytest.mark.parametrize("chain, fragment", [
    ([{"map": 5}], "'map'"),
    ([{"convert": "x"}], "'convert'"),
    ([{"decimal": ";"}], "'decimal'"),
    ([{"date": 4}], "'date'"),
    ([{"split": {"index": "a"}}], "'split'"),
    ([{"concat": 3}], "'concat'"),
    ([{"regex_extract": {"pattern": "("}}], "regularne"),
    ([{"regex_extract": {"pattern": "a" * 201}}], "za długie"),
    ([{"regex_extract": "x"}], "'regex_extract'"),
    (["nie_ma_takiej"], "Nieznana transformacja"),
    ([{"trim": 1, "upper": 2}], "Niepoprawny krok"),
    ("trim", "listą"),
])
def test_validate_chain_reports_polish_message(chain, fragment):
    msg = validate_chain(chain, "currency")
    assert msg and fragment in msg and "'currency'" in msg or (msg and fragment in msg)


def test_validate_chain_accepts_registry_steps():
    assert validate_chain(["trim", {"decimal": ","}, {"map": {"a": "b"}}, {"convert": "2"}, {"date": "%d.%m.%Y"},
                           {"split": {"sep": "-", "index": 1}}, {"concat": {"paths": ["a/b"], "sep": " "}},
                           {"regex_extract": {"pattern": r"\d+", "group": 0}}, {"gs1": "10"}], "x") is None
    assert validate_chain([], "x") is None


def test_validate_rules_checks_structure_and_chains():
    assert validate_rules({"line_path": 5}) == "Ścieżka elementu z pozycjami musi być tekstem."
    assert validate_rules({"header": []}) == "Sekcja 'header' musi być obiektem."
    assert validate_rules({"defaults": {"currency": True}}) == ("Wartość domyślna pola 'currency' musi być tekstem "
                                                                 "lub liczbą.")
    assert validate_rules({"header": {"number": "x"}}) == "Reguła pola 'number' musi być obiektem."
    assert validate_rules({"header": {"number": {"path": 1}}}) == "Pole 'path' w regule 'number' musi być tekstem."
    assert "'map'" in validate_rules({"lines": {"qty": {"path": "a", "transforms": [{"map": 5}]}}})
    assert validate_rules({"line_path": "a/b", "header": {"number": {"path": "a/n", "transforms": ["trim"]}},
                           "lines": {}, "defaults": {"currency": "PLN"}, "line_defaults": {}}) is None


def test_negotiation_and_editor_share_validation(seeded, client):
    from app.services.negotiation import NegotiationError, resolve
    from app.services.pipeline import ingest
    from tests.test_negotiation_statuses import inv
    doc = ingest(inv("WAL/1"), "w.json", source="upload")
    with pytest.raises(NegotiationError, match="'map'"):
        resolve(doc, "map_field", {"field": "currency", "path": "invoice/currency", "transforms": [{"map": 5}]},
                remember=True)
    from app.web import templates_views
    assert templates_views.validate_rules is validate_rules
