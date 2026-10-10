from app.engine.tree import Node, SourceTree, jaccard, relative_path


def build():
    root = Node("Doc")
    head = root.add(Node("Head"))
    head.add(Node("Nr", "F/1"))
    lines = root.add(Node("Lines"))
    for i in range(3):
        ln = lines.add(Node("Line"))
        ln.add(Node("Name", f"Towar {i}"))
        ln.add(Node("Qty", str(i + 1), attrs={"unit": "pcs"}))
    return SourceTree(root, "xml")


def test_paths_and_values():
    t = build()
    assert t.first("Doc/Head/Nr") == "F/1"
    assert t.values("Doc/Lines/Line/Name") == ["Towar 0", "Towar 1", "Towar 2"]
    assert "Doc/Lines/Line/Qty/@unit" in t.leaf_paths()
    line = t.nodes_at("Doc/Lines/Line")[1]
    assert t.first("Qty", context=line) == "2"
    assert t.first("Qty/@unit", context=line) == "pcs"
    assert t.first("Doc/Missing") is None


def test_detect_line_group():
    assert build().detect_line_group() == "Doc/Lines/Line"


def test_detect_single_line_by_hint():
    root = Node("Faktura")
    root.add(Node("Numer", "1"))
    w = root.add(Node("Pozycje")).add(Node("Pozycja"))
    w.add(Node("Nazwa", "X"))
    assert SourceTree(root, "xml").detect_line_group() == "Faktura/Pozycje/Pozycja"


def test_nested_repeats_prefer_outermost():
    root = Node("Inv")
    for _ in range(2):
        ln = root.add(Node("InvoiceLine"))
        for _ in range(3):
            ln.add(Node("Note")).add(Node("Text", "x"))
    assert SourceTree(root, "xml").detect_line_group() == "Inv/InvoiceLine"


def test_fingerprint_stable_across_line_count():
    a = build()
    root = Node("Doc")
    root.add(Node("Head")).add(Node("Nr", "F/2"))
    ln = root.add(Node("Lines")).add(Node("Line"))
    ln.add(Node("Name", "Inny"))
    ln.add(Node("Qty", "9", attrs={"unit": "kg"}))
    assert SourceTree(root, "xml").fingerprint() == a.fingerprint()
    assert len(a.fingerprint()) == 16


def test_helpers():
    assert relative_path("A/B/C/D", "A/B") == "C/D"
    assert relative_path("A/X", "A/B") is None
    assert jaccard({"a", "b"}, {"a", "b", "c", "d"}) == 0.5
    assert jaccard(set(), set()) == 0.0
