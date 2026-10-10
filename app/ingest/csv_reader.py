import csv
import io

from app.engine.tree import Node, SourceTree

from . import NodeBudget, ReaderError


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1250", errors="replace")


def read_csv(data: bytes, budget: NodeBudget | None = None) -> SourceTree:
    budget = budget or NodeBudget(10 ** 9)
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
    except csv.Error as exc:
        raise ReaderError(f"Niepoprawny CSV: {exc}.") from exc
    names = [(h.strip().replace("/", "_") or f"kol{i + 1}") for i, h in enumerate(header)]
    root = Node("csv")
    try:
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            budget.take(1 + min(len(names), len(row)))
            rnode = root.add(Node("row"))
            for name, cell in zip(names, row):
                rnode.add(Node(name, cell.strip() or None))
    except csv.Error as exc:
        raise ReaderError(f"Niepoprawny CSV: {exc}.") from exc
    if not root.children:
        raise ReaderError("Plik CSV nie zawiera żadnych wierszy danych.")
    return SourceTree(root, "csv")
