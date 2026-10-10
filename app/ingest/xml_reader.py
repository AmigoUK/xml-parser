from lxml import etree

from app.engine.tree import Node, SourceTree

from . import ReaderError

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


def read_xml(data: bytes) -> SourceTree:
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise ReaderError("Pliki XML z deklaracją DOCTYPE/ENTITY są odrzucane ze względów bezpieczeństwa.")
    try:
        root = etree.fromstring(data, etree.XMLParser(**_PARSER_KW))
    except etree.XMLSyntaxError as exc:
        raise ReaderError(f"Niepoprawny XML: {exc.msg} (linia {exc.lineno}).") from exc
    return SourceTree(_convert(root), "xml")
