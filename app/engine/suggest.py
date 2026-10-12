"""Podpowiedzi mapowań — wyłącznie heurystyki (bez LLM): synonimy ścieżek, wyuczone szablony, rozpoznawanie typu
wartości, dopasowanie rozmyte nazw towarów i dostawców, zgadywanie przelicznika z nazwy pozycji."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process
from rapidfuzz.utils import default_process

from .canonical import DATE, DECIMAL, GTIN, HEADER_FIELDS, LINE_FIELDS, LINE_KEYS, MONEY, PRICE, FieldDef
from .gs1 import GS1Error, is_valid_gtin, parse_gs1
from .transforms import TransformError, apply_chain
from .tree import SourceTree, relative_path
from .values import parse_date, to_decimal

DEFAULT_SYNONYMS = Path(__file__).resolve().parents[2] / "data" / "synonyms.yaml"
FIELDS_BY_KEY = {f.key: f for f in HEADER_FIELDS + LINE_FIELDS}
MULTI_USE = {"batch", "expiry_date"}

# Pewność podpowiedzi (0–1): skąd pochodzi dopasowanie ścieżki do pola
CONF_LEARNED = 0.95        # ścieżka z wcześniejszego szablonu
CONF_SYNONYM_TOP = 0.9     # pierwszy synonim na liście; każdy kolejny o CONF_SYNONYM_STEP mniej, nie mniej niż MIN
CONF_SYNONYM_STEP = 0.02
CONF_SYNONYM_MIN = 0.6
CONF_GS1 = 0.7             # partia / data ważności z AI kodu GS1-128
CONF_GTIN = 0.6            # poprawny GTIN (cyfra kontrolna)
CONF_DATE = 0.4            # wartość parsuje się jako data
CONF_TAX_ID = 0.4          # wartość wygląda jak NIP/VAT
CONF_NUMBER = 0.3          # wartość parsuje się jako liczba
CONF_INSIDE_FACTOR = 0.8   # pole nagłówka znalezione w pierwszej pozycji
CONF_DECIMAL_SEP = 0.5     # ta sama ścieżka z jawnym separatorem dziesiętnym
CONF_KNOWN_UNIT = 0.95     # alias jednostki ze słownika synonimów
CONF_UNIT_FUZZY = 0.85     # waga podobieństwa kodu jednostki
UNIT_PREFIX_SCORE = 0.8    # alias jest prefiksem kodu jednostki (lub odwrotnie)
UNIT_FUZZ_MIN = 0.5
CONF_CONVERSION_FROM_NAME = 0.7  # przelicznik odczytany z nazwy towaru („25 kg”)
CONF_CONVERSION_UNKNOWN = 0.3
# długości: GTIN-14 z prefiksem AI „01” oraz minimalna długość kodu GS1-128 z co najmniej dwoma AI
AI01_GTIN_LEN = 16
GS1_MIN_LEN = 18
_CACHE: dict[Path, dict] = {}


def load_synonyms(path: Path | None = None) -> dict:
    """Słownik synonimów ścieżek (data/synonyms.yaml) z pamięcią podręczną per plik."""
    p = Path(path or DEFAULT_SYNONYMS)
    if p not in _CACHE:
        with p.open(encoding="utf-8") as fh:
            _CACHE[p] = yaml.safe_load(fh) or {}
    return _CACHE[p]


@dataclass
class Candidate:
    """Podpowiedź ścieżki dla pola: ścieżka, transformacje, pewność, powód i podgląd wartości po transformacjach."""
    path: str
    transforms: list = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    preview: str | None = None

    def to_dict(self) -> dict:
        return {"kind": "path", **asdict(self)}


def suffix_match(path: str, synonym: str) -> bool:
    """Czy końcowe segmenty ścieżki odpowiadają synonimowi (porównanie bez wielkości liter)."""
    segs = path.lower().split("/")
    s = synonym.lower().split("/")
    return len(s) <= len(segs) and segs[-len(s):] == s


def _tail(path: str, n: int = 2) -> str:
    return "/".join(path.lower().split("/")[-n:])


def learned_pairs(rule_sets: Iterable[dict]) -> dict[tuple[str, str], str]:
    """Mapa (sekcja, ścieżka) → klucz pola z aktywnych reguł szablonów — wyuczone dopasowania."""
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
    """Ścieżki elementów z pozycjami znane z wcześniejszych szablonów."""
    return {k[1] for k in (learned or {}) if k[0] == "line_path"}


def _gs1_ais(value: str) -> dict[str, str]:
    if len(value) < GS1_MIN_LEN or not value.startswith("01"):
        return {}
    try:
        parsed = parse_gs1(value)
    except GS1Error:
        return {}
    return parsed if len(parsed) >= 2 else {}


def _detect(f: FieldDef, value: str) -> tuple[float, list] | None:
    v = value.strip()
    if f.kind == GTIN:
        if len(v) == AI01_GTIN_LEN and v.startswith("01") and is_valid_gtin(v[2:]):
            return CONF_GTIN, ["strip_ai_prefix"]
        if len(v) >= 12 and is_valid_gtin(v):
            return CONF_GTIN, []
    if f.key == "batch":
        if "10" in _gs1_ais(v):
            return CONF_GS1, [{"gs1": "10"}]
    if f.key == "expiry_date":
        ais = _gs1_ais(v)
        for ai in ("17", "15"):
            if ai in ais:
                return CONF_GS1, [{"gs1": ai}]
    if f.kind == DATE:
        try:
            parse_date(v)
            return CONF_DATE, []
        except ValueError:
            pass
    if f.key.endswith("tax_id") and re.fullmatch(r"[A-Z]{0,2}\d{8,12}", re.sub(r"[\s-]", "", v.upper())):
        return CONF_TAX_ID, []
    if f.kind in (MONEY, PRICE, DECIMAL):
        try:
            to_decimal(v)
            if re.fullmatch(r"[\d\s.,\-+%£€$]+", v):
                return CONF_NUMBER, []
        except ValueError:
            pass
    return None


def _infer_transforms(f: FieldDef, value: str) -> list:
    v = (value or "").strip()
    if f.kind == GTIN and len(v) == AI01_GTIN_LEN and v.startswith("01") and is_valid_gtin(v[2:]):
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
                    "preview": _preview(source_value, transforms), "confidence": CONF_DECIMAL_SEP,
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
                hits[p] = (CONF_LEARNED, "z wcześniejszego szablonu")
    syn_hits: dict[str, tuple[float, str]] = {}
    for idx, syn in enumerate(syns):  # liczy się pierwszy pasujący synonim danej ścieżki
        for p in pool.with_suffix(syn):
            syn_hits.setdefault(p, (max(CONF_SYNONYM_MIN, CONF_SYNONYM_TOP - CONF_SYNONYM_STEP * idx),
                                    f"synonim „{syn}”"))
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
    """Kandydaci ścieżek dla pola: wyuczone, synonimy, rozpoznany typ wartości — po pewności malejąco, do `limit`."""
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
            cands = [Candidate(c.path, c.transforms, round(c.confidence * CONF_INSIDE_FACTOR, 2),
                               c.reason + " (wartość z pierwszej pozycji)", c.preview)
                     for c in _score(_pool(tree, "inside", line_path), f, syns, learned, scope)]
    cands.sort(key=lambda c: -c.confidence)
    return cands[:limit]


def draft_rules(tree: SourceTree, synonyms: dict, learned: dict | None = None,
                threshold: float = 0.5) -> dict:
    """Reguły robocze dla nowego pliku: element z pozycjami i pola o pewności ≥ `threshold` (każda ścieżka raz)."""
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
    """Podpowiedzi naszej jednostki dla aliasu z pliku: słownik synonimów, potem podobieństwo kodów."""
    a = (alias or "").strip().lower()
    table = {str(k).lower(): v for k, v in (synonyms.get("units") or {}).items()}
    found: dict[str, tuple[float, str]] = {}
    if a in table and table[a] in unit_codes:
        found[table[a]] = (CONF_KNOWN_UNIT, "znany kod jednostki")
    base = a.rstrip(".")
    for code in unit_codes:
        if code in found or not base:
            continue
        r = fuzz.ratio(base, code) / 100
        if code.startswith(base) or base.startswith(code):
            r = max(r, UNIT_PREFIX_SCORE)
        if r >= UNIT_FUZZ_MIN:
            found[code] = (round(r * CONF_UNIT_FUZZY, 2), "podobna nazwa")
    out = [{"kind": "unit", "unit": c, "confidence": s, "reason": why} for c, (s, why) in found.items()]
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


# próg podobieństwa nazwy (rapidfuzz token_set_ratio, 0–100) i waga pewności podpowiedzi „podobna nazwa”
FUZZ_MIN_PRODUCT = 50
FUZZ_MIN_SUPPLIER = 70
FUZZY_WEIGHT = 0.9


class ProductIndex:
    """Kartoteka przygotowana do podpowiedzi towarów: lista nazw dla porównania rozmytego (rapidfuzz liczy całą
    listę w C, bez pętli w Pythonie) i mapa GTIN → towary. Budowany raz na dokument, nie na każdą pozycję."""

    def __init__(self, products: list[dict]):
        self.products = list(products)
        self.names = [p.get("name") or "" for p in self.products]
        self.by_gtin: dict[str, list[dict]] = {}
        for p in self.products:
            if p.get("gtin"):
                self.by_gtin.setdefault(p["gtin"].zfill(14), []).append(p)


def product_candidates(line: dict, products: list[dict], limit: int = 5, index: ProductIndex | None = None,
                       fuzzy: bool = True) -> list[dict]:
    """Podpowiedzi towaru dla pozycji: zgodny GTIN (pewność 1.0), potem podobne nazwy (`fuzzy`; wynik/100 × 0.9,
    od progu FUZZ_MIN_PRODUCT). `index` pozwala policzyć indeks kartoteki raz dla wielu pozycji."""
    index = index if index is not None else ProductIndex(products)
    gtin = (line.get("gtin") or "").zfill(14) if line.get("gtin") else None
    name = line.get("name") or ""
    out, matched = [], set()
    for p in index.by_gtin.get(gtin, []) if gtin else []:
        out.append({"kind": "product", "code": p["code"], "name": p["name"], "confidence": 1.0,
                    "reason": "zgodny GTIN"})
        matched.add(id(p))
    if fuzzy and name:
        hits = process.extract(name, index.names, scorer=fuzz.token_set_ratio, processor=default_process,
                               score_cutoff=FUZZ_MIN_PRODUCT, limit=limit + len(matched))
        for _, score, idx in hits:
            p = index.products[idx]
            if id(p) in matched:
                continue
            out.append({"kind": "product", "code": p["code"], "name": p["name"],
                        "confidence": round(score / 100 * FUZZY_WEIGHT, 2), "reason": "podobna nazwa"})
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


def norm_tax_id(value: str | None) -> str:
    """NIP/VAT w postaci porównywalnej: wielkie litery, tylko litery i cyfry (bez spacji, myślników, kropek)."""
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
    """Podpowiedzi istniejącego dostawcy: zgodny NIP/VAT (pewność 1.0), potem podobna nazwa."""
    out = []
    for s in suppliers:
        if tax_id and tax_ids_match(tax_id, s.get("tax_id")):
            out.append({"kind": "use_supplier", "supplier_id": s["id"], "name": s["name"],
                        "confidence": 1.0, "reason": "zgodny NIP/VAT"})
            continue
        if name:
            r = fuzz.token_set_ratio(name, s.get("name") or "", processor=default_process)
            if r >= FUZZ_MIN_SUPPLIER:
                out.append({"kind": "use_supplier", "supplier_id": s["id"], "name": s["name"],
                            "confidence": round(r / 100 * FUZZY_WEIGHT, 2), "reason": "podobna nazwa"})
    return sorted(out, key=lambda d: -d["confidence"])[:limit]


_QTY_IN_NAME = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|szt)\b", re.IGNORECASE)


def conversion_guess(line_name: str | None, from_unit: str) -> dict:
    """Zgaduje przelicznik z nazwy pozycji („25 kg” → 25 kg na jednostkę bazową); bez trafienia współczynnik None."""
    guess = {"kind": "conversion", "from_unit": from_unit, "to_unit": "szt", "factor": None,
             "confidence": CONF_CONVERSION_UNKNOWN}
    m = None
    for m in _QTY_IN_NAME.finditer(line_name or ""):  # noqa: B007 — liczy się ostatnie dopasowanie
        pass
    if m:
        try:
            qty = to_decimal(m.group(1))
        except ValueError:  # liczba poza zakresem / za długa w nazwie towaru — podpowiedź bez współczynnika
            return guess
        unit = m.group(2).lower()
        if unit == "g":
            qty, unit = qty / 1000, "kg"
        elif unit == "ml":
            qty, unit = qty / 1000, "l"
        guess.update(to_unit=unit, factor=format(qty.normalize(), "f"), confidence=CONF_CONVERSION_FROM_NAME)
    return guess
