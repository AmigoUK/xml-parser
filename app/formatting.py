"""Drobne pomocniki formatowania używane w panelu, API i serwisach."""
MIB = 1024 * 1024


def mib(n: int) -> int:
    """Liczba pełnych mebibajtów (do komunikatów o limitach rozmiaru pliku)."""
    return int(n) // MIB
