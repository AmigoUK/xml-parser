"""Silnik jako publiczne API projektu: fasada `app.engine.__all__`, docstringi publicznych funkcji i klas,
typ dokumentu kanonicznego, rozbicie najcięższych funkcji i nazwane stałe (audyt 2026-10-11, jakość kodu)."""
import importlib
import inspect
import pkgutil
from pathlib import Path

import app.engine as engine

ROOT = Path(__file__).resolve().parent.parent.parent


def _engine_modules():
    for info in pkgutil.iter_modules(engine.__path__):
        yield importlib.import_module(f"app.engine.{info.name}")


def test_engine_facade_exports_resolve():
    assert {"apply_template", "ApplyResult", "validate_invoice", "Issue", "SourceTree", "Node", "apply_chain",
            "validate_rules", "REGISTRY", "draft_rules", "field_candidates", "product_candidates", "ProductIndex",
            "to_decimal", "fmt_qty", "parse_gs1", "empty_invoice", "Invoice", "InvoiceLine", "HEADER_FIELDS",
            "LINE_FIELDS", "Lookups", "MemoryLookups", "document_key", "mapping_key"} <= set(engine.__all__)
    for name in engine.__all__:
        assert getattr(engine, name) is not None, name


def test_public_engine_functions_classes_and_modules_have_docstrings():
    missing = []
    for mod in _engine_modules():
        if not (mod.__doc__ or "").strip():
            missing.append(mod.__name__)
        for name, obj in vars(mod).items():
            if name.startswith("_") or getattr(obj, "__module__", None) != mod.__name__:
                continue
            if inspect.isfunction(obj) or inspect.isclass(obj):
                if not (inspect.getdoc(obj) or "").strip():
                    missing.append(f"{mod.__name__}.{name}")
    assert not missing, missing


def test_canonical_invoice_typed_dicts_match_empty_invoice():
    from app.engine.canonical import LINE_FIELDS, Invoice, InvoiceLine, empty_invoice
    assert set(Invoice.__annotations__) == set(empty_invoice())
    extra = {"line_no", "unit_source", "product_index", "conversion_factor"}
    assert set(InvoiceLine.__annotations__) == {f.key for f in LINE_FIELDS} | extra


def test_apply_template_split_into_helpers():
    from app.engine import template
    for name in ("_apply_header", "_apply_line", "_resolve_unit", "_resolve_product", "_apply_conversion"):
        assert callable(getattr(template, name)), name
    body = inspect.getsource(template.apply_template)
    assert body.count("\n") < 60


def test_enrich_is_a_dispatch_table():
    from app.services import pipeline
    assert set(pipeline._ENRICHERS) == {"unknown_supplier", "unmapped_field", "transform_error", "invalid_value",
                                        "ambiguous_number", "unknown_unit", "unmapped_product", "missing_conversion"}
    assert inspect.getsource(pipeline._enrich).count("\n") < 20


def test_named_constants_instead_of_magic_numbers():
    from app import ingest
    from app.engine import suggest
    from app.services import login_guard, pipeline
    assert suggest.CONF_LEARNED == 0.95 and suggest.FUZZ_MIN_PRODUCT == 50 and suggest.FUZZ_MIN_SUPPLIER == 70
    assert suggest.CONF_GTIN == 0.6 and suggest.CONF_GS1 == 0.7
    assert suggest.CONF_DATE == 0.4 and suggest.CONF_NUMBER == 0.3
    assert pipeline.LINE_PATH_SUGGESTIONS == 15 and pipeline.CONF_CREATE_PRODUCT == 0.3
    assert ingest.BINARY_SAMPLE_BYTES == 1024 and ingest.CONTROL_SAMPLE_BYTES == 4096
    assert ingest.UTF16_ZERO_RATIO == 0.3 and ingest.CONTROL_CHAR_RATIO == 0.02
    assert 'cfg.get("LOGIN_' not in inspect.getsource(login_guard)  # wartości domyślne tylko w Config
    assert 'config.get("MAX_LINES"' not in inspect.getsource(pipeline)
    for path in ("app/services/negotiation.py", "app/services/login_guard.py", "app/web/auth.py", "app/web/catalog.py"):
        src = (ROOT / path).read_text(encoding="utf-8")
        assert "[:64]" not in src and "[:255]" not in src, path
    from app.web import documents, history, templates_views
    assert documents.RECENT_DOCS_LIMIT == 10 and documents.DOCS_LIST_LIMIT == 200 and history.HISTORY_LIMIT == 300
    assert templates_views.COMMENT_MAX == 500 and templates_views.EDITOR_CANDIDATES == 3
    from app.formatting import MIB, mib
    assert MIB == 1024 * 1024 and mib(10 * MIB) == 10
