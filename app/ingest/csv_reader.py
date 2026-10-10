import csv
import io

from app.engine.tree import Node, SourceTree

from . import ReaderError


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1250", errors="replace")


def read_csv(data: bytes) -> SourceTree:
    text = _decode(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise ReaderError("Plik CSV jest pusty.") from None
    names = [(h.strip().replace("/", "_") or f"kol{i + 1}") for i, h in enumerate(header)]
    root = Node("csv")
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        rnode = root.add(Node("row"))
        for name, cell in zip(names, row):
            rnode.add(Node(name, cell.strip() or None))
    if not root.children:
        raise ReaderError("Plik CSV nie zawiera żadnych wierszy danych.")
    return SourceTree(root, "csv")
