"""Podpowiedzi mapowań — wyłącznie heurystyki (bez LLM)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import yaml
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from .canonical import (DATE, DECIMAL, GTIN, HEADER_FIELDS, LINE_FIELDS, LINE_KEYS, MONEY, PRICE,
                        FieldDef)
from .gs1 import GS1Error, is_valid_gtin, parse_gs1
from .transforms import TransformError, apply_chain
from .tree import SourceTree, relative_path
from .values import parse_date, to_decimal

DEFAULT_SYNONYMS = Path(__file__).resolve().parents[2] / "data" / "synonyms.yaml"
FIELDS_BY_KEY = {f.key: f for f in HEADER_FIELDS + LINE_FIELDS}
MULTI_USE = {"batch", "expiry_date"}
_CACHE: dict[Path, dict] = {}


def load_synonyms(path: Path | None = None) -> dict:
    p = Path(path or DEFAULT_SYNONYMS)
    if p not in _CACHE:
        with p.open(encoding="utf-8") as fh:
            _CACHE[p] = yaml.safe_load(fh) or {}
    return _CACHE[p]


@dataclass
class Candidate:
    path: str
    transforms: list = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    preview: str | None = None

    def to_dict(self) -> dict:
        return {"kind": "path", **asdict(self)}


def suffix_match(path: str, synonym: str) -> bool:
    segs = path.lower().split("/")
    s = synonym.lower().split("/")
    return len(s) <= len(segs) and segs[-len(s):] == s


def _tail(path: str, n: int = 2) -> str:
    return "/".join(path.lower().split("/")[-n:])


def learned_pairs(rule_sets: Iterable[dict]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for rules in rule_sets:
        for key, rule in ((rules or {}).get("header") or {}).items():
            if (rule or {}).get("path"):
                out[("header", _tail(rule["path"]))] = key
        for key, rule in ((rules or {}).get("lines") or {}).items():
            if (rule or {}).get("path"):
                out[("lines", rule["path"].lower())] = key
        if (rules or {}).get("line_path"):
            out[("line_path", rules["line_path"])] = "line_path"
    return out


def learned_line_paths(learned: dict | None) -> set[str]:
    return {k[1] for k in (learned or {}) if k[0] == "line_path"}


def _gs1_ais(value: str) -> dict[str, str]:
    if len(value) < 18 or not value.startswith("01"):
        return {}
    try:
        parsed = parse_gs1(value)
    except GS1Error:
        return {}
    return parsed if len(parsed) >= 2 else {}


def _detect(f: FieldDef, value: str) -> tuple[float, list] | None:
    v = value.strip()
    if f.kind == GTIN:
        if len(v) == 16 and v.startswith("01") and is_valid_gtin(v[2:]):
            return 0.6, ["strip_ai_prefix"]
        if len(v) >= 12 and is_valid_gtin(v):
            return 0.6, []
    if f.key == "batch":
        if "10" in _gs1_ais(v):
            return 0.7, [{"gs1": "10"}]
    if f.key == "expiry_date":
        ais = _gs1_ais(v)
        for ai in ("17", "15"):
            if ai in ais:
                return 0.7, [{"gs1": ai}]
    if f.kind == DATE:
        try:
            parse_date(v)
            return 0.4, []
        except ValueError:
            pass
    if f.key.endswith("tax_id") and re.fullmatch(r"[A-Z]{0,2}\d{8,12}", re.sub(r"[\s-]", "", v.upper())):
        return 0.4, []
    if f.kind in (MONEY, PRICE, DECIMAL):
        try:
            to_decimal(v)
            if re.fullmatch(r"[\d\s.,\-+%£€$]+", v):
                return 0.3, []
        except ValueError:
            pass
    return None


def _infer_transforms(f: FieldDef, value: str) -> list:
    v = (value or "").strip()
    if f.kind == GTIN and len(v) == 16 and v.startswith("01") and is_valid_gtin(v[2:]):
        return ["strip_ai_prefix"]
    if f.key == "vat_rate" and "%" in v:
        return ["strip_percent"]
    return []


def _preview(value: str | None, transforms: list) -> str | None:
    try:
        return apply_chain(value, transforms)
    except TransformError:
        return None


def _step_name(step) -> str | None:
    if isinstance(step, str):
        return step
    if isinstance(step, dict) and len(step) == 1:
        return next(iter(step))
    return None


def decimal_sep_candidates(rule: dict | None, source_path: str | None, source_value: str | None) -> list[dict]:
    """Podpowiedzi dla niejednoznacznej liczby (EDGE-11): ta sama ścieżka z jawnym separatorem dziesiętnym.

    Istniejące kroki reguły zostają; krok 'decimal' trafia przed pierwszy krok liczbowy (convert/negate)."""
    rule = rule or {}
    path = rule.get("path") or source_path
    if not path:
        return []
    chain = [st for st in (rule.get("transforms") or []) if _step_name(st) != "decimal"]
    pos = next((i for i, st in enumerate(chain) if _step_name(st) in ("convert", "negate")), len(chain))
    out = []
    for sep, label in ((",", "przecinek"), (".", "kropka")):
        transforms = chain[:pos] + [{"decimal": sep}] + chain[pos:]
        out.append({"kind": "path", "path": path, "transforms": transforms,
                    "preview": _preview(source_value, transforms), "confidence": 0.5,
                    "reason": f"separator dziesiętny: {label}"})
    return out


# Rozpoznawanie pola po samym typie wartości (data, liczba, GTIN…) jest drogie — dla bardzo szerokich
# plików ograniczamy je do pierwszych N ścieżek w kolejności dokumentu (SEC-1). Synonimy i wyuczone
# ścieżki działają dla wszystkich ścieżek przez indeks sufiksów.
DETECT_LIMIT = 1000
_INDEX_SEGS = 4


class _Pool:
    """Ścieżka → pierwsza wartość, z indeksami do szybkiego dopasowania synonimów i wyuczonych ścieżek."""

    def __init__(self, items: dict[str, str], scope: str):
        self.items = items
        self.pos = {p: i for i, p in enumerate(items)}
        self.by_suffix: dict[tuple[str, ...], list[str]] = {}
        self.by_key: dict[str, list[str]] = {}
        for p in items:
            segs = p.lower().split("/")
            for n in range(1, min(len(segs), _INDEX_SEGS) + 1):
                self.by_suffix.setdefault(tuple(segs[-n:]), []).append(p)
            self.by_key.setdefault(_tail(p) if scope == "header" else p.lower(), []).append(p)

    def with_suffix(self, syn: str) -> list[str]:
        t = tuple(syn.lower().split("/"))
        if len(t) <= _INDEX_SEGS:
            return self.by_suffix.get(t, [])
        return [p for p in self.items if suffix_match(p, syn)]


def _score(pool: _Pool, f: FieldDef, syns: list[str], learned: dict, scope: str) -> list[Candidate]:
    hits: dict[str, tuple[float, str]] = {}
    for (sc, key), fk in learned.items():
        if sc == scope and fk == f.key:
            for p in pool.by_key.get(key, ()):
                hits[p] = (0.95, "z wcześniejszego szablonu")
    syn_hits: dict[str, tuple[float, str]] = {}
    for idx, syn in enumerate(syns):  # liczy się pierwszy pasujący synonim danej ścieżki
        for p in pool.with_suffix(syn):
            syn_hits.setdefault(p, (max(0.6, 0.9 - 0.02 * idx), f"synonim „{syn}”"))
    for p, (sc, why) in syn_hits.items():
        if sc > hits.get(p, (0.0, ""))[0]:
            hits[p] = (sc, why)
    out: list[tuple[int, Candidate]] = []
    for p, (sc, why) in hits.items():
        value = pool.items[p]
        transforms = _infer_transforms(f, value)
        out.append((pool.pos[p], Candidate(p, transforms, round(sc, 2), why, _preview(value, transforms))))
    for i, (p, value) in enumerate(pool.items.items()):
        if i >= DETECT_LIMIT:
            break
        if p in hits:
            continue
        det = _detect(f, value)
        if det:
            sc, transforms = det
            out.append((i, Candidate(p, transforms, round(sc, 2), "rozpoznany typ wartości",
                                     _preview(value, transforms))))
    out.sort(key=lambda x: x[0])
    return [c for _, c in out]


def _sample(tree: SourceTree) -> dict[str, str]:
    key = ("suggest-sample",)
    if key not in tree.cache:
        sample: dict[str, str] = {}
        for p, v in tree.leaf_items():
            sample.setdefault(p, v)
        tree.cache[key] = sample
    return tree.cache[key]


def _pool(tree: SourceTree, kind: str, line_path: str | None) -> _Pool:
    """Pule ścieżek liczone raz na drzewo: 'lines' (względne w pozycji), 'header', 'inside'."""
    key = ("suggest-pool", kind, line_path)
    if key not in tree.cache:
        sample = _sample(tree)
        if kind == "lines":
            items: dict[str, str] = {}
            for p, v in sample.items():
                rel = relative_path(p, line_path)
                if rel:
                    items.setdefault(rel, v)
        else:
            prefix = (line_path + "/") if line_path else None
            want_inside = kind == "inside"
            items = {p: v for p, v in sample.items() if bool(prefix and p.startswith(prefix)) == want_inside}
        tree.cache[key] = _Pool(items, "lines" if kind == "lines" else "header")
    return tree.cache[key]


def field_candidates(tree: SourceTree, field_key: str, line_path: str | None, synonyms: dict,
                     learned: dict | None = None, limit: int = 5) -> list[Candidate]:
    f = FIELDS_BY_KEY[field_key]
    scope = "lines" if field_key in LINE_KEYS else "header"
    learned = learned or {}
    syns = (synonyms.get(scope) or {}).get(field_key) or []
    if scope == "lines":
        if not line_path:
            return []
        cands = _score(_pool(tree, "lines", line_path), f, syns, learned, scope)
    else:
        cands = _score(_pool(tree, "header", line_path), f, syns, learned, scope)
        if not cands and line_path:
            cands = [Candidate(c.path, c.transforms, round(c.confidence * 0.8, 2),
                               c.reason + " (wartość z pierwszej pozycji)", c.preview)
                     for c in _score(_pool(tree, "inside", line_path), f, syns, learned, scope)]
    cands.sort(key=lambda c: -c.confidence)
    return cands[:limit]


def draft_rules(tree: SourceTree, synonyms: dict, learned: dict | None = None,
                threshold: float = 0.5) -> dict:
    line_path = tree.detect_line_group(synonyms, learned_line_paths(learned))
    rules = {"line_path": line_path, "header": {"doc_type": {"constant": "invoice"}}, "lines": {},
             "defaults": {}, "line_defaults": {}}
    for fields, section in ((HEADER_FIELDS, "header"), (LINE_FIELDS, "lines")):
        used: set[str] = set()
        for f in fields:
            if f.key == "doc_type":
                continue
            for c in field_candidates(tree, f.key, line_path, synonyms, learned):
                if c.confidence < threshold:
                    break
                if c.path in used and f.key not in MULTI_USE:
                    continue
                rules[section][f.key] = {"path": c.path, "transforms": c.transforms}
                used.add(c.path)
                break
    return rules


def unit_candidates(alias: str, unit_codes: list[str], synonyms: dict, limit: int = 5) -> list[dict]:
    a = (alias or "").strip().lower()
    table = {str(k).lower(): v for k, v in (synonyms.get("units") or {}).items()}
    found: dict[str, tuple[float, str]] = {}
    if a in table and table[a] in unit_codes:
        found[table[a]] = (0.95, "znany kod jednostki")
    base = a.rstrip(".")
    for code in unit_codes:
        if code in found or not base:
            continue
        r = fuzz.ratio(base, code) / 100
        if code.startswith(base) or base.startswith(code):
            r = max(r, 0.8)
        if r >= 0.5:
            found[code] = (round(r * 0.85, 2), "podobna nazwa")
    out = [{"kind": "unit", "unit": c, "confidence": s, "reason": why} for c, (s, why) in found.items()]
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


def product_candidates(line: dict, products: list[dict], limit: int = 5) -> list[dict]:
    gtin = (line.get("gtin") or "").zfill(14) if line.get("gtin") else None
    name = line.get("name") or ""
    out = []
    for p in products:
        if gtin and p.get("gtin") and p["gtin"].zfill(14) == gtin:
            out.append({"kind": "product", "code": p["code"], "name": p["name"], "confidence": 1.0,
                        "reason": "zgodny GTIN"})
            continue
        r = fuzz.token_set_ratio(name, p.get("name") or "", processor=default_process)
        if name and r >= 50:
            out.append({"kind": "product", "code": p["code"], "name": p["name"],
                        "confidence": round(r / 100 * 0.9, 2), "reason": "podobna nazwa"})
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


def norm_tax_id(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def split_tax_id(value: str | None) -> tuple[str | None, str]:
    """NIP/VAT → (prefiks kraju albo None, część bez prefiksu); bez spacji, myślników i kropek."""
    s = norm_tax_id(value)
    if len(s) > 2 and s[:2].isalpha():
        return s[:2], s[2:]
    return None, s


def tax_ids_match(a: str | None, b: str | None) -> bool:
    """Prefiks kraju pomijamy tylko, gdy po jednej stronie go brak — FR123 ≠ DE123 (EDGE-8)."""
    (pa, x), (pb, y) = split_tax_id(a), split_tax_id(b)
    if not x or not y or x != y:
        return False
    return pa is None or pb is None or pa == pb


def supplier_candidates(name: str | None, tax_id: str | None, suppliers: list[dict],
                        limit: int = 5) -> list[dict]:
    out = []
    for s in suppliers:
        if tax_id and tax_ids_match(tax_id, s.get("tax_id")):
            out.append({"kind": "use_supplier", "supplier_id": s["id"], "name": s["name"],
                        "confidence": 1.0, "reason": "zgodny NIP/VAT"})
            continue
        if name:
            r = fuzz.token_set_ratio(name, s.get("name") or "", processor=default_process)
            if r >= 70:
                out.append({"kind": "use_supplier", "supplier_id": s["id"], "name": s["name"],
                            "confidence": round(r / 100 * 0.9, 2), "reason": "podobna nazwa"})
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


_QTY_IN_NAME = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|szt)\b", re.IGNORECASE)


def conversion_guess(line_name: str | None, from_unit: str) -> dict:
    guess = {"kind": "conversion", "from_unit": from_unit, "to_unit": "szt", "factor": None, "confidence": 0.3}
    m = None
    for m in _QTY_IN_NAME.finditer(line_name or ""):
        pass
    if m:
        qty = to_decimal(m.group(1))
        unit = m.group(2).lower()
        if unit == "g":
            qty, unit = qty / 1000, "kg"
        elif unit == "ml":
            qty, unit = qty / 1000, "l"
        guess.update(to_unit=unit, factor=format(qty.normalize(), "f"), confidence=0.7)
    return guess
