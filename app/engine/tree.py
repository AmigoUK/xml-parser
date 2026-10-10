"""Drzewo źródłowe niezależne od formatu (XML/JSON/CSV) i operacje na ścieżkach."""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator

LINE_HINTS = ("pozycja", "fawiersz", "invoiceline", "row", "item", "items", "line", "lines", "wiersz")


@dataclass(eq=False)
class Node:
    name: str
    text: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = field(default=None, repr=False)

    def add(self, child: "Node") -> "Node":
        child.parent = self
        self.children.append(child)
        return child

    @property
    def path(self) -> str:
        parts, node = [], self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return "/".join(reversed(parts))


def relative_path(path: str, base: str) -> str | None:
    prefix = base + "/"
    return path[len(prefix):] if path.startswith(prefix) else None


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


class SourceTree:
    def __init__(self, root: Node, fmt: str):
        self.root = root
        self.fmt = fmt

    def iter_nodes(self) -> Iterator[Node]:
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def leaf_items(self) -> list[tuple[str, str]]:
        out = []
        for node in self.iter_nodes():
            p = node.path
            if node.text not in (None, ""):
                out.append((p, node.text))
            for k, v in node.attrs.items():
                if v not in (None, ""):
                    out.append((f"{p}/@{k}", v))
        return out

    def leaf_paths(self) -> list[str]:
        seen: dict[str, None] = {}
        for p, _ in self.leaf_items():
            seen.setdefault(p, None)
        return list(seen)

    def path_set(self) -> set[str]:
        return set(self.leaf_paths())

    def group_paths(self) -> list[str]:
        seen: dict[str, None] = {}
        for node in self.iter_nodes():
            if node.children:
                seen.setdefault(node.path, None)
        return list(seen)

    def _descend(self, nodes: list[Node], segments: list[str]) -> list[Node]:
        for seg in segments:
            nodes = [c for n in nodes for c in n.children if c.name == seg]
            if not nodes:
                break
        return nodes

    def nodes_at(self, abs_path: str) -> list[Node]:
        segs = abs_path.split("/")
        if not segs or segs[0] != self.root.name:
            return []
        return self._descend([self.root], segs[1:])

    def values(self, path: str, context: Node | None = None) -> list[str]:
        segs = path.split("/")
        attr = segs.pop()[1:] if segs and segs[-1].startswith("@") else None
        if context is None:
            if not segs or segs[0] != self.root.name:
                return []
            nodes = self._descend([self.root], segs[1:])
        else:
            nodes = self._descend([context], segs)
        if attr is not None:
            return [n.attrs[attr] for n in nodes if n.attrs.get(attr) not in (None, "")]
        return [n.text for n in nodes if n.text not in (None, "")]

    def first(self, path: str, context: Node | None = None) -> str | None:
        vals = self.values(path, context)
        return vals[0] if vals else None

    def detect_line_group(self) -> str | None:
        counts = Counter(n.path for n in self.iter_nodes() if n.children and n is not self.root)
        candidates = [p for p, c in counts.items() if c >= 2]
        outer = [p for p in candidates if not any(p.startswith(o + "/") for o in candidates)]
        if outer:
            return sorted(outer, key=lambda p: (-counts[p], p.count("/")))[0]
        hinted = [p for p in counts if p.rsplit("/", 1)[-1].lower() in LINE_HINTS]
        if hinted:
            return sorted(hinted, key=lambda p: p.count("/"))[0]
        return None

    def fingerprint(self) -> str:
        blob = "\n".join(sorted(self.path_set())).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def display_rows(self) -> list[dict]:
        rows = []

        def walk(node: Node, depth: int) -> None:
            rows.append({"path": node.path, "name": node.name, "value": node.text, "depth": depth})
            for k, v in node.attrs.items():
                rows.append({"path": f"{node.path}/@{k}", "name": f"@{k}", "value": v, "depth": depth + 1})
            for c in node.children:
                walk(c, depth + 1)

        walk(self.root, 0)
        return rows
