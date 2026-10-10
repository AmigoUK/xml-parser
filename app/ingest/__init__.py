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


def read_document(data: bytes, filename: str | None = None) -> SourceTree:
    if not data or not data.strip():
        raise ReaderError("Plik jest pusty.")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in data[:1024]:
        raise ReaderError("Kodowanie UTF-16/UTF-32 nie jest obsługiwane — zapisz plik jako UTF-8.")
    fmt = detect_format(data)
    if fmt == "xml":
        from .xml_reader import read_xml
        return read_xml(data)
    if fmt == "json":
        from .json_reader import read_json
        return read_json(data)
    from .csv_reader import read_csv
    return read_csv(data)
