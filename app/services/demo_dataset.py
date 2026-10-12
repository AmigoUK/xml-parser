"""Zestaw demo „Miesiąc faktur”: manifest, postęp wczytywania liczony z bazy i wczytywanie faz przez ingest().

Serwis nie zna żądania Flaska — tylko pliki z `demo/dataset/` i bazę. Manifest jest jedynym źródłem prawdy
o składzie zestawu (generuje go `tools/gen_demo_dataset.py`, do obrazu Docker trafia `demo/`).

Każdy dokument commituje się osobno (ingest), więc przerwane wczytywanie można bezpiecznie powtórzyć — już
wczytane wpisy zostaną pominięte (idempotencja)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.models import STATUS_LABELS, Document
from app.services.pipeline import DocumentTooLarge, StorageUnavailable, ingest

DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "demo" / "dataset"
MANIFEST_NAME = "manifest.json"

PHASES: dict[str, tuple[str, ...]] = {
    "pierwsze": ("first",),
    "pozostale": ("rest",),
    "wszystko": ("first", "rest"),
}


VALID_PHASES = ("first", "rest")
VALID_FORMATS = ("xml", "json", "csv")


class DatasetError(ValueError):
    """Pliki zestawu nie zgadzają się z manifestem (brak pliku, zły sha256) — nic nie zostało wczytane."""


@dataclass(frozen=True)
class Expected:
    status: str
    blocking: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Entry:
    order: int
    filename: str
    sha256: str
    supplier: str
    format: str
    phase: str
    shows: str
    on_ingest: Expected
    after_resolve: Expected | None = None
    duplicate_of: str | None = None


@dataclass(frozen=True)
class Manifest:
    title: str
    generator: dict = field(default_factory=dict)
    suppliers: dict = field(default_factory=dict)
    entries: tuple[Entry, ...] = ()

    def by_phase(self, phase_key: str) -> list[Entry]:
        """Wpisy danej fazy (klucz z PHASES, np. „pierwsze”) w kolejności `order`."""
        phases = PHASES[phase_key]
        return [e for e in self.entries if e.phase in phases]


@dataclass(frozen=True)
class ProgressRow:
    entry: Entry
    doc_id: int | None
    status: str | None
    status_label: str | None
    source: str | None
    matches_expected: bool | None


@dataclass
class BatchResult:
    loaded: list[Document] = field(default_factory=list)
    skipped: list[Entry] = field(default_factory=list)


class DatasetLoadError(RuntimeError):
    """Wczytywanie przerwane w trakcie (magazyn/rozmiar); `partial` = co już zacommitowano + reszta jako `skipped`."""

    def __init__(self, message: str, partial: BatchResult):
        super().__init__(message)
        self.partial = partial


def _expected(raw: dict | None) -> Expected | None:
    if raw is None:
        return None
    return Expected(status=raw["status"], blocking=tuple(raw.get("blocking") or ()),
                    warnings=tuple(raw.get("warnings") or ()))


def _checked(e: Entry) -> Entry:
    if e.on_ingest is None:
        raise ValueError(f"{e.filename}: brak „expected.on_ingest”")
    if e.phase not in VALID_PHASES:
        raise ValueError(f"{e.filename}: nieznana faza „{e.phase}”")
    if e.format not in VALID_FORMATS:
        raise ValueError(f"{e.filename}: nieznany format „{e.format}”")
    return e


def load_manifest(path: Path | str | None = None) -> Manifest:
    """Czyta manifest zestawu; brak pliku lub zły kształt → FileNotFoundError / ValueError z polskim komunikatem."""
    p = Path(path) if path is not None else DATASET_DIR / MANIFEST_NAME
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Brak manifestu zestawu demo: {p}") from exc
    except (OSError, ValueError) as exc:
        raise ValueError(f"Nie można odczytać manifestu zestawu demo ({p}): {exc}") from exc
    try:
        entries = tuple(sorted((
            _checked(Entry(order=int(f["order"]), filename=f["filename"], sha256=f["sha256"], supplier=f["supplier"],
                  format=f["format"], phase=f["phase"], shows=f.get("shows", ""),
                  on_ingest=_expected(f["expected"]["on_ingest"]),
                  after_resolve=_expected(f["expected"].get("after_resolve")),
                  duplicate_of=f.get("duplicate_of")))
            for f in raw["files"]), key=lambda e: e.order))
        if len({e.order for e in entries}) != len(entries):
            raise ValueError("powtórzone pole „order”")
        return Manifest(title=raw["title"], generator=raw.get("generator") or {},
                        suppliers=raw.get("suppliers") or {}, entries=entries)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Manifest zestawu demo ma nieprawidłową strukturę ({p}): {exc!r}") from exc


def is_available() -> bool:
    """Czy zestaw jest w obrazie/katalogu i da się go odczytać (błędy manifestu → False)."""
    try:
        load_manifest()
    except (FileNotFoundError, ValueError):
        return False
    return True


def _matches(entry: Entry, status: str | None) -> bool | None:
    if status is None:
        return None
    allowed = {entry.on_ingest.status}
    if entry.after_resolve is not None:
        allowed.add(entry.after_resolve.status)
    return status in allowed


def progress(manifest: Manifest | None = None) -> list[ProgressRow]:
    """Wiersz na wpis manifestu. Dokument dopasowany po (filename, sha256) niezależnie od `source`;
    przy kilku — najnowszy `id`. Jedno zapytanie po zbiorze nazw plików."""
    m = manifest or load_manifest()
    names = {e.filename for e in m.entries}
    newest: dict[tuple[str, str], Document] = {}
    if names:
        for doc in Document.query.filter(Document.filename.in_(names)).order_by(Document.id):
            newest[(doc.filename, doc.sha256)] = doc
    rows = []
    for e in m.entries:
        doc = newest.get((e.filename, e.sha256))
        status = doc.status if doc else None
        rows.append(ProgressRow(entry=e, doc_id=doc.id if doc else None, status=status,
                                status_label=STATUS_LABELS.get(status, status) if doc else None,
                                source=doc.source if doc else None, matches_expected=_matches(e, status)))
    return rows


def pending(phase_key: str) -> list[Entry]:
    """Wpisy fazy, które nie zostały jeszcze wczytane (nieznany klucz → KeyError)."""
    m = load_manifest()
    entries = m.by_phase(phase_key)
    done = {r.entry.filename for r in progress(m) if r.doc_id is not None}
    return [e for e in entries if e.filename not in done]


def load_entries(entries: list[Entry], source: str = "demo") -> BatchResult:
    """Wczytuje wpisy przez ingest() w kolejności `order`; już wczytane pomija. Błędy magazynu/rozmiaru lecą wyżej."""
    result = BatchResult()
    m = load_manifest()
    done = {r.entry.filename for r in progress(m) if r.doc_id is not None}
    todo = []
    for e in sorted(entries, key=lambda x: x.order):
        if e.filename in done:
            result.skipped.append(e)
        else:
            todo.append((e, _read_verified(e)))  # walidacja wszystkich plików PRZED pierwszym ingestem
    for i, (e, data) in enumerate(todo):
        try:
            result.loaded.append(ingest(data, e.filename, source=source))
        except (StorageUnavailable, DocumentTooLarge) as exc:
            result.skipped.extend(x for x, _ in todo[i:])
            raise DatasetLoadError(
                f"Wczytywanie przerwane na pliku {e.filename} (wczytano {len(result.loaded)}): {exc}", result) from exc
    return result


def _read_verified(e: Entry) -> bytes:
    path = DATASET_DIR / Path(e.filename).name
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DatasetError(f"Brak pliku zestawu demo: {e.filename}") from exc
    if hashlib.sha256(data).hexdigest() != e.sha256:
        raise DatasetError(f"Plik zestawu demo {e.filename} jest niezgodny z manifestem (sha256) — nic nie wczytano.")
    return data


def load_phase(phase_key: str, source: str = "demo") -> BatchResult:
    """Wczytuje fazę z PHASES (nieznany klucz → KeyError); ponowne wywołanie niczego nie dubluje."""
    if phase_key not in PHASES:
        raise KeyError(phase_key)
    return load_entries(load_manifest().by_phase(phase_key), source=source)


def counts() -> dict[str, tuple[int, int]]:
    """Dla każdej fazy: (liczba niewczytanych, liczba wszystkich)."""
    m = load_manifest()
    done = {r.entry.filename for r in progress(m) if r.doc_id is not None}
    return {k: (sum(e.filename not in done for e in m.by_phase(k)), len(m.by_phase(k))) for k in PHASES}
