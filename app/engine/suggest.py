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
    return out


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


def _score(pool: dict[str, str], f: FieldDef, syns: list[str], learned: dict, scope: str) -> list[Candidate]:
    out = []
    for path, value in pool.items():
        score, reason, transforms = 0.0, "", []
        key = _tail(path) if scope == "header" else path.lower()
        if learned.get((scope, key)) == f.key:
            score, reason = 0.95, "z wcześniejszego szablonu"
        for idx, syn in enumerate(syns):
            if suffix_match(path, syn):
                s = max(0.6, 0.9 - 0.02 * idx)
                if s > score:
                    score, reason = s, f"synonim „{syn}”"
                break
        if score:
            transforms = _infer_transforms(f, value)
        else:
            det = _detect(f, value)
            if det:
                score, transforms = det
                reason = "rozpoznany typ wartości"
        if score:
            out.append(Candidate(path, transforms, round(score, 2), reason, _preview(value, transforms)))
    return out


def field_candidates(tree: SourceTree, field_key: str, line_path: str | None, synonyms: dict,
                     learned: dict | None = None, limit: int = 5) -> list[Candidate]:
    f = FIELDS_BY_KEY[field_key]
    scope = "lines" if field_key in LINE_KEYS else "header"
    learned = learned or {}
    syns = (synonyms.get(scope) or {}).get(field_key) or []
    sample: dict[str, str] = {}
    for p, v in tree.leaf_items():
        sample.setdefault(p, v)
    if scope == "lines":
        if not line_path:
            return []
        pool: dict[str, str] = {}
        for p, v in sample.items():
            rel = relative_path(p, line_path)
            if rel:
                pool.setdefault(rel, v)
        cands = _score(pool, f, syns, learned, scope)
    else:
        inside = lambda p: bool(line_path) and p.startswith(line_path + "/")  # noqa: E731
        cands = _score({p: v for p, v in sample.items() if not inside(p)}, f, syns, learned, scope)
        if not cands and line_path:
            cands = [Candidate(c.path, c.transforms, round(c.confidence * 0.8, 2),
                               c.reason + " (wartość z pierwszej pozycji)", c.preview)
                     for c in _score({p: v for p, v in sample.items() if inside(p)}, f, syns, learned, scope)]
    cands.sort(key=lambda c: -c.confidence)
    return cands[:limit]


def draft_rules(tree: SourceTree, synonyms: dict, learned: dict | None = None,
                threshold: float = 0.5) -> dict:
    line_path = tree.detect_line_group()
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


def tax_ids_match(a: str | None, b: str | None) -> bool:
    x, y = norm_tax_id(a), norm_tax_id(b)
    if not x or not y:
        return False
    strip = lambda s: s[2:] if len(s) > 2 and s[:2].isalpha() else s  # noqa: E731
    return x == y or strip(x) == strip(y)


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
