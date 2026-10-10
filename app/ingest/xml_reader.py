import io

from lxml import etree

from app.engine.tree import Node, SourceTree

from . import NodeBudget, ReaderError

_PARSER_KW = dict(
    resolve_entities=False, no_network=True, huge_tree=False,
    remove_comments=True, remove_pis=True, load_dtd=False,
)


def _local(tag: str) -> str:
    return etree.QName(tag).localname


def _convert(el) -> Node:
    text = (el.text or "").strip() or None
    attrs = {_local(k): v.strip() for k, v in el.attrib.items()}
    node = Node(_local(el.tag), text, attrs)
    for child in el:
        if isinstance(child.tag, str):
            node.add(_convert(child))
    return node


def _parse(data: bytes, budget: NodeBudget | None):
    if budget is None:
        return etree.fromstring(data, etree.XMLParser(**_PARSER_KW))
    # parsowanie przyrostowe: limit węzłów przerywa wczytywanie, zanim cały plik trafi do pamięci (SEC-1)
    ctx = etree.iterparse(io.BytesIO(data), events=("start",), **_PARSER_KW)
    for _, el in ctx:
        budget.take(1 + len(el.attrib))
    return ctx.root


def read_xml(data: bytes, budget: NodeBudget | None = None) -> SourceTree:
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise ReaderError("Pliki XML z deklaracją DOCTYPE/ENTITY są odrzucane ze względów bezpieczeństwa.")
    try:
        root = _parse(data, budget)
    except etree.XMLSyntaxError as exc:
        raise ReaderError(f"Niepoprawny XML: {exc.msg} (linia {exc.lineno}).") from exc
    info = root.getroottree().docinfo
    if info.doctype or info.internalDTD is not None or info.externalDTD is not None:
        raise ReaderError("Pliki XML z deklaracją DOCTYPE/ENTITY są odrzucane ze względów bezpieczeństwa.")
    try:
        return SourceTree(_convert(root), "xml")
    except RecursionError:
        raise ReaderError("Dokument XML jest zagnieżdżony zbyt głęboko.") from None
