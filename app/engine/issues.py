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

    def to_dict(self) -> dict:
        return asdict(self)


def has_blocking(issues) -> bool:
    for i in issues:
        sev = i.severity if isinstance(i, Issue) else i.get("severity")
        if sev == BLOCKING:
            return True
    return False
