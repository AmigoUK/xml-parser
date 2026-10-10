import json

from app.engine.tree import Node, SourceTree

from . import ReaderError


def _scalar(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _build(name: str, value, parent: Node) -> None:
    if isinstance(value, dict):
        node = parent.add(Node(name))
        for k, v in value.items():
            if isinstance(v, list):
                for item in v:
                    _build(k, item, node)
            else:
                _build(k, v, node)
    elif isinstance(value, list):
        for item in value:
            _build(name, item, parent)
    else:
        parent.add(Node(name, _scalar(value)))


def read_json(data: bytes) -> SourceTree:
    try:
        obj = json.loads(data.decode("utf-8-sig"), parse_float=str, parse_int=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReaderError(f"Niepoprawny JSON: {exc}.") from exc
    root = Node("root")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                for item in v:
                    _build(k, item, root)
            else:
                _build(k, v, root)
    elif isinstance(obj, list):
        for item in obj:
            _build("item", item, root)
    else:
        raise ReaderError("JSON nie zawiera obiektu ani listy.")
    if not root.children:
        raise ReaderError("JSON jest pusty.")
    return SourceTree(root, "json")
