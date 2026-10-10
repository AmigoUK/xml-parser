import json
from decimal import Decimal

from app.engine.tree import Node, SourceTree
from app.engine.values import PlainNumber

from . import NodeBudget, ReaderError


def _scalar(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        # liczba JSON: zapis jednoznaczny (kropka); wykładnik rozwijamy, gdy wynik jest krótki (EDGE-1)
        if v.is_finite() and -30 <= v.adjusted() <= 30:
            return PlainNumber(format(v, "f"))
        return PlainNumber(v)
    if isinstance(v, PlainNumber):  # liczba całkowita JSON (parse_int)
        return v
    return str(v)


def _build(name: str, value, parent: Node, budget: NodeBudget) -> None:
    if isinstance(value, dict):
        budget.take()
        node = parent.add(Node(name))
        for k, v in value.items():
            if isinstance(v, list):
                for item in v:
                    _build(k, item, node, budget)
            else:
                _build(k, v, node, budget)
    elif isinstance(value, list):
        for item in value:
            _build(name, item, parent, budget)
    else:
        budget.take()
        parent.add(Node(name, _scalar(value)))


def read_json(data: bytes, budget: NodeBudget | None = None) -> SourceTree:
    budget = budget or NodeBudget(10 ** 9)
    try:
        obj = json.loads(data.decode("utf-8-sig"), parse_float=Decimal, parse_int=PlainNumber)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReaderError(f"Niepoprawny JSON: {exc}.") from exc
    except RecursionError:
        raise ReaderError("JSON jest zagnieżdżony zbyt głęboko.") from None
    try:
        return _to_tree(obj, budget)
    except RecursionError:
        raise ReaderError("JSON jest zagnieżdżony zbyt głęboko.") from None


def _to_tree(obj, budget: NodeBudget) -> SourceTree:
    root = Node("root")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                for item in v:
                    _build(k, item, root, budget)
            else:
                _build(k, v, root, budget)
    elif isinstance(obj, list):
        for item in obj:
            _build("item", item, root, budget)
    else:
        raise ReaderError("JSON nie zawiera obiektu ani listy.")
    if not root.children:
        raise ReaderError("JSON jest pusty.")
    return SourceTree(root, "json")
