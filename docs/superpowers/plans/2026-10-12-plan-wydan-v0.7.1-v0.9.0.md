# Plan pracy: v0.7.1 → v0.8.0 → v0.9.0 (xml-parser)

## Kontekst

Po wydaniu v0.7.0 CI jest zielone, `[Unreleased]` puste, nic poważnego nie wisi. Przegląd 21 szablonów panelu
i 10 modułów `app/web` wykazał 25 niedoróbek UX (angielskie strony błędów Werkzeug, brak aktywnej nawigacji, listy
bez paginacji, brak potwierdzeń i flashy, niedostępne formularze, daty bez strefy, surowe kwoty). Z audytu
2026-10-11 zostały drobiazgi niskie (rate limit zmiany hasła, martwe `REMEMBER_COOKIE_*`, inline `style=`).
Z zatwierdzonych wcześniej planów nierozpoczęte są: zestaw demo „Miesiąc faktur”
(`docs/superpowers/plans/2026-10-11-zestaw-demo-design.md`) i webhooki (Etap B
`docs/superpowers/plans/2026-10-11-api-integracja-naprawy.md`).

**Decyzje użytkownika (2026-10-12):** trzy wydania — **v0.7.1 szlif UX**, **v0.8.0 zestaw demo**, **v0.9.0
webhooki**; kolumny `ApiKey.webhook_url/webhook_secret` zostają (użyje ich v0.9.0); listy słowników: strony
numerowane z zachowaniem porządku alfabetycznego; zestaw demo = Alfa, Beta, Gamma, Epsilon, Zeta + nowa **Eta**
(XML z angielskimi tagami), Delta tylko jako próbka; webhooki dostarcza usługa `worker` w Compose, `--once`
awaryjnie z crona.

## Zasady wspólne

- **Wykonanie przez subagentów (SDD)** jak przy v0.5.1: ledger `.superpowers/sdd/2026-10-12-<wydanie>/progress.md`
  (gitignored), `task-N-brief.md` (Files / Interfaces / kroki TDD), `task-N-report.md`, przegląd diffu po każdym
  zadaniu, rulingi numerowane ciągle. Zadania jednej fali nie dotykają tych samych plików; każde na gałęzi
  `feat/vX.Y.Z-TN` z `main`, merge w podanej kolejności, pełny `pytest -q` + `ruff check .` po każdym merge.
- **TDD**: test RED w `tests/test_<obszar>.py` (polski docstring modułu, `html = r.get_data(as_text=True)`,
  `"tekst" in html`, fixtures `app`/`client`/`auth_client`/`seeded` z `tests/conftest.py`; `KEY` lokalnie
  w module), potem kod. Pokrycie ≥ 90 % (CI), MariaDB tylko przez `needs_mariadb`.
- **CSP**: `script-src 'self'` — zero `on*=`/inline `<script>` (`tests/test_security_web.py`); zachowania
  w `app/static/app.js`/`editor.js`; atrybuty Alpine bez `window.`/`document.`/`=>` (`tests/test_editor_js.py:103`).
- **Chronione**: `private/`, `.env`, `tests/test_no_private_data.py`, wydane migracje. Dane fikcyjne w stylu
  istniejących („Hurtownia Alfa”, NIP `99900000xx`, GTIN `590999…`).
- **Pomoc**: po zmianie `app/help_content.py`/`app/templates/help/`/`app/help_examples/` →
  `.venv/bin/python tools/export_help.py` (pilnuje `tests/test_help_export.py`); Wiki aktualizuje się sama.
- **Wydanie** (każde): bump `pyproject.toml` → CHANGELOG `[Unreleased]`→`[X.Y.Z] — data` + link porównania →
  zrzuty `tools/screenshots.py` (Playwright w venv scratchpadu: `uv venv pw && uv pip install -p pw/bin/python
  playwright && pw/bin/python -m playwright install chromium`; `pw/bin/python tools/screenshots.py --app-python
  .venv/bin/python`; nie równolegle z pytest) → `export_help.py` → pełny pytest + ruff → commit
  `chore(release): vX.Y.Z — …` z trailerami `Co-Authored-By` / `Claude-Session` → tag → `git push origin main
  vX.Y.Z` → `gh release create vX.Y.Z --notes "<sekcja CHANGELOG>"` (tytuł jak w v0.7.0). Wdrożenie na demo
  wykonuje użytkownik (`tools/backup.sh` + `docker compose up -d --build`), ja daję komendy i weryfikuję `/healthz`.

---

# WYDANIE 1 — v0.7.1 „szlif UX panelu”

Bez zmian schematu bazy. Fale wg własności plików: F1 backend/infrastruktura (kontrakty), F2 szablony, F3 Pomoc,
zrzuty, wydanie.

### Decyzje projektowe
- **Czas**: panel pokazuje czas lokalny `DISPLAY_TZ` (domyślnie `Europe/Warsaw`), w `title` pełna strefa; API bez
  zmian (UTC `Z`). `tzdata` do `requirements.txt` + `requirements.lock` (fallback `zoneinfo` w obrazie slim).
- **Paginacja**: dokumenty/kolejka/historia/szablony → kursor po `id` (`?before=` desc; kolejka `?after=` asc,
  FIFO) z `limit+1`; **listy CRUD → `?page=N` (offset) z zachowaniem porządku `spec.order_by`** + `?q=`.
  Wspólny helper `app/web/paging.py` i partial `_pager.html`. Stałe `DOCS_LIST_LIMIT`/`HISTORY_LIMIT`/
  `RECENT_DOCS_LIMIT` zostają jako rozmiar strony (`tests/engine/test_engine_api.py:79`).
- **CSP style**: `'unsafe-inline'` w `style-src` zostaje (dynamiczne `:style` edytora i `padding-left` drzewa
  w `document.html:41`); 6 statycznych `style=` → klasy w `app.css`.
- **Nazwy = menu**: `spec.title` „Mapowania towarów”, „Jednostki”, „Przeliczniki” (`app/web/catalog.py:56,67,80`);
  h1 „Historia”, „Szablony”. Pomoc cytuje tylko „Mapowania towarów dostawcy” (`help/towary.html:44`) i podpisy
  zrzutów — poprawić w F3.
- **Limit prób hasła**: pula `pwchange:<email>` w `LoginAttempt.email` (osobna od logowania; per-IP wspólna).
- `CrudSpec` dostaje `new_label` („Nowy dostawca”), `singular_acc` (biernik do flashy/potwierdzeń),
  `search_fields`, `display` (etykieta rekordu; domyślnie 1. kolumna).

## F1 — backend i infrastruktura (7 zadań równolegle)

**T1 Polskie strony błędów** — Modify `app/api/routes.py:169-206` (istniejące `bp.app_errorhandler` — osobny
`app.errorhandler` nadpisałby JSON API; zamiast `return exc` → `_panel_error(code, title, message)`; nowy handler
403; 413 przy `request.endpoint in ("docs.upload","catalog.import_products")` → flash + redirect; 500 → najpierw
`db.session.rollback()`, render w try/except z fallbackiem tekstowym; OverflowError w panelu → strona 404).
Create `app/templates/errors/error.html` (rozszerza `base.html`, link do Pulpitu i Pomocy), `tests/test_web_errors.py`:
`test_panel_404_is_polish_page_with_nav`, `test_panel_405_polish_page`, `test_panel_403_for_non_admin_demo_reset`,
`test_upload_413_redirects_to_form_with_flash`, `test_panel_413_outside_upload_renders_page`,
`test_panel_500_polish_without_details` (widok rzucający, `PROPAGATE_EXCEPTIONS=False`, brak treści wyjątku),
`test_panel_overflow_renders_404_page`, `test_error_pages_keep_security_headers`, `test_api_errors_still_json`.
Strażnicy bez zmian: `tests/test_api.py:54,79,157-161`, `tests/test_security_gaps.py:138-171`, `tests/test_ids.py`.

**T2 Filtry Jinja + `DISPLAY_TZ` + porządki w Config** — Create `app/web/filters.py` (`register_filters(app)`;
`dt`/`dts` → `<time datetime="<UTC ISO Z>" title="Czas lokalny <TZ>">…</time>`, `None`→„—”; `money` „1 234,56”
na bazie `fmt_money` z `app/engine/values.py`; `qty` do 4 miejsc bez zer końcowych; `mib` → `app.formatting.mib`;
`ZoneInfo` z `lru_cache`, zła nazwa → UTC + warning). Modify `app/__init__.py` (rejestracja), `app/config.py`
(`DISPLAY_TZ`; usunąć `REMEMBER_COOKIE_*` l.38-40,43), `requirements.txt`/`.lock` (`tzdata`), `.env.example`,
`tests/test_security_web.py:84-85` (asercja na brak `REMEMBER_COOKIE` w źródle). Create `tests/test_filters.py`:
`test_dt_converts_naive_utc_to_warsaw_winter_and_summer`, `test_dt_has_time_element_with_utc_and_tz_title`,
`test_dts_includes_seconds`, `test_dt_none_is_dash`, `test_display_tz_configurable`,
`test_invalid_display_tz_falls_back_to_utc_with_warning`, `test_money_polish_thousands_and_comma`,
`test_qty_strips_trailing_zeros_max_four_places`, `test_money_qty_passthrough_for_non_numeric`, `test_mib_filter`,
`test_filters_registered_in_jinja_env`, `test_zoneinfo_warsaw_available`. Ryzyko: lock spójny z `pip check`/`pip-audit`.

**T3 Limit prób obecnego hasła** — Modify `app/web/auth.py:80-103` (`reserve_attempt(PASSWORD_CHANGE_PREFIX+email,
ip)` → `lockout_minutes` → 429 + flash; złe hasło = próba zostaje; poprawne → `discard_attempt`+`clear_failures`),
`app/services/login_guard.py` (stała `PASSWORD_CHANGE_PREFIX="pwchange:"`). Create
`tests/test_password_change_guard.py`: `test_locked_after_limit_wrong_current_passwords`,
`test_lockout_does_not_block_login_with_correct_password`, `test_login_failures_do_not_count_for_password_change`,
`test_correct_current_password_clears_prefixed_failures`, `test_blocked_attempt_is_discarded`.
Zamyka ostrzeżenie „missing rate limit” z przeglądu commitów.

**T4 Listy — backend** — Create `app/web/paging.py`: `page_by_id(query, id_col, per_page, *, before=None,
after=None) -> (rows, next_cursor)`, `page_by_number(query, per_page, page) -> (rows, page, pages, total)`
(offset, dla CRUD), `cursor_arg(name)` przez `parse_id` z `app/ids.py`, `next_url(param, value)`/`first_url(param)`
zachowujące pozostałe `request.args`. Modify `app/web/documents.py` (lista: `?q=` ≤100 znaków po
`Document.number` i `Supplier.name` przez `outerjoin`, `?before=`; kolejka: `?after=`; kontekst `docs, next_url,
first_url, shown, q`), `app/web/history.py` (`ACTION_LABELS` dla wszystkich akcji `audit(` w `app/` — implementer
grepuje, w tym akcje negocjacji; filtry `?action=`, `?user=`, `?before=`; `users` distinct ≤200),
`app/web/crud.py` (`CrudSpec` + 4 pola, `CRUD_PAGE_SIZE=200`, `?q=` ilike po `search_fields`, `?page=`; flash
`Zapisano {singular_acc} „{label}”.` / `Usunięto …` — prefiks „Zapisano” zachowany dla
`tests/test_negotiation_statuses.py:355`), `app/web/catalog.py` (tytuły, `new_label`, `singular_acc`,
`search_fields`: suppliers name/tax_id, products code/name/gtin, mappings supplier_code/supplier_gtin/
supplier_name_norm, units code/name, aliases alias), `app/web/templates_views.py:43-50` (jedno `group_by` zamiast
N+1, `TEMPLATES_PAGE_SIZE=100`, kursor). Szablonów nie dotyka. Create `tests/test_web_paging.py`:
`test_page_by_id_desc_returns_next_cursor_only_when_more`, `test_page_by_id_asc_with_after`,
`test_page_by_number_keeps_order_and_counts`, `test_bad_cursor_or_page_means_first_page`,
`test_next_url_preserves_filters_and_view_args`, `test_documents_list_paginates_at_limit` (monkeypatch limit=2),
`test_documents_search_by_number_and_supplier_name`, `test_queue_fifo_with_after_cursor`,
`test_history_filters_by_action_and_user`, `test_history_action_labels_cover_all_audited_actions` (skan źródeł),
`test_crud_list_search_q`, `test_crud_list_pages_alphabetical` (monkeypatch `CRUD_PAGE_SIZE=2`),
`test_crud_flash_names_object`, `test_all_specs_have_singular_forms_and_titles_match_menu`,
`test_templates_index_single_count_query` (licznik `before_cursor_execute`).
Sprawdzić `tests/test_reliability_fixes.py:49` (lista przeliczników).

**T5 Edytor: `dirty` + `beforeunload` + ARIA** — Modify `app/static/editor.js` (`dirty`, `markDirty()` w assign/
applyCandidate/clear/setLinePath/setTransforms/setDefault, `onBeforeUnload(e)` gdy `dirty && !saving`, rejestracja
w `init()`, `dirty=false` po udanym `save()`), `app/templates/editor.html` (`@input="markDirty()"` na komentarzu;
`aria-label`+`title` na przyciskach l.29,39,40; `style="min-height:0"` → `class="min-h-0"`),
`tests/test_editor_js.py` (atrapa `window.addEventListener` zbierająca handlery; testy
`test_dirty_flag_set_on_change_and_cleared_after_save`, `test_beforeunload_blocks_only_when_dirty`,
`test_init_registers_beforeunload_handler`, `test_editor_icon_buttons_have_aria_labels`,
`test_editor_has_no_static_inline_style`).

**T6 Szkielet UI** — Modify `app/templates/base.html:22` (flash: `role="alert"`, `fade show`, `<button
class="btn-close" data-bs-dismiss="alert" aria-label="Zamknij">`), `app/static/app.css` (klasy `.w-form-narrow`,
`.w-form-key`, `.scroll-pane`, `.min-h-0`, `.cell-truncate`, `.api-docs-bar`, `body.api-docs`), `app/static/app.js`
(`uploadForm`: `submitting`, `submitted()`, `submitLabel()` → „Przetwarzanie…”), `app/web/demo.py:62`
(`"danger"`→`"error"`), `app/templates/api_docs.html` (pasek „← Panel” + `app.css`, `class="api-docs"`).
Create `tests/test_web_base.py`: `test_flash_has_close_button_and_role_alert`,
`test_demo_reset_error_uses_error_category`, `test_api_docs_has_back_to_panel_bar`,
`test_app_css_defines_shared_layout_classes`, `test_upload_component_has_submitting_state`,
`test_no_inline_handlers_in_base_and_api_docs`.

**T7 Aktywna nawigacja + ARIA** — Modify `app/templates/_nav.html` (makro `nav_link(endpoint, label, active)`:
atrybuty PRZED `href`, tekst tuż przed `</a>` — `tests/test_web_help.py:73-75` wymaga dokładnie
`href="/pomoc">Pomoc</a>`; `ep = request.endpoint or ''` — na stronach błędów jest `None`; reguły: Dokumenty
aktywne też dla `docs.detail`/`docs.raw`; „Dane” aktywne gdy `request.blueprint == 'catalog'`, pozycja dropdownu
gdy endpoint kończy się `_<key>`; toggler `aria-controls="nav" aria-expanded="false" aria-label="Przełącz
nawigację"`; dropdown `id="nav-dane" role="button" aria-expanded="false"`, menu `aria-labelledby`).
Create `tests/test_web_nav.py`: `test_exactly_one_active_item_on_dashboard`,
`test_catalog_page_activates_dane_and_item`, `test_document_detail_activates_documents`,
`test_help_link_markup_exact`, `test_password_link_and_logout_present`, `test_toggler_and_dropdown_aria_attributes`,
`test_no_active_item_on_login_page`. Strażnicy: `tests/test_security_fixes.py:204-207`, `tools/screenshots.py:261`.

Kolejność merge F1: T2 → T6 → T7 → T1 → T3 → T4 → T5 (T2/T6 definiują filtry i klasy; jedyny wspólny plik
`app/__init__.py` tylko w T2).

## F2 — szablony (4 zadania równolegle, po F1)

**T8 Listy — szablony** — Create `app/templates/_pager.html` (`<nav aria-label="Stronicowanie">`, „Pokazano N
(najnowsze)”, „Starsze →” `rel="next"`, „← Najnowsze” tylko gdy kursor w args; wariant numerowany dla CRUD:
„Strona p z n”, „← Poprzednia”/„Następna →”). Modify `documents.html` (form `role="search"`, `input type="search"
name="q" aria-label`, hidden `status`; przyciski statusów przenoszą `q`), `_doc_table.html` (`table-responsive`,
nazwa pliku `d-inline-block text-truncate cell-truncate` + `title`, `|dt`, stany puste: kolejka „Kolejka pusta —
wszystko wyjaśnione.”, `q` → „Brak dokumentów pasujących do „…””, inaczej „Brak dokumentów. Wgraj fakturę →”;
używać `q is defined and q` — partial jest też na pulpicie), `history.html` (h1 „Historia”, formularz filtrów
select `action` + `input user` z `<datalist>`, `table-responsive`, `|dts`, etykieta akcji z `title` = surowy kod,
payload `code.small.text-break`, pager), `crud_list.html` (form `q` gdy `spec.search_fields`, `table-responsive`,
`data-confirm="Usunąć {{ spec.singular_acc }} „{{ spec.label(row) }}”?"`, pusty stan „Brak rekordów. Dodaj
pierwszy →” + `extra_actions` („Import CSV”), pager numerowany), `templates_list.html` (h1 „Szablony”,
`table-responsive`, pager). Create `tests/test_web_lists_ui.py`: `test_documents_pager_shows_count_and_next_link`,
`test_pager_keeps_status_and_q_in_links`, `test_queue_pager_labels_and_empty_state`,
`test_documents_empty_state_links_upload`, `test_list_pages_wrap_tables_in_table_responsive` (6 stron),
`test_doc_table_truncates_filename_with_title_and_local_time`, `test_history_polish_action_label_and_filter_form`,
`test_history_payload_has_text_break`, `test_crud_delete_confirm_contains_singular_and_name`,
`test_crud_empty_state_add_and_import_links`, `test_crud_numbered_pager_alphabetical`,
`test_crud_search_box_only_for_specs_with_search_fields`, `test_headings_match_menu_labels`.

**T9 Widok dokumentu i karty problemów** — Modify `document.html` („← Wróć do kolejki” gdy `needs_review`, inaczej
„← Wróć do dokumentów”; nazwa pliku truncate+title; `style` l.39 → `scroll-pane` (l.41 zostaje); nagłówek wyniku
`money`/`qty` wg `f.kind` z `app/engine/canonical.py` (`header_fields`/`line_fields`) + `text-end`; tabela pozycji
`th/td.text-end` dla money/price/decimal, `conversion_factor|qty`; „Pokazano … z …” bez zmian —
`tests/test_ingest_limits.py:135`), `_issues.html` (`form_open(doc, action, confirm=None)` → `data-confirm`;
`remember(idx, action)` → `id="remember-{idx}-{action}"` + `<label for>` — ten sam idx ma dwie akcje
z `remember`; `aria-label`/`<label for>` na polach l.35,36,43,67,68,74,75,88,104,105,108,122,134,135,136;
`factor` `inputmode="decimal"`; `code`/`name` placeholdery; „Odrzuć” `confirm='Odrzucić dokument? Cofnąć to może
tylko „Przywróć”.'`). Create `tests/test_web_document_view.py`: `test_back_link_targets_queue_or_documents_by_status`,
`test_money_and_qty_formatting_and_text_end`, `test_remember_checkboxes_have_unique_ids_with_labels`,
`test_issue_controls_have_labels_or_aria_labels` (regex po `<input`/`<select` poza hidden),
`test_factor_input_is_decimal_inputmode`, `test_reject_form_has_confirm` (ta sama próbka 2×),
`test_scroll_pane_replaces_inline_style`, `test_no_inline_js_on_document_page`. Nazwy pól POST bez zmian
(`tests/test_negotiation*.py`).

**T10 Szablon (szczegóły) i Klucze API** — Modify `app/web/apikeys.py` (flash: toggle „Klucz „X” wyłączony/
włączony.”, rename pusta → „Podaj nową nazwę klucza.” error, sukces „Zmieniono nazwę klucza na „X”.”, delete
„Usunięto klucz „X”.”, brak klucza → „Nie znaleziono klucza.”; `name_max=NAME_MAX` w kontekście),
`apikeys.html` (`w-form-key`, `<label class="visually-hidden" for="new-key-name">`, `maxlength`, rename
`aria-label`+`maxlength`, przycisk „Zmień nazwę”, toggle aktywnego `data-confirm="Wyłączyć klucz „X”? Systemy
używające go przestaną działać."`, `|dt`, `table-responsive`, `{% else %}` „Brak kluczy — utwórz pierwszy
powyżej.”, „Skopiuj teraz” zostaje), `template_detail.html` („← Szablony”, dostawca pod h1 (`t.supplier` może
być None), `<label for>` na selectach porównania, `table-responsive`, `|dt`, „Przywróć” `data-confirm`).
Create `tests/test_web_apikeys.py`: `test_toggle_flashes_new_state`, `test_rename_empty_flashes_error_and_keeps_name`,
`test_rename_flashes_new_name`, `test_delete_flashes_name`, `test_page_markup_labels_maxlength_confirms`,
`test_empty_keys_state`; w `tests/test_web_templates.py`: `test_detail_has_back_link_supplier_and_select_labels`,
`test_restore_button_has_confirm`.

**T11 Formularze** — Modify `crud_form.html` (h1 `spec.new_label` / `„{title} — edycja „{label}””`, `w-form-narrow`,
textarea `maxlength` (`TEXTAREA_MAX=2000` w `crud.py` — kolumny Text bez długości), number `inputmode="decimal"`
+ placeholder), `login.html` (`<label for>`, `autocomplete="username"`/`"current-password"`, e-mail z
`request.form` po błędzie), `upload.html` (`<label for="file">`, `required`, „Maks. {{ config['MAX_DOCUMENT_BYTES']
|mib }} MiB; XML, JSON lub CSV.”, `@submit="submitted()"`, `:disabled="submitting" x-text="submitLabel()"`),
`products_import.html` (`style`→klasa, `<label for>`). Create `tests/test_web_forms.py`:
`test_login_autocomplete_and_email_refilled_after_error`, `test_upload_form_required_hint_and_submit_lock`,
`test_crud_form_headings_use_new_label_and_record_name`, `test_crud_textarea_maxlength_and_number_inputmode`,
`test_forms_have_no_static_inline_style`.

Merge F2: T8 → T9 → T10 → T11.

## F3 — Pomoc, zrzuty, wydanie (1 agent, sekwencyjnie)

**T12** — Modify `app/help_content.py` (FAQ: „Jaki czas pokazuje panel?” — `DISPLAY_TZ`, API w UTC; „Lista
pokazuje tylko 200 wpisów — gdzie reszta?” — „Starsze →”, wyszukiwarka, filtry historii; slugi `czas-w-panelu`,
`dluzsze-listy`), `help/towary.html:44` („Mapowania towarów”), podpisy zrzutów w `help/szablony.html:9`,
`help/jednostki.html:38-40`, README l.53-58 (podpisy „Szablony”, „Przeliczniki”) + tabela env (`DISPLAY_TZ`),
`docker-compose.yml` (`DISPLAY_TZ` w `environment` — `tests/test_ops_scripts.py:100` pilnuje listy),
`tools/screenshots.py` (`ENV_PREFIXES`: +`DISPLAY_TZ`, −`REMEMBER_COOKIE`), CHANGELOG `[0.7.1]` (Added: strony
błędów PL, paginacja+wyszukiwanie+filtry historii, flash kluczy, potwierdzenia, stany puste, `DISPLAY_TZ`,
`beforeunload`; Changed: nazwy = menu, formaty kwot/czasu, etykiety akcji, „Zmień nazwę”; Fixed: N+1 szablonów,
pusta nazwa klucza, kategoria flasha demo, dostępność formularzy; Security: limit prób hasła, usunięcie
`REMEMBER_COOKIE_*`; znane ograniczenie: 413 przed odczytem body może dać reset połączenia w przeglądarce),
`pyproject.toml` 0.7.1. Kroki: Pomoc → `export_help.py` → zrzuty (13 stron) → README/CHANGELOG/bump → pełny
pytest + ruff → commit `chore(release): v0.7.1 — szlif UX panelu: strony błędów, paginacja, dostępność` →
tag → push → `gh release create`.

### Kryteria akceptacji v0.7.1
1. Pełny pytest zielony (lokalnie i CI z MariaDB), pokrycie ≥ 90 %, ruff czysty.
2. 404/403/405/413/500/OverflowError w panelu → polska strona z nav i stopką; `/api/*` nadal JSON.
3. Dokładnie jedna pozycja `aria-current="page"` na stronach panelu; `href="/pomoc">Pomoc</a>` bez zmian.
4. Każda lista ma `table-responsive` i pager; dokumenty `?q=`, CRUD `?q=`+`?page=` alfabetycznie, historia
   `?action=`/`?user=` z polskimi etykietami wszystkich akcji z kodu.
5. Czas w 4 miejscach przez `|dt`/`|dts` (`<time datetime="…Z" title="…">`), kwoty „1 234,56”, `text-end`.
6. `data-confirm` na: Odrzuć, Przywróć wersję, Wyłącz klucz, usuwanie CRUD z nazwą; flashe kluczy i CRUD z nazwą;
   flash zamykany, `role="alert"`; `demo.py` bez `"danger"`.
7. Brak `on*=`, brak statycznych `style=` (poza drzewem i `:style`); edytor `dirty`/`beforeunload`; 429 po
   `LOGIN_MAX_ATTEMPTS` złych obecnych haseł; logowanie nienaruszone.
8. `docs/pomoc/` zgodne, 13 zrzutów z „v0.7.1” w stopce, README podpisy = h1, CHANGELOG, tag, GitHub Release.

---

# WYDANIE 2 — v0.8.0 „zestaw demo «Miesiąc faktur»”

### Ustalenia z kodu (wiążące)
- `ingest()` (`app/services/pipeline.py:437`) commituje każdy dokument; duplikat „ten sam plik” po `sha256`
  w zakresie (`api_key_id`) niezależnie od rozpoznania dostawcy; duplikat po numerze wymaga `supplier_id`.
- `sum_mismatch_total` jest blokujący bez podpowiedzi → pułapka „niezgodność sum” = **`sum_mismatch_line`**
  (ilość×cena ≠ netto pozycji, sumy faktury z netto pozycji) → `approved` + ostrzeżenie.
- Brak waluty → `unmapped_field` (`currency`), pierwsza podpowiedź `PLN`. `conversion_guess` czyta ostatnie
  `liczba+(kg|g|ml|l|szt)` z nazwy → „karton 20 szt” daje 20.
- Synonimy EN dla XML Ety są w `data/synonyms.yaml` (InvoiceNumber, IssueDate, Currency, SellerName, SellerVAT,
  Totals/Net|Vat|Gross, ProductCode, GTIN, ProductName, Quantity, unit, UnitPrice, NetAmount, VatRate); jednostki
  `pcs, pce, ea, c62, h87, kart.` w słowniku podpowiedzi.
- `tools/` nie trafia do obrazu Docker, `demo/` tak → serwis i Pomoc czytają `demo/dataset/manifest.json`.
- Numery zestawu nie kolidują z `demo/samples` (oba zbiory mogą być w jednej bazie, np. w `tools/screenshots.py`).

### Decyzje
- Skład: **Alfa, Beta, Gamma, Epsilon, Zeta, Eta** × 4 = 24 pliki; Delta zostaje próbką; jej pułapka `kart.`
  przechodzi do 3. faktury Zety. Eta = „Eta Packaging Sp. z o.o.”, NIP `9990000077`, XML z angielskimi tagami.
- Pliki **commitowane** + deterministyczny generator `tools/gen_demo_dataset.py` (bez importu `app`, własna cyfra
  kontrolna GTIN, `random.Random(seed)` tylko do ilości, kwoty `Decimal`); test „regeneracja = identyczne bajty”.
- Manifest: `expected.on_ingest` (status + zbiory kodów `blocking`/`warnings`) i `expected.after_resolve`
  (po pierwszych podpowiedziach; `null` dla czystych i duplikatu). Duplikat = plik `20-beta-3-ponownie.xml`
  bajt w bajt równy `14-beta-3.xml`.
- Postęp dopasowany po `(filename, sha256)` niezależnie od `source` (panel i API widoczne w tabeli, kolumna źródło).
- Pomoc: **nowy temat `zestaw-demo`** po `pierwsza-faktura` (tabela 24 wierszy renderowana z manifestu, skrypt API);
  `pierwsza-faktura` dostaje odnośnik. Przycisk „Wyczyść dane demo” → **„Resetuj zestaw demo”** (ta sama akcja).

### Rozkład pułapek (kolejność = daty październik 2026)
| NN | plik | pułapka | on_ingest | after_resolve |
|---|---|---|---|---|
| 01 | alfa-1 | nowy dostawca, brak waluty, `pcs`, towar po kodzie | needs_review: unknown_supplier, unmapped_field, unknown_unit, unmapped_product | approved |
| 02 | beta-1 | nowy dostawca, `worek`→kg ×25 z nazwy, towar po nazwie | needs_review: unknown_supplier, unmapped_product, missing_conversion | approved |
| 03 | eta-1 | nowy dostawca (XML EN), `pcs`, towar po nazwie | needs_review: unknown_supplier, unknown_unit, unmapped_product | approved |
| 04 | gamma-1 | nowy dostawca, `C62`/`H87`, towar po nazwie | needs_review: unknown_supplier, unknown_unit, unmapped_product | approved |
| 05 | epsilon-1 | nowy dostawca, `EA`, towary po GTIN | needs_review: unknown_supplier, unknown_unit | approved |
| 06 | zeta-1 | nowy dostawca, `wor.`→worek 25 kg, towary spoza kartoteki | needs_review: unknown_supplier, unknown_unit, missing_conversion, unmapped_product | approved |
| 07–12 | *-2 | czyste drugie faktury | approved | — |
| 13 | alfa-3 | `sum_mismatch_line` | approved + warning | — |
| 14 | beta-3 | czysta | approved | — |
| 15 | eta-3 | towar spoza kartoteki (nowy GTIN) → `create_product` | needs_review: unmapped_product | approved |
| 16 | gamma-3 | nowy alias `PCE` zamiast `C62` | needs_review: unknown_unit | approved |
| 17 | epsilon-3 | brak klucza `currency` | needs_review: unmapped_field | approved |
| 18 | zeta-3 | `kart.`→karton + przelicznik 20 szt z nazwy + nowy towar | needs_review: unknown_unit, missing_conversion, unmapped_product | approved |
| 19 | alfa-4 | czysta | approved | — |
| 20 | beta-3-ponownie | duplikat bajtowy 14 | duplicate | null |
| 21–24 | eta/gamma/epsilon/zeta-4 | czyste | approved | — |

„Wczytaj wszystko naraz” bez nauki: 01–06 i 07–19, 21–24 → `needs_review` (nieznany dostawca), 20 → `duplicate`.

## F1 (równolegle)

**T1 Generator i zestaw plików** — Create `tools/gen_demo_dataset.py` (`generate(out_dir)`, `load(out_dir)`,
`main(argv)` z `--out`/`--check`; renderery per format; `gtin_check_digit`), `demo/dataset/` (24 pliki
`NN-<dostawca>-<k>.<ext>`, `manifest.json` z `version, title, generator{tool,seed}, suppliers{}, files[]`
zapisany `indent=2, ensure_ascii=False`, `README.md` generowany), `tests/test_demo_dataset_files.py`:
`test_manifest_lists_exactly_the_files_in_directory`, `test_manifest_entries_well_formed` (order 1..24, phase,
kody w `ISSUE_HELP`, `duplicate_of` → wcześniejszy plik o tym samym sha, 6 wpisów `first` po jednym na dostawcę),
`test_sha256_in_manifest_matches_files`, `test_generator_is_deterministic`, `test_dataset_does_not_collide_with_samples`,
`test_files_parse`, `test_fictional_identifiers_only`, **`test_expected_statuses_on_fresh_db`** (test prawdy
manifestu: wczytanie w kolejności z `resolve_with_top_suggestions` dla `first` → statusy i zbiory kodów równe
`expected`). Ryzyko: `draft_rules` dla Ety może dodać `unmapped_field` → dostroić tagi, nie silnik; nazwy nowych
towarów wyraźnie inne od kartoteki (`FUZZ_MIN_PRODUCT=50`).

**T2 Serwis `app/services/demo_dataset.py`** — czyste funkcje testowane na manifeście syntetycznym (monkeypatch
`DATASET_DIR`): `load_manifest(path=None) -> Manifest`, `is_available()`, `Entry` (frozen dataclass),
`ProgressRow(entry, doc_id, status, status_label, source, matches_expected)`, `progress()` (jedno zapytanie po
zbiorze nazw, najnowszy `id` na parę), `pending(phase_key)`, `load_entries(entries, source="demo") ->
BatchResult(loaded, skipped)`, `load_phase(phase_key, source)` (`PHASES = {"pierwsze": ("first",), "pozostale":
("rest",), "wszystko": ("first","rest")}`; nieznana → `KeyError`), `counts()`. Create `tests/test_demo_dataset_service.py`:
`test_load_manifest_parses_entries_and_phases`, `test_is_available_false_without_manifest`,
`test_progress_matches_by_filename_and_sha_any_source`, `test_progress_distinguishes_duplicate_entry_from_original`,
`test_pending_skips_loaded_entries`, `test_load_phase_is_idempotent`, `test_load_phase_unknown_key`,
`test_matches_expected_accepts_on_ingest_or_after_resolve`.

## F2 (równolegle, po T1+T2)

**T3 Widok `/demo`** — Modify `app/web/demo.py` (`GET /demo` + `dataset=progress()`, `dataset_counts`; `POST
/demo/zestaw/wczytaj/<phase>` login_required, `phase ∉ PHASES` → 404, flash „Wczytano N faktur, pominięto M już
wczytanych”, redirect `/demo#zestaw`; `StorageUnavailable/DocumentTooLarge` → flash error; reset: etykieta
„Resetuj zestaw demo”, `data-confirm`), `app/templates/demo.html`, Create `_demo_dataset.html` (karta `id="zestaw"`,
3 przyciski z liczbami z `counts()`, wyszarzone gdy `pending` puste, tabela: #, plik, dostawca, format, co
pokazuje, oczekiwany, faktyczny status z linkiem, źródło; `table-warning` gdy `matches_expected is False`).
Testy w `tests/test_web_demo.py`: `test_demo_page_shows_dataset_table_with_24_rows_and_buttons`,
`test_dataset_buttons_hidden_when_logged_out`, `test_load_first_phase_creates_six_demo_documents_and_redirects_to_anchor`,
`test_load_first_phase_twice_skips_loaded`, `test_load_rest_then_all_is_idempotent`, `test_unknown_phase_404`,
`test_reset_button_renamed`, `test_reset_forbidden_for_operator_role`, `test_dataset_endpoints_404_outside_demo_mode`,
`test_web_demo_only_wires_views` (wzór `tests/test_services_layering.py`).

**T4 Testy e2e + parametryzacja uczenia** — Create `tests/test_demo_dataset_e2e.py`:
`test_first_phase_all_needs_review_with_expected_codes`, `test_resolve_first_then_rest_follow_manifest`
(13 → warning `sum_mismatch_line`, 16 → alias `PCE` Gammy, 18 → `conversion_factor == "20"`, 17 → waluta,
20 → `issues[0].source_value == str(id dok. 14)`), `test_all_at_once_without_learning`,
`test_reset_then_identical_run`, `test_progress_rows_match_expected_after_full_flow`. Modify `tests/test_learning.py`
(parametry `("dataset", "01-alfa-1.xml", "07-alfa-2.xml")` itd. dla 6 dostawców, realne drugie pliki).

**T5 Skrypt curl przez API** — Create `app/help_examples/zestaw-demo.sh` (`set -euo pipefail`, `BASE="__API_BASE__
/api/v1"`, `XP_API_KEY` wymagany, argumenty `[pierwsze|pozostale|wszystko] [katalog]`, filtr manifestu jq-iem,
`-F file=@…`, wypis `#<id> <status> <plik>`, podsumowanie; brak curl/jq → kod 1), `tests/test_demo_dataset_example.py`
(import `live_api`, `require_runtime` z `tests/test_help_examples_run.py`): `test_script_loads_first_phase_all_needs_review`,
`test_script_rest_after_panel_learning_follows_manifest`, `test_script_reports_missing_jq`,
`test_script_unknown_phase_exits_1`, `test_script_is_valid_bash`.

**T6 Zrzut `14-demo-zestaw`** — Modify `tools/screenshots.py` (w `serve()` najpierw `load_phase("pierwsze")`,
potem `SAMPLES`; `DOC_ID`/`ZETA_ID` z przesunięciem o liczbę z manifestu; `Shot("14-demo-zestaw", "/demo#zestaw",
False)`), `tests/test_screenshots_tool.py` (zrzut FAQ szukany po nazwie `13-faq-worek` zamiast `PAGES[-1]`;
`test_dataset_first_phase_offsets_document_ids`; `/demo` zawiera „Zestaw demo” w teście `--serve`).
PNG generuje orkiestrator (Playwright poza `.venv`) przed F3.

## F3 (równolegle, po F2)

**T7a Pomoc `zestaw-demo`** — Modify `app/help_content.py` (TOPICS wpis po `pierwsza-faktura`; FAQ „Jak wczytać
zestaw demo przez API?” slug `zestaw-demo-api`), `app/web/help.py` (dla slugu `zestaw-demo`: manifest + skrypt
z podstawionym `__API_BASE__`; brak katalogu → komunikat, nie 500; renderuje się bez `DEMO_MODE` — eksport),
Create `app/templates/help/zestaw-demo.html` (po co, jak przejść krok po kroku, tabela 24 wierszy z manifestu,
zrzut 14, legenda pułapek — m.in. „dla dostawcy w GBP wybierz GBP, nie pierwszą podpowiedź”, sekcja „Przez API”
z uwagą o zakresie klucza), `help/pierwsza-faktura.html` i `help/jak-to-dziala.html` (odnośnik, podpisy zrzutów
02/03 — pokazują dokumenty zestawu), `tests/test_web_help.py` (`HELP_SHOTS["zestaw-demo"] = ["14-demo-zestaw.png"]`;
`test_dataset_topic_lists_all_files_and_phases`, `test_dataset_topic_renders_api_script_with_request_host`,
`test_dataset_topic_without_dataset_dir_is_not_500`), eksport `docs/pomoc/`.

**T7b Dokumentacja** — Modify `README.md` („Tryb demo”: przyciski, tabela postępu, „Resetuj zestaw demo”, skrypt
API; tabela zrzutów + `14-demo-zestaw.png`; „Rozwój lokalny”: `gen_demo_dataset.py --check`), CHANGELOG
`[Unreleased]` (treść Added/Changed), `docs/superpowers/plans/2026-10-11-zestaw-demo-design.md` (v0.8.0, Eta,
decyzje), `demo/samples/README.md` (akapit o `demo/dataset/`). Testy: `tests/test_docs_assets.py`,
`tests/test_no_private_data.py`.

## F4 — T8 weryfikacja (ruff, pytest z cov, `gen_demo_dataset.py --check`, `export_help.py` bez różnic),
**T9 wydanie v0.8.0**: bump → pełna regeneracja 14 zrzutów → CHANGELOG `[0.8.0]` → export_help → commit
`chore(release): v0.8.0 — zestaw demo „Miesiąc faktur”: 24 faktury, pułapki w czasie, import przez API` → tag →
push → `gh release create`.

### Kryteria akceptacji v0.8.0
- `demo/dataset/` = 24 faktury + manifest + README; `--check` zwraca 0; test determinizmu zielony; brak kolizji
  z `demo/samples`; strażnik danych prywatnych zielony.
- Świeża baza: „pierwsze (6)” → 6× `needs_review` z kodami z manifestu → po rozwiązaniu 6× `approved`;
  „pozostałe (18)” → 13× `approved` (1 z ostrzeżeniem), 4× `needs_review` (15–18) rozwiązywalne, 1× `duplicate`
  wskazujący dokument 14. Ponowne kliknięcie nie tworzy dokumentów; reset (admin, 403 dla innych) → identyczny
  przebieg.
- Tabela postępu z linkami i źródłem; skrypt `zestaw-demo.sh` wykonany w testach wobec prawdziwego serwera.
- Pomoc `zestaw-demo` + `docs/pomoc/zestaw-demo.md`, README, `test_learning.py` obejmuje 6 dostawców;
  14 zrzutów z „v0.8.0”; tag + Release; dokument projektu zaktualizowany.

---

# WYDANIE 3 — v0.9.0 „webhooki”

### Korekty względem planu Etapu B
- Wydanie v0.9.0; `down_revision` nowej migracji = aktualna głowa **`d2c1e7a94f30`**; kolumny `api_keys.webhook_*`
  istnieją od migracji początkowej — używamy, nie dodajemy.
- Outbox dostaje **`uuid`** (String 36, unique) — `X-XP-Delivery` stały między ponowieniami; indeks
  `(api_key_id, created_at, id)` dla list.
- Mutacje webhooka w panelu wymagają roli `admin` (jak `demo.reset`); istniejące akcje kluczy bez zmian.
- Zdarzenie emitowane także dla przejścia `received → …` (każda zmiana statusu do approved/needs_review/
  duplicate/rejected).

### Decyzje architektoniczne
1. **Punkt emisji**: `pipeline.process(doc, *, previous_status=None)` (zapamiętuje `doc.status` przed `_process`,
   emituje po `touch()` w obu gałęziach) + jawny hook w `negotiation.a_reject`; `restore()` przekazuje
   `previous_status=STATUS_REJECTED`. Obejmuje kaskady, edytor (`commit_with_retry`), API i panel. Dokumenty
   bez `api_key_id` (panel/demo) i klucze nieaktywne → brak zdarzeń.
2. **Outbox w tej samej sesji**, bez flush; commit/rollback wywołującego decyduje.
3. **Ładunek** `{event, id, status, previous_status, updated_at, document_url}` budowany przy enqueue; bajty
   (`json.dumps(sort_keys, separators=(",",":"))`) i podpis liczone przy wysyłce. `document_url` z nowej
   `PUBLIC_BASE_URL` (fallback `request.host_url` → `null`).
4. **Worker** = usługa compose `worker` (`flask webhooks-worker`, pętla 5 s, SIGTERM/SIGINT → stop, heartbeat
   do pliku dla healthchecku); `--once` awaryjnie z crona. Entrypoint: tryb „jeśli podano argumenty, wykonaj je”
   po sondzie bazy, `MIGRATE_ON_START=0` dla workera.
5. **Lease zamiast długiej blokady**: `SELECT … FOR UPDATE SKIP LOCKED` (tylko dialekt mysql) LIMIT 50,
   `attempts+=1`, `next_attempt_at=now+60s`, commit; HTTP poza transakcją; wynik osobnym commitem.
6. **Harmonogram** `BACKOFF=(60,300,1800,7200,43200)`, `MAX_ATTEMPTS=6` → `failed`; „Ponów” resetuje.
7. **Klient HTTP stdlib** `http.client` z przypiętym IP (`create_connection((ip,port),5)` + SSL
   `server_hostname=host`), bez redirectów (3xx = porażka), `read(1024)`. Zero nowych zależności.
8. **SSRF**: `not ip.is_global` (prywatne, loopback, link-local/metadata, CGNAT 100.64/10, mapped IPv6);
   wszystkie adresy z `getaddrinfo`; `WEBHOOK_ALLOWED_HOSTS` = nazwy i CIDR; walidacja przy zapisie i przy każdej
   wysyłce; tylko https (http przy `WEBHOOK_ALLOW_HTTP=1`), bez userinfo/fragmentu, ≤500 znaków.
9. **Sekret** `secrets.token_urlsafe(32)`, pokazany raz; nigdy w audycie/logach/API. Ustawienie adresu bez sekretu
   generuje go.
10. **FK** `webhook_deliveries.api_key_id ondelete=CASCADE`; `document_id` nullable; `reset_demo` kasuje
    `WebhookDelivery` przed `Document`.
11. **`webhook.test`** w tym samym kształcie (pola dokumentu `null`), wysyłany synchronicznie z panelu.
12. **Retencja** `flask prune-webhooks [--days]` (`WEBHOOK_RETENTION_DAYS=30`), wzór `prune-audit`.
13. **API** `GET /api/v1/webhook-deliveries` (read-only, filtry `status`, `document_id`, kursor po
    `(created_at,id)` desc z `app/api/cursor.py`); OpenAPI 3.0.3: `WebhookEvent`, `WebhookDelivery`,
    `WebhookDeliveryList`, opis w `info.description`, bez `callbacks`.
14. **Pomoc**: nowy temat `webhooki` po `integracja` + „Sposób C — webhook” w `integracja#odbior`; przykłady
    `webhook-odbiorca.{py,php,mjs,sh}` z trybem `--check` (sekret z env, ts i podpis z argumentów, body stdin,
    kod 0/1) → testowalne bez serwera.
15. **Compose**: kotwica `x-app-env: &app-env`, `worker` dziedziczy + `MIGRATE_ON_START: "0"`, wolumen `storage`,
    `depends_on: app: service_healthy`, healthcheck po heartbeat.

### Kontrakty
```
app/models.py: WebhookDelivery(id, uuid, api_key_id, document_id, event, payload JSON, status, attempts,
  next_attempt_at, last_error, last_status_code, created_at, sent_at); stałe WEBHOOK_PENDING/SENT/FAILED,
  EVENT_STATUS_CHANGED="document.status_changed", EVENT_TEST="webhook.test"; Document.api_key relationship
app/config.py: PUBLIC_BASE_URL, WEBHOOK_ALLOW_HTTP, WEBHOOK_ALLOWED_HOSTS, WEBHOOK_RETENTION_DAYS, WEBHOOK_HEARTBEAT_FILE
app/services/webhook_security.py: validate_target(url,*,allow_http,allowed_hosts,resolve=True)->ResolvedTarget,
  is_blocked_ip, parse_allowed_hosts, sign(secret,ts,body)->"sha256=…", verify(...,max_skew=300), new_secret(),
  HEADER_TIMESTAMP/SIGNATURE/DELIVERY
app/services/webhook_outbox.py: build_payload(doc, previous), document_url(id), emit_status_change(doc, previous),
  enqueue_test(key)
app/services/webhooks.py: claim_batch(now,limit), send(delivery,*,now)->SendResult, apply_result, deliver_pending(now,limit)->int,
  send_now(delivery), retry(delivery,now), prune_deliveries(days), run_worker(app,*,interval,stop,heartbeat), send_http(target,body,headers)
app/services/apikeys.py: set_webhook_url(key,url)->new_secret|None, rotate_webhook_secret(key)->str, clear_webhook(key)
app/api/serializers.py: delivery_to_json(d)
CLI: flask webhooks-worker [--once] [--interval 5]; flask prune-webhooks [--days N]
```

## F0 (sekwencyjnie) — **T0 fundament**
Modify `app/models.py`, `app/config.py`, `app/services/seed.py:106-112`, `tests/test_migrations.py` (parametryzacja
łańcucha). Create `migrations/versions/<rev>_webhook_deliveries.py` (`down_revision='d2c1e7a94f30'`, idempotentne
create/drop jak `2eff54106035`), `tests/test_webhook_model.py`: `test_revision_follows_parent_on_a_single_chain[webhooki]`,
`test_webhook_deliveries_upgrade_and_downgrade_on_sqlite`, `test_webhook_deliveries_schema_matches_models_on_mariadb`
(needs_mariadb), `test_deleting_api_key_cascades_deliveries`, `test_deleting_document_with_delivery_is_rejected`,
`test_reset_demo_removes_deliveries_before_documents`, `test_config_webhook_defaults`.

## F1 (równolegle, po T0)
**T1 emisja (outbox)** — Create `app/services/webhook_outbox.py`, `tests/test_webhook_outbox.py`; Modify
`pipeline.py`, `negotiation.py`. Testy: `test_ingest_by_api_key_with_webhook_creates_one_delivery`,
`test_no_delivery_without_webhook_url`, `test_no_delivery_for_panel_document_without_api_key`,
`test_no_delivery_when_status_unchanged`, `test_reject_in_panel_emits_rejected`, `test_restore_emits_with_previous_rejected`,
`test_duplicate_cascade_emits_for_demoted_document`, `test_outbox_row_disappears_with_rollback`,
`test_commit_with_retry_leaves_single_delivery`, `test_document_url_falls_back_to_request_host_then_null`,
`test_inactive_key_does_not_enqueue`, `test_payload_updated_at_matches_api_format`. Nie importować `pipeline`
z outboxu (cykl).
**T2 bezpieczeństwo celu i podpis** — Create `app/services/webhook_security.py`, `tests/test_webhook_security.py`
(`getaddrinfo` zawsze monkeypatch): `test_rejects_http_without_flag`, `test_allows_http_with_flag`,
`test_rejects_userinfo_fragment_and_long_url`, `test_blocks_loopback_private_linklocal_metadata_cgnat`,
`test_localhost_name_resolving_to_loopback_is_blocked`, `test_dns_returning_one_private_among_public_is_blocked`,
`test_allowlist_hostname_and_cidr_bypass_block`, `test_dns_failure_is_target_error`,
`test_sign_matches_reference_vector` (ten sam wektor w przykładach T5), `test_verify_rejects_tampered_body_and_old_timestamp`,
`test_new_secret_length_and_alphabet`.
**T4 ops** — Modify `docker/entrypoint.sh`, `docker-compose.yml`, `.env.example`, `tests/test_ops_scripts.py`:
`test_entrypoint_execs_given_command_instead_of_gunicorn`, `test_entrypoint_without_arguments_still_starts_gunicorn`,
`test_entrypoint_command_mode_respects_migrate_on_start`, `test_compose_worker_service_shares_env_and_runs_worker`,
`test_compose_app_gets_only_app_variables` (+ nowe zmienne), `test_env_example_documents_webhook_variables`.
Healthcheck HTTP z Dockerfile nadpisać w compose heartbeatem.
**T5 przykłady weryfikacji podpisu** — Create `app/help_examples/webhook-odbiorca.{py,php,mjs,sh}`,
`tests/test_webhook_examples_run.py` (`test_check_mode_accepts_valid_signature[runtime]`,
`test_check_mode_rejects_tampered_body[runtime]`, `test_check_mode_rejects_stale_timestamp[runtime]`,
`test_examples_have_no_api_base_leftovers`, `test_python_receiver_serves_200_and_verifies`); Modify `app/web/help.py`
(rejestr `WEBHOOK_EXAMPLES`). Sprawdzić, czy `tests/test_web_help.py` iteruje katalog przykładów.
**T6 API + OpenAPI** — Modify `app/api/routes.py`, `app/api/serializers.py`, `app/static/openapi.yaml`,
`tests/test_config_docs_fixes.py:97` (+ ścieżka). Create `tests/test_api_webhook_deliveries.py`:
`test_list_deliveries_scoped_to_key`, `test_list_filters_status_and_document_id`,
`test_list_pagination_cursor_newest_first`, `test_bad_status_and_cursor_400`,
`test_delivery_json_has_no_secret_and_times_in_api_format`, `test_openapi_has_webhook_schemas_and_deliveries_path`,
`test_openapi_matches_delivery_json_keys`.

## F2 (po F1)
**T3 wysyłka, ponowienia, worker, CLI** — Create `app/services/webhooks.py`, `tests/test_webhooks_delivery.py`
(odbiorca `ThreadingHTTPServer` jak `tests/test_help_examples_run.py:14-18`, `WEBHOOK_ALLOW_HTTP=1` +
allowlista `127.0.0.1` w teście), `tests/test_cli_webhooks.py`; Modify `app/__init__.py` (komendy). Testy:
`test_deliver_sends_signed_request_and_marks_sent`, `test_delivery_uuid_stable_across_retries`,
`test_server_error_schedules_backoff_sequence`, `test_sixth_failure_marks_failed_with_last_error_and_code`,
`test_redirect_302_is_failure_not_followed`, `test_timeout_is_failure`, `test_response_read_limited_to_1kb`,
`test_blocked_target_fails_without_connection`, `test_target_revalidated_at_send_time`,
`test_missing_url_or_inactive_key_marks_failed`, `test_claim_sets_lease_and_attempts`,
`test_claim_skips_rows_locked_by_other_connection` (needs_mariadb), `test_deliver_pending_sqlite_sequential`,
`test_send_now_and_retry_reset`, `test_prune_deliveries_only_sent_failed_older_than_days`,
`test_run_worker_stops_on_event_and_touches_heartbeat`, `test_webhooks_worker_once_delivers_and_exits_0`,
`test_prune_webhooks_cli_uses_config_default`. `db.session.remove()` po iteracji; `last_error` obcinane.
**T9 Pomoc** — Create `app/templates/help/webhooki.html`; Modify `app/help_content.py` (TOPICS po `integracja`;
FAQ `webhook-podpis`, `webhook-brak-dostawy`; „Jak podłączyć…” bez „(webhooków nie ma)”; podsumowanie l.27-29),
`help/integracja.html` (diagram, Sposób C, usunięcie alertu l.37-39, lista kontrolna, błędy),
`help/api.html:125-129`, `tests/test_web_help.py` (`test_webhooks_topic_listed_after_integration_and_linked`,
`test_webhooks_topic_shows_examples_in_four_languages_with_request_host`, `test_help_no_longer_says_webhooks_missing`,
`test_integration_has_way_c_with_link`, `test_faq_webhook_entries_anchored`; `HELP_SHOTS["webhooki"] =
["15-klucze-webhook.png"]`), eksport. Sprawdzić test sąsiadów/pagera tematów.

## F3 (po F2)
**T7 panel „Klucze API”** (buduje na v0.7.1) — Modify `app/web/apikeys.py` (trasy `POST /<id>/webhook`,
`/<id>/webhook/sekret`, `/<id>/webhook/test`, `/dostawy/<id>/ponow`; `_admin_or_403()`; audyt bez sekretu),
`app/services/apikeys.py`, `apikeys.html` (`<details>` per klucz: formularz adresu, „Wyczyść”, „Rotuj sekret”
z `data-confirm`, „Wyślij testowe zdarzenie”, alert „Sekret webhooka — Skopiuj teraz”, tabela 50 dostaw
`table-responsive` z `|dt` i „Ponów”), `tests/test_security_web.py`/`test_security_gaps.py` (CSRF nowych
formularzy). Create `tests/test_web_apikeys_webhook.py`: `test_set_webhook_url_generates_secret_shown_once`,
`test_set_webhook_url_rejects_private_target_with_flash`, `test_clear_webhook`,
`test_rotate_secret_changes_value_and_shows_once`, `test_test_event_sends_synchronously_and_lists_result`,
`test_test_event_failure_is_listed_not_500`, `test_retry_failed_delivery_resets_schedule`,
`test_deliveries_list_limited_to_50_newest`, `test_webhook_actions_require_admin_role`,
`test_webhook_forms_require_csrf`, `test_no_inline_handlers_on_apikeys_with_webhook`.
**T11 dokumentacja operacyjna** — Modify `README.md` (API: akapit + link `docs/pomoc/webhooki.md`; tabela env;
„Kopie zapasowe”: sekrety webhooków w zrzucie; usługa `worker` i `--once` z crona; `prune-webhooks`),
`docs/wdrozenie.md`, `docs/superpowers/plans/2026-10-11-api-integracja-naprawy.md` (Etap B → v0.9.0, uuid,
decyzje). Testy w `tests/test_config_docs_fixes.py`: `test_readme_env_table_lists_webhook_variables`,
`test_wdrozenie_mentions_worker_and_public_base_url`.

## F4 (sekwencyjnie)
**T10 zrzut `15-klucze-webhook`** — Modify `tools/screenshots.py` (po próbkach: klucz demo z adresem
`https://erp.example.com/webhooki/parser` zapisanym bez DNS — allowlista `erp.example.com` lub zapis pola
wprost; 3 wiersze `WebhookDelivery` sent/failed/pending; `Shot("15-klucze-webhook", "/klucze-api", True)`),
`tests/test_screenshots_tool.py`.
**T12 integracja i wydanie v0.9.0** — ruff, pytest z cov (z `TEST_MARIADB_URL`), export_help, strażnik; CHANGELOG
`[0.9.0]` z **`### Uwagi do aktualizacji`** (nowa migracja `webhook_deliveries` — CREATE TABLE, sekundy; nowa
usługa `worker` — bez niej dostawy czekają jako `pending`; nowe zmienne: `PUBLIC_BASE_URL` potrzebna do
`document_url`, `WEBHOOK_ALLOWED_HOSTS` dla tailnetu; sekrety webhooków jawnie w bazie i kopiach); bump 0.9.0;
pełna regeneracja 15 zrzutów; commit `chore(release): v0.9.0 — webhooki: outbox, worker, podpis HMAC, panel
i Pomoc` → tag → push → `gh release create`.

Kolejność: T0 → (T1‖T2‖T4‖T5‖T6) → (T3‖T9) → (T7‖T11) → T10 → T12.

### Kryteria akceptacji v0.9.0
- Każda zmiana statusu dokumentu klucza z webhookiem (API, panel, negocjacja, edytor, kaskady, odrzucenie,
  przywrócenie) → dokładnie 1 rekord `pending`; rollback → 0; dokument panelu/demo → 0.
- Dostawa: POST JSON z `X-XP-Timestamp`, `X-XP-Signature: sha256=…`, `X-XP-Delivery` (stałe); 2xx → `sent`;
  5xx/timeout/3xx/sieć → backoff 1m/5m/30m/2h/12h; 6. porażka → `failed`.
- Cel: tylko https (http z flagą); żadnego połączenia do adresów nie-globalnych bez allowlisty; DNS przy każdej
  wysyłce; bez redirectów; ≤1 KB; 5 s.
- Worker: startuje po healthy `app`, kończy na SIGTERM, heartbeat; `--once` działa; na MariaDB dwa workery nie
  wysyłają tego samego rekordu.
- Panel: admin ustawia adres/sekret (raz widoczny), test zdarzenia, lista 50 dostaw z „Ponów”, Historia bez
  sekretu, CSRF, brak `on*=`.
- API lista dostaw tylko własne, kursor, 401/400; OpenAPI z `WebhookEvent`; `/api/docs` renderuje.
- Pomoc bez „Webhooków nie ma”; temat `webhooki` z 4 przykładami przechodzącymi `--check`; eksport; Wiki.
- Migracja: jedna głowa, idempotentna na SQLite i MariaDB; `reset_demo` z dostawami. CI: ruff, cov ≥ 90 %,
  `pip-audit` bez nowych zależności.

### Wdrożenie v0.9.0 na demo (komendy dla użytkownika)
1. `tools/backup.sh` (zrzut zawiera sekrety webhooków — `backups/` traktować jak sekret).
2. `.env`: `PUBLIC_BASE_URL=https://<magicdns-host>:18506`, `WEBHOOK_ALLOWED_HOSTS=100.64.0.0/10`; opcjonalnie
   `WEBHOOK_ALLOW_HTTP=1` tylko na czas testu.
3. `git pull && docker compose up -d --build` → `docker compose logs -f worker` („webhooks-worker: start”).
4. Test: na maszynie w tailnecie `XP_WEBHOOK_SECRET=… python3 app/help_examples/webhook-odbiorca.py --port 9000`;
   w panelu klucz demo → adres → „Zapisz” → „Wyślij testowe zdarzenie” → `sent 200`; wgranie próbki kluczem →
   odbiorca loguje `document.status_changed`; `GET /api/v1/webhook-deliveries`.
5. `/healthz` 200, `docker compose ps` worker healthy; zdjąć `WEBHOOK_ALLOW_HTTP`, restart.

---

## Weryfikacja końcowa (po każdym wydaniu)
- `ruff check . && .venv/bin/python -m pytest -q` lokalnie; CI zielone na tagu (`gh run list`).
- `tools/export_help.py` bez diffu; `tests/test_help_export.py`, `test_docs_assets.py`, `test_screenshots_tool.py`,
  `test_no_private_data.py` zielone; zrzuty ze stopką w nowej wersji.
- `git log --oneline vPREV..vNEW` vs sekcja CHANGELOG — każda zmiana ma wpis.
- Wiki odświeżone (`gh run list --workflow wiki.yml`), GitHub Release z notami.
- Po wdrożeniu przez użytkownika: `/healthz` zwraca nową wersję; dla v0.9.0 dodatkowo `alembic_version` =
  nowa rewizja i `docker compose ps` pokazuje `worker`.
- Pamięć projektu (`project_xml_parser.md`) uzupełnić o status każdego wydania.
