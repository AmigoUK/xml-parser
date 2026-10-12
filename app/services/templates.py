import sqlalchemy as sa
from sqlalchemy import func

from app.extensions import db
from app.models import Document, Template, TemplateVersion


def new_version(template: Template, rules: dict, author: str | None, comment: str | None) -> TemplateVersion:
    # numer z bazy, nie z kolekcji w pamięci (mogła się zestarzeć); wyścig dwóch zapisów rozstrzyga
    # UNIQUE uq_template_version, a wywołujący ponawia (BE-7)
    last = db.session.query(func.max(TemplateVersion.version)).filter(
        TemplateVersion.template_id == template.id).scalar() or 0
    tv = TemplateVersion(version=last + 1, rules=dict(rules), author=author, comment=comment)
    template.versions.append(tv)  # przez relację, żeby kolekcja w sesji była aktualna
    db.session.flush()
    template.active_version_id = tv.id
    return tv


def create_template(supplier, tree_paths: list[str], fingerprint: str, fmt: str, rules: dict,
                    author: str | None) -> Template:
    name = f"{supplier.name} — {fmt.upper()}" if supplier else f"Format {fingerprint}"
    limit = Template.name.type.length
    if len(name) > limit:  # nazwa dostawcy 255 znaków + „ — JSON” nie mieści się w kolumnie (BE-8/EDGE-18)
        suffix = f" — {fmt.upper()}" if supplier else ""
        name = name[:limit - len(suffix) - 1].rstrip() + "…" + suffix
    t = Template(supplier_id=supplier.id if supplier else None, name=name, fingerprint=fingerprint,
                 paths=sorted(tree_paths))
    db.session.add(t)
    db.session.flush()
    new_version(t, rules, author, "Pierwsza wersja (z negocjacji)")
    return t


def active_rule_sets() -> list[dict]:
    out = []
    for t in Template.query.order_by(Template.id):
        v = t.active_version
        if v:
            out.append(v.rules)
    return out


def locked_active_version_id(doc: Document) -> int | None:
    """Aktywna wersja szablonu dokumentu odczytana z bazy pod blokadą wiersza do końca transakcji (FR-5) —
    kontrola wersji bazowej edytora (409 przy zapisie innego operatora w międzyczasie)."""
    if not doc.template_id:
        return None
    stmt = sa.select(Template.active_version_id).where(Template.id == doc.template_id)
    if db.session.get_bind().dialect.name == "sqlite":
        # SQLite nie zna FOR UPDATE: zapis no-op bierze blokadę zapisu bazy do końca transakcji
        db.session.execute(sa.update(Template).where(Template.id == doc.template_id)
                           .values(active_version_id=Template.active_version_id)
                           .execution_options(synchronize_session=False))
    else:
        stmt = stmt.with_for_update()  # odczyt blokujący widzi najnowszą zatwierdzoną wartość (InnoDB)
    return db.session.execute(stmt).scalar()
