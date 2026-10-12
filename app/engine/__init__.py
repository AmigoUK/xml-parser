"""Silnik parsera — czysta logika bez Flaska i bazy: drzewo źródłowe, transformacje, zastosowanie szablonu,
walidacja, podpowiedzi, wartości, klucze unikalności. Fasada eksportuje publiczne API używane przez services/web/api."""
from .canonical import (
                        FIELD_LABELS,
                        HEADER_FIELDS,
                        HEADER_KEYS,
                        LINE_FIELDS,
                        LINE_KEYS,
                        FieldDef,
                        Invoice,
                        InvoiceLine,
                        empty_invoice,
                        get_path,
                        set_path,
)
from .gs1 import GS1Error, is_valid_gtin, parse_gs1
from .issues import BLOCKING, WARNING, Issue, aggregate_line_issues, has_blocking
from .keys import alias_key, document_key, fold, mapping_key, norm_doc_number
from .lookups import Lookups, MemoryLookups, norm_alias, norm_product_name
from .suggest import (
                        Candidate,
                        ProductIndex,
                        conversion_guess,
                        draft_rules,
                        field_candidates,
                        load_synonyms,
                        product_candidates,
                        supplier_candidates,
                        unit_candidates,
)
from .template import ApplyResult, apply_template, document_decimal_sep
from .transforms import (
                        REGISTRY,
                        TRANSFORM_LABELS,
                        TransformContext,
                        TransformError,
                        apply_chain,
                        validate_chain,
                        validate_rules,
)
from .tree import Node, SourceTree, jaccard, relative_path
from .validate import validate_invoice
from .values import (
                        AmbiguousNumberError,
                        PlainNumber,
                        fmt_money,
                        fmt_price,
                        fmt_qty,
                        normalize_currency,
                        normalize_gtin,
                        parse_date,
                        parse_factor,
                        to_decimal,
)

__all__ = [
    "FIELD_LABELS", "HEADER_FIELDS", "HEADER_KEYS", "LINE_FIELDS", "LINE_KEYS", "FieldDef", "Invoice", "InvoiceLine",
    "empty_invoice", "get_path", "set_path",
    "GS1Error", "is_valid_gtin", "parse_gs1",
    "BLOCKING", "WARNING", "Issue", "aggregate_line_issues", "has_blocking",
    "alias_key", "document_key", "fold", "mapping_key", "norm_doc_number",
    "Lookups", "MemoryLookups", "norm_alias", "norm_product_name",
    "Candidate", "ProductIndex", "conversion_guess", "draft_rules", "field_candidates", "load_synonyms",
    "product_candidates", "supplier_candidates", "unit_candidates",
    "ApplyResult", "apply_template", "document_decimal_sep",
    "REGISTRY", "TRANSFORM_LABELS", "TransformContext", "TransformError", "apply_chain", "validate_chain",
    "validate_rules",
    "Node", "SourceTree", "jaccard", "relative_path",
    "validate_invoice",
    "AmbiguousNumberError", "PlainNumber", "fmt_money", "fmt_price", "fmt_qty", "normalize_currency",
    "normalize_gtin", "parse_date", "parse_factor", "to_decimal",
]
