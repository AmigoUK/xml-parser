"""unikalność kluczy w bazie: faktura, NIP, przeliczniki, aliasy, mapowania (pakiet E)

Revision ID: e4a1d7c03b52
Revises: b7f3c2a91d40
Create Date: 2026-10-10 23:50:00.000000

Przed założeniem indeksów UNIQUE migracja deduplikuje istniejące dane:
- dostawcy: NIP normalizowany (bez spacji/myślników/kropek, wielkie litery); przy powtórzeniu NIP zostaje
  u najstarszego dostawcy, u pozostałych jest czyszczony z notatką (dokumenty/szablony zostają nietknięte);
- aliasy jednostek: kolumna supplier_scope (0 = globalny); powtórzenia → zostaje najstarszy;
- przeliczniki: kolumny supplier_scope/product_scope; powtórzenia klucza (dostawca, towar, z jednostki) →
  zostaje najnowszy (tak wybierał lookup);
- mapowania towarów: kolumna match_key (sha256: dostawca + kod / GTIN / nazwa); powtórzenia → zostaje
  najstarsze (tak wybierał lookup);
- dokumenty: dedupe_hash dla wszystkich, dedupe_key dla żywego oryginału (najniższe id); późniejsze żywe
  kopie tej samej faktury dostają status duplicate z problemem „duplicate”.

Funkcje normalizujące są tu skopiowane (zamrożone) z app/engine/keys.py — migracja nie może zależeć od
przyszłych zmian kodu aplikacji.
"""
import hashlib
import json
import re
import unicodedata

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4a1d7c03b52'
down_revision = 'b7f3c2a91d40'
branch_labels = None
depends_on = None

LIVE = ('approved', 'needs_review')


# ---------------------------------------------------------------- zamrożone normalizacje (stan z pakietu E)

def _fold(value):
    decomposed = unicodedata.normalize("NFKD", str(value))
    s = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", s).strip()


def _digest(*parts):
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _norm_doc_number(number):
    if number is None:
        return None
    s = re.sub(r"\s*([/\-])\s*", r"\1", _fold(number))
    return s or None


def _document_key(supplier_id, doc_type, number):
    num = _norm_doc_number(number)
    if not supplier_id or not num:
        return None
    return _digest("doc", int(supplier_id), _fold(doc_type or ""), num)


def _mapping_key(supplier_id, code, gtin, name):
    if supplier_id is None:
        return None
    if code not in (None, "") and _fold(code):
        return _digest("map", int(supplier_id), "code", _fold(code))
    if gtin not in (None, "") and str(gtin).strip():
        return _digest("map", int(supplier_id), "gtin", str(gtin).strip().zfill(14))
    if name not in (None, "") and _fold(name):
        return _digest("map", int(supplier_id), "name", _fold(name))
    return None


def _norm_tax_id(value):
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())[:64] or None


def _json(value, default):
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value


# ---------------------------------------------------------------- tabele (lekkie, tylko potrzebne kolumny)

suppliers = sa.table('suppliers', sa.column('id', sa.Integer), sa.column('tax_id', sa.String),
                     sa.column('notes', sa.Text))
aliases = sa.table('unit_aliases', sa.column('id', sa.Integer), sa.column('alias_norm', sa.String),
                   sa.column('supplier_id', sa.Integer), sa.column('supplier_scope', sa.Integer))
conversions = sa.table('unit_conversions', sa.column('id', sa.Integer), sa.column('supplier_id', sa.Integer),
                       sa.column('product_id', sa.Integer), sa.column('from_unit_id', sa.Integer),
                       sa.column('supplier_scope', sa.Integer), sa.column('product_scope', sa.Integer))
mappings = sa.table('product_mappings', sa.column('id', sa.Integer), sa.column('supplier_id', sa.Integer),
                    sa.column('supplier_code', sa.String), sa.column('supplier_gtin', sa.String),
                    sa.column('supplier_name_norm', sa.String), sa.column('match_key', sa.String))
documents = sa.table('documents', sa.column('id', sa.Integer), sa.column('supplier_id', sa.Integer),
                     sa.column('status', sa.String), sa.column('number', sa.String),
                     sa.column('doc_type', sa.String), sa.column('result', sa.Text),
                     sa.column('overrides', sa.Text), sa.column('issues', sa.Text),
                     sa.column('dedupe_hash', sa.String), sa.column('dedupe_key', sa.String))


def _delete_ids(bind, table, ids):
    ids = sorted(ids)
    for i in range(0, len(ids), 500):
        bind.execute(table.delete().where(table.c.id.in_(ids[i:i + 500])))


def _dedupe_suppliers(bind):
    rows = bind.execute(sa.select(suppliers.c.id, suppliers.c.tax_id, suppliers.c.notes)
                        .order_by(suppliers.c.id)).fetchall()
    owner = {}
    for sid, tax, notes in rows:
        norm = _norm_tax_id(tax)
        values = {}
        if norm and norm in owner:
            note = f"[migracja e4a1d7c03b52] usunięto zduplikowany NIP/VAT {norm} (ma go dostawca #{owner[norm]})."
            values = {"tax_id": None, "notes": f"{notes}\n{note}" if notes else note}
        else:
            if norm:
                owner[norm] = sid
            if norm != tax:
                values = {"tax_id": norm}
        if values:
            bind.execute(suppliers.update().where(suppliers.c.id == sid).values(**values))


def _dedupe_aliases(bind):
    bind.execute(aliases.update().values(supplier_scope=sa.func.coalesce(aliases.c.supplier_id, 0)))
    seen, drop = set(), []
    for aid, norm, scope in bind.execute(sa.select(aliases.c.id, aliases.c.alias_norm, aliases.c.supplier_scope)
                                         .order_by(aliases.c.id)):
        key = (_fold(norm or ""), scope)  # równość wg kolacji MariaDB (wielkość liter, akcenty, spacje)
        if key in seen:
            drop.append(aid)
        else:
            seen.add(key)
    _delete_ids(bind, aliases, drop)


def _dedupe_conversions(bind):
    bind.execute(conversions.update().values(supplier_scope=sa.func.coalesce(conversions.c.supplier_id, 0),
                                             product_scope=sa.func.coalesce(conversions.c.product_id, 0)))
    seen, drop = set(), []
    rows = bind.execute(sa.select(conversions.c.id, conversions.c.supplier_scope, conversions.c.product_scope,
                                  conversions.c.from_unit_id).order_by(conversions.c.id.desc()))
    for cid, ss, ps, fu in rows:  # od najnowszego — najnowszy zostaje
        if (ss, ps, fu) in seen:
            drop.append(cid)
        else:
            seen.add((ss, ps, fu))
    _delete_ids(bind, conversions, drop)


def _dedupe_mappings(bind):
    seen, drop, keys = set(), [], {}
    rows = bind.execute(sa.select(mappings.c.id, mappings.c.supplier_id, mappings.c.supplier_code,
                                  mappings.c.supplier_gtin, mappings.c.supplier_name_norm).order_by(mappings.c.id))
    for mid, sid, code, gtin, name in rows:
        key = _mapping_key(sid, code, gtin, name)
        if key is None:
            continue
        if key in seen:
            drop.append(mid)
        else:
            seen.add(key)
            keys[mid] = key
    _delete_ids(bind, mappings, drop)
    for mid, key in keys.items():
        bind.execute(mappings.update().where(mappings.c.id == mid).values(match_key=key))


def _dedupe_documents(bind):
    holders = {}
    rows = bind.execute(sa.select(documents.c.id, documents.c.supplier_id, documents.c.status, documents.c.number,
                                  documents.c.doc_type, documents.c.result, documents.c.overrides,
                                  documents.c.issues).order_by(documents.c.id)).fetchall()
    for did, sid, status, number, doc_type, result, overrides, issues in rows:
        result = _json(result, {}) or {}
        if not isinstance(result, dict):
            result = {}
        overrides = _json(overrides, {}) or {}
        full_number = result.get("number", number) if result else number
        dtype = result.get("doc_type", doc_type) if result else doc_type
        h = _document_key(sid, dtype, full_number)
        values = {"dedupe_hash": h}
        live = status in LIVE and not (isinstance(overrides, dict) and overrides.get("allow_duplicate"))
        if h and live:
            if h in holders:
                issue = {"code": "duplicate", "severity": "blocking",
                         "message": f"Ta faktura była już przetworzona (dokument #{holders[h]}).",
                         "field": None, "line_no": None, "source_path": None, "source_value": str(holders[h]),
                         "suggestions": [], "count": 1, "line_nos": []}
                old = _json(issues, []) or []
                values.update(status="duplicate",
                              issues=json.dumps([issue] + [i for i in old if isinstance(i, dict)
                                                           and i.get("code") != "duplicate"]))
            else:
                holders[h] = did
                values["dedupe_key"] = h
        bind.execute(documents.update().where(documents.c.id == did).values(**values))


def upgrade():
    bind = op.get_bind()

    # --- dostawcy: NIP znormalizowany i unikalny
    _dedupe_suppliers(bind)
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.drop_index('ix_suppliers_tax_id')
        batch_op.create_index('ix_suppliers_tax_id', ['tax_id'], unique=True)

    # --- aliasy jednostek: zakres 0 = globalny
    with op.batch_alter_table('unit_aliases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('supplier_scope', sa.Integer(), server_default='0', nullable=False))
    _dedupe_aliases(bind)
    with op.batch_alter_table('unit_aliases', schema=None) as batch_op:
        batch_op.create_index('uq_alias_scope', ['alias_norm', 'supplier_scope'], unique=True)

    # --- przeliczniki: (dostawca, towar, z jednostki) z NULL → 0
    with op.batch_alter_table('unit_conversions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('supplier_scope', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('product_scope', sa.Integer(), server_default='0', nullable=False))
    _dedupe_conversions(bind)
    with op.batch_alter_table('unit_conversions', schema=None) as batch_op:
        batch_op.create_index('uq_conversion_scope', ['supplier_scope', 'product_scope', 'from_unit_id'],
                              unique=True)

    # --- mapowania towarów: hash tożsamości (indeks z kilku VARCHAR(255) utf8mb4 przekroczyłby 3072 B)
    with op.batch_alter_table('product_mappings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('match_key', sa.String(length=64), nullable=True))
    _dedupe_mappings(bind)
    with op.batch_alter_table('product_mappings', schema=None) as batch_op:
        batch_op.create_index('ix_product_mappings_match_key', ['match_key'], unique=True)

    # --- dokumenty: klucz faktury (najwyżej jeden żywy oryginał) + indeks listy API
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dedupe_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('dedupe_key', sa.String(length=64), nullable=True))
    _dedupe_documents(bind)
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index('ix_documents_dedupe_hash', ['dedupe_hash'], unique=False)
        batch_op.create_index('ix_documents_dedupe_key', ['dedupe_key'], unique=True)
        batch_op.create_index('ix_documents_api_status_created', ['api_key_id', 'status', 'created_at'],
                              unique=False)
    if bind.dialect.name in ('mysql', 'mariadb'):
        # pozostałość po downgrade (indeks dla klucza obcego) — teraz FK obsługuje indeks złożony
        if 'ix_documents_api_key_id' in {i['name'] for i in sa.inspect(bind).get_indexes('documents')}:
            op.drop_index('ix_documents_api_key_id', table_name='documents')


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name in ('mysql', 'mariadb') and 'ix_documents_api_key_id' not in {
            i['name'] for i in sa.inspect(bind).get_indexes('documents')}:
        # InnoDB mógł użyć indeksu złożonego dla klucza obcego api_key_id (i usunąć własny) — bez
        # osobnego indeksu nie da się go skasować
        op.create_index('ix_documents_api_key_id', 'documents', ['api_key_id'], unique=False)
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index('ix_documents_api_status_created')
        batch_op.drop_index('ix_documents_dedupe_key')
        batch_op.drop_index('ix_documents_dedupe_hash')
        batch_op.drop_column('dedupe_key')
        batch_op.drop_column('dedupe_hash')

    with op.batch_alter_table('product_mappings', schema=None) as batch_op:
        batch_op.drop_index('ix_product_mappings_match_key')
        batch_op.drop_column('match_key')

    with op.batch_alter_table('unit_conversions', schema=None) as batch_op:
        batch_op.drop_index('uq_conversion_scope')
        batch_op.drop_column('product_scope')
        batch_op.drop_column('supplier_scope')

    with op.batch_alter_table('unit_aliases', schema=None) as batch_op:
        batch_op.drop_index('uq_alias_scope')
        batch_op.drop_column('supplier_scope')

    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.drop_index('ix_suppliers_tax_id')
        batch_op.create_index('ix_suppliers_tax_id', ['tax_id'], unique=False)
