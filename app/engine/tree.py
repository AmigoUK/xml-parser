"""Drzewo źródłowe niezależne od formatu (XML/JSON/CSV) i operacje na ścieżkach."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

LINE_HINTS = ("pozycja", "fawiersz", "invoiceline", "row", "item", "items", "line", "lines", "wiersz")
# pola, bez których grupa nie jest uznawana za pozycję na podstawie samych synonimów
_DEFINING_LINE_FIELDS = frozenset({"qty", "unit_price_net"})
_INDEX_CACHE: dict[int, tuple[dict, tuple[dict[tuple[str, ...], str], int]]] = {}


def _line_field_index(synonyms: dict | None) -> tuple[dict[tuple[str, ...], str], int]:
    """Mapa: krotka końcowych segmentów ścieżki (małe litery) → klucz pola pozycji."""
    if synonyms is None:
        from .suggest import load_synonyms  # import leniwy: suggest importuje ten moduł
        synonyms = load_synonyms()
    cached = _INDEX_CACHE.get(id(synonyms))
    if cached is not None and cached[0] is synonyms:
        return cached[1]
    index: dict[tuple[str, ...], str] = {}
    for key, syns in ((synonyms.get("lines") or {}).items()):
        for syn in syns or []:
            index.setdefault(tuple(str(syn).lower().split("/")), key)
    result = (index, max((len(k) for k in index), default=1))
    _INDEX_CACHE[id(synonyms)] = (synonyms, result)
    return result


def _hinted(path: str) -> bool:
    return path.rsplit("/", 1)[-1].lower() in LINE_HINTS


def _has_ancestor_in(path: str, group: set[str]) -> bool:
    """Czy któryś właściwy przodek ścieżki należy do zbioru — O(głębokość), nie O(|zbiór|)."""
    end = path.rfind("/")
    while end > 0:
        if path[:end] in group:
            return True
        end = path.rfind("/", 0, end)
    return False


@dataclass(eq=False)
class Node:
    """Węzeł drzewa źródłowego: nazwa, tekst, atrybuty, dzieci i rodzic (ścieżka liczona z łańcucha rodziców)."""
    name: str
    text: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for child in self.children:
            child.parent = self

    def add(self, child: Node) -> Node:
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
    """Ścieżka względna wobec `base` (gdy `path` leży pod `base`) albo None."""
    prefix = base + "/"
    return path[len(prefix):] if path.startswith(prefix) else None


def jaccard(a: set, b: set) -> float:
    """Podobieństwo Jaccarda dwóch zbiorów ścieżek (0–1; dwa puste zbiory → 0)."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


class SourceTree:
    """Drzewo pliku (XML/JSON/CSV) z operacjami na ścieżkach: wartości, liście, grupy, wykrywanie pozycji,
    odcisk struktury."""
    def __init__(self, root: Node, fmt: str):
        self.root = root
        self.fmt = fmt
        self._leaf_items: list[tuple[str, str]] | None = None
        self.cache: dict = {}  # wyniki pochodne liczone raz na drzewo (drzewo po odczycie jest niezmienne)

    def iter_nodes(self) -> Iterator[Node]:
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def iter_with_paths(self) -> Iterator[tuple[Node, str]]:
        """Przejście w głąb z wyliczaną przyrostowo ścieżką (Node.path kosztuje O(głębokość))."""
        stack = [(self.root, self.root.name)]
        while stack:
            node, path = stack.pop()
            yield node, path
            for child in reversed(node.children):
                stack.append((child, f"{path}/{child.name}"))

    def leaf_items(self) -> list[tuple[str, str]]:
        # drzewo po odczycie jest niezmienne — liczymy raz (wołane wielokrotnie przez podpowiedzi)
        if self._leaf_items is None:
            out = []
            for node, p in self.iter_with_paths():
                if node.text not in (None, ""):
                    out.append((p, node.text))
                for k, v in node.attrs.items():
                    if v not in (None, ""):
                        out.append((f"{p}/@{k}", v))
            self._leaf_items = out
        return list(self._leaf_items)

    def leaf_paths(self) -> list[str]:
        seen: dict[str, None] = {}
        for p, _ in self.leaf_items():
            seen.setdefault(p, None)
        return list(seen)

    def path_set(self) -> set[str]:
        return set(self.leaf_paths())

    def group_paths(self) -> list[str]:
        seen: dict[str, None] = {}
        for node, path in self.iter_with_paths():
            if node.children:
                seen.setdefault(path, None)
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

    def detect_line_group(self, synonyms: dict | None = None,
                          learned_paths: Iterable[str] | None = None) -> str | None:
        """Wskazuje element powtarzający się jako pozycja faktury. Jedno przejście drzewa (SEC-1).

        Kolejność: ścieżka pozycji z wyuczonych szablonów → grupa zawierająca typowe pola pozycji
        (ilość/cena + co najmniej jedno inne, wg synonimów) → najliczniejsza zewnętrzna grupa
        powtarzalna → nazwa z LINE_HINTS (EDGE-4)."""
        index, max_len = _line_field_index(synonyms)
        counts: dict[str, int] = {}
        fields: dict[str, set[str]] = {}

        def credit(leaf_path: str) -> None:
            segs = leaf_path.rsplit("/", max_len)
            low = [x.lower() for x in segs]
            for n in range(1, min(max_len, len(segs) - 1) + 1):
                key = index.get(tuple(low[-n:]))
                if key:
                    group = leaf_path[: -(len("/".join(segs[-n:])) + 1)]
                    fields.setdefault(group, set()).add(key)

        for node, path in self.iter_with_paths():
            if node.children and node is not self.root:
                counts[path] = counts.get(path, 0) + 1
            if node.text not in (None, "") and node is not self.root:
                credit(path)
            for k, v in node.attrs.items():
                if v not in (None, ""):
                    credit(f"{path}/@{k}")

        def depth(p: str) -> int:
            return p.count("/")

        def score(p: str) -> int:
            return len(fields.get(p, ()))

        learned = [p for p in (learned_paths or ()) if p in counts]
        if learned:
            return sorted(learned, key=lambda p: (-score(p), -counts[p], depth(p), p))[0]

        strong = {p for p, f in fields.items() if p in counts and len(f) >= 2 and f & _DEFINING_LINE_FIELDS}
        strong = [p for p in strong if not _has_ancestor_in(p, strong)]
        if strong:
            return sorted(strong, key=lambda p: (counts[p] < 2, -score(p), not _hinted(p),
                                                 -counts[p], depth(p), p))[0]

        repeated = {p for p, c in counts.items() if c >= 2}
        outer = [p for p in repeated if not _has_ancestor_in(p, repeated)]
        if outer:
            return sorted(outer, key=lambda p: (-counts[p], depth(p), p))[0]
        hinted = [p for p in counts if _hinted(p)]
        if hinted:
            return sorted(hinted, key=lambda p: (depth(p), p))[0]
        return None

    def fingerprint(self) -> str:
        blob = "\n".join(sorted(self.path_set())).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def display_rows(self, limit: int | None = None) -> list[dict]:
        """Wiersze podglądu drzewa w kolejności dokumentu; `limit` przerywa budowę po N wierszach."""
        rows: list[dict] = []
        stack = [(self.root, self.root.name, 0)]
        while stack and (limit is None or len(rows) < limit):
            node, path, depth = stack.pop()
            rows.append({"path": path, "name": node.name, "value": node.text, "depth": depth})
            for k, v in node.attrs.items():
                rows.append({"path": f"{path}/@{k}", "name": f"@{k}", "value": v, "depth": depth + 1})
            for c in reversed(node.children):
                stack.append((c, f"{path}/{c.name}", depth + 1))
        return rows if limit is None else rows[:limit]
