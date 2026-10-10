from app.engine.tree import SourceTree


class ReaderError(ValueError):
    """Plik nie daje się odczytać — komunikat po polsku dla operatora."""


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


def _check_not_binary(data: bytes) -> None:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ReaderError(_UTF_MSG)
    if data.startswith(_BINARY_SIGNATURES):
        raise ReaderError(_BINARY_MSG)
    sample = data[:1024]
    if b"\x00" in sample:
        # tekst UTF-16/32 bez BOM: zera na co drugim (lub co czwartym) bajcie
        even, odd = sample[0::2], sample[1::2]
        if max(even.count(0) / len(even), odd.count(0) / len(odd) if odd else 0) >= 0.3:
            raise ReaderError(_UTF_MSG)
        raise ReaderError(_BINARY_MSG)
    head = data[:4096]
    ctrl = sum(1 for b in head if b < 0x20 and b not in (9, 10, 13)) + head.count(b"\x7f")
    if ctrl / len(head) > 0.02:
        raise ReaderError(_BINARY_MSG)


def read_document(data: bytes, filename: str | None = None) -> SourceTree:
    if not data or not data.strip():
        raise ReaderError("Plik jest pusty.")
    _check_not_binary(data)
    fmt = detect_format(data)
    if fmt == "xml":
        from .xml_reader import read_xml
        return read_xml(data)
    if fmt == "json":
        from .json_reader import read_json
        return read_json(data)
    from .csv_reader import read_csv
    return read_csv(data)
