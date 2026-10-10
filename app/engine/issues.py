from dataclasses import asdict, dataclass
from dataclasses import field as dc_field  # atrybut Issue.field przesłoniłby dataclasses.field

BLOCKING = "blocking"
WARNING = "warning"


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    field: str | None = None
    line_no: int | None = None
    source_path: str | None = None
    source_value: str | None = None
    suggestions: list[dict] = dc_field(default_factory=list)
    count: int = 1  # liczba pozycji, których dotyczy (po agregacji — EDGE-5)
    line_nos: list[int] = dc_field(default_factory=list)  # pierwsze numery pozycji (maks. MAX_LINE_NOS)

    def to_dict(self) -> dict:
        return asdict(self)


def has_blocking(issues) -> bool:
    for i in issues:
        sev = i.severity if isinstance(i, Issue) else i.get("severity")
        if sev == BLOCKING:
            return True
    return False


MAX_LINE_NOS = 20
# kod → pola klucza agregacji. Przelicznik i towar zależą od wartości (jednostka / kod+nazwa towaru),
# błędy wartości i niezgodności sum — tylko od pola (rozwiązaniem jest zmiana reguły, nie wartości).
_AGGREGATE_KEYS = {
    "missing_conversion": ("field", "source_value"),
    "unmapped_product": ("field", "source_value"),
    "invalid_value": ("field",),
    "transform_error": ("field",),
    "ambiguous_number": ("field",),
    "vat_rate_fraction": ("field",),
    "sum_mismatch_line": ("field",),
}


def aggregate_line_issues(issues: list[Issue]) -> list[Issue]:
    """Łączy powtarzające się problemy pozycji w jeden z licznikiem i listą pierwszych numerów pozycji.

    10 000 × „brak przelicznika dla worek” → 1 problem (count=10000, line_nos=[1..20]). Pierwsze
    wystąpienie zachowuje swoje miejsce na liście i line_no (formularze rozwiązywania działają bez zmian)."""
    out: list[Issue] = []
    groups: dict[tuple, Issue] = {}
    for issue in issues:
        fields = _AGGREGATE_KEYS.get(issue.code)
        if fields is None or issue.line_no is None:
            out.append(issue)
            continue
        key = (issue.code, issue.severity) + tuple(getattr(issue, f) for f in fields)
        first = groups.get(key)
        if first is None:
            issue.line_nos = [issue.line_no]
            groups[key] = issue
            out.append(issue)
            continue
        first.count += 1
        if len(first.line_nos) < MAX_LINE_NOS:
            first.line_nos.append(issue.line_no)
    for issue in groups.values():
        if issue.count > 1:
            more = ", …" if issue.count > len(issue.line_nos) else ""
            issue.message += (f" Dotyczy {issue.count} pozycji (nr {', '.join(map(str, issue.line_nos))}{more}).")
    return out
