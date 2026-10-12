from app.engine.tree import SourceTree


class ReaderError(ValueError):
    """Plik nie daje się odczytać — komunikat po polsku dla operatora."""


DEFAULT_MAX_TREE_NODES = 200_000


class NodeBudget:
    """Licznik węzłów drzewa (elementy, atrybuty, komórki) — twardy limit przeciw DoS (SEC-1)."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def take(self, n: int = 1) -> None:
        self.used += n
        if self.used > self.limit:
            raise ReaderError(f"Plik zawiera zbyt wiele elementów (ponad {self.limit:,}) — "
                              "limit chroni serwer przed przeciążeniem. Podziel fakturę na mniejsze pliki."
                              .replace(",", " "))


def _max_tree_nodes() -> int:
    from flask import current_app, has_app_context
    if has_app_context():
        return int(current_app.config.get("MAX_TREE_NODES", DEFAULT_MAX_TREE_NODES))
    return DEFAULT_MAX_TREE_NODES


def detect_format(data: bytes) -> str:
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head == b"<":
        return "xml"
    if head in (b"{", b"["):
        return "json"
    return "csv"


_BINARY_SIGNATURES = (
    b"%PDF", b"PK\x03\x04", b"PK\x05\x06", b"\x89PNG", b"GIF8", b"\xff\xd8\xff", b"\xd0\xcf\x11\xe0",
    b"Rar!", b"\x1f\x8b", b"7z\xbc\xaf", b"\x7fELF",
)
_BINARY_MSG = "Plik binarny (np. PDF) — wgraj XML, JSON lub CSV."
_UTF_MSG = "Kodowanie UTF-16/UTF-32 nie jest obsługiwane — zapisz plik jako UTF-8."


# \t \n \r oraz separatory GS1/EDI (GS 0x1d, RS 0x1e) występują w tekstowych plikach faktur (EDGE-12)
_TEXT_CONTROLS = frozenset((0x09, 0x0a, 0x0d, 0x1d, 0x1e))
# heurystyka pliku binarnego: próbka na bajty zerowe (UTF-16/32 bez BOM: zera na co drugim bajcie), próbka na znaki
# sterujące i progi, powyżej których plik nie jest tekstem
BINARY_SAMPLE_BYTES = 1024
CONTROL_SAMPLE_BYTES = 4096
UTF16_ZERO_RATIO = 0.3
CONTROL_CHAR_RATIO = 0.02


def _check_not_binary(data: bytes) -> None:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ReaderError(_UTF_MSG)
    if data.startswith(_BINARY_SIGNATURES):
        raise ReaderError(_BINARY_MSG)
    sample = data[:BINARY_SAMPLE_BYTES]
    if b"\x00" in sample:
        # tekst UTF-16/32 bez BOM: zera na co drugim (lub co czwartym) bajcie
        even, odd = sample[0::2], sample[1::2]
        if max(even.count(0) / len(even), odd.count(0) / len(odd) if odd else 0) >= UTF16_ZERO_RATIO:
            raise ReaderError(_UTF_MSG)
        raise ReaderError(_BINARY_MSG)
    head = data[:CONTROL_SAMPLE_BYTES]
    ctrl = sum(1 for b in head if b < 0x20 and b not in _TEXT_CONTROLS) + head.count(b"\x7f")
    if ctrl / len(head) > CONTROL_CHAR_RATIO:
        raise ReaderError(_BINARY_MSG)


def read_document(data: bytes, filename: str | None = None, max_nodes: int | None = None) -> SourceTree:
    if not data or not data.strip():
        raise ReaderError("Plik jest pusty.")
    _check_not_binary(data)
    budget = NodeBudget(max_nodes if max_nodes is not None else _max_tree_nodes())
    fmt = detect_format(data)
    if fmt == "xml":
        from .xml_reader import read_xml
        return read_xml(data, budget)
    if fmt == "json":
        from .json_reader import read_json
        return read_json(data, budget)
    from .csv_reader import read_csv
    return read_csv(data, budget)
