"""Filtry Jinja panelu (dt/dts/money/qty/mib) i strefa wyświetlania DISPLAY_TZ."""
import logging
from datetime import datetime
from decimal import Decimal

from app.formatting import mib


def _render(app, tpl, **ctx):
    return app.jinja_env.from_string(tpl).render(**ctx)


def test_dt_converts_naive_utc_to_warsaw_winter_and_summer(app):
    winter = _render(app, "{{ v|dt }}", v=datetime(2026, 1, 15, 11, 30))
    summer = _render(app, "{{ v|dt }}", v=datetime(2026, 7, 15, 11, 30))
    assert ">15.01.2026 12:30<" in winter
    assert ">15.07.2026 13:30<" in summer


def test_dt_has_time_element_with_utc_and_tz_title(app):
    html = _render(app, "{{ v|dt }}", v=datetime(2026, 1, 15, 11, 30))
    assert html == ('<time datetime="2026-01-15T11:30:00Z" title="Czas lokalny Europe/Warsaw">'
                    '15.01.2026 12:30</time>')


def test_dts_includes_seconds(app):
    html = _render(app, "{{ v|dts }}", v=datetime(2026, 1, 15, 11, 30, 45))
    assert ">15.01.2026 12:30:45<" in html
    assert 'datetime="2026-01-15T11:30:45Z"' in html


def test_dt_none_is_dash(app):
    assert _render(app, "{{ v|dt }}", v=None) == "—"
    assert _render(app, "{{ v|dts }}", v=None) == "—"


def test_display_tz_configurable(app):
    app.config["DISPLAY_TZ"] = "America/New_York"
    html = _render(app, "{{ v|dt }}", v=datetime(2026, 1, 15, 11, 30))
    assert ">15.01.2026 06:30<" in html
    assert 'title="Czas lokalny America/New_York"' in html


def test_invalid_display_tz_falls_back_to_utc_with_warning(app, caplog):
    app.config["DISPLAY_TZ"] = "Mars/Olympus"
    with caplog.at_level(logging.WARNING):
        html = _render(app, "{{ v|dt }}", v=datetime(2026, 1, 15, 11, 30))
    assert ">15.01.2026 11:30<" in html
    assert 'title="Czas lokalny UTC"' in html
    assert "Mars/Olympus" in caplog.text


def test_money_polish_thousands_and_comma(app):
    assert _render(app, "{{ v|money }}", v=Decimal("1234.5")) == "1\xa0234,50"
    assert _render(app, "{{ v|money }}", v="1234567.891") == "1\xa0234\xa0567,89"
    assert _render(app, "{{ v|money }}", v=Decimal("-0.001")) == "0,00"
    assert _render(app, "{{ v|money }}", v=Decimal("12")) == "12,00"


def test_qty_strips_trailing_zeros_max_four_places(app):
    assert _render(app, "{{ v|qty }}", v=Decimal("1.5000")) == "1,5"
    assert _render(app, "{{ v|qty }}", v=Decimal("10.000")) == "10"
    assert _render(app, "{{ v|qty }}", v="0.123456") == "0,1235"
    assert _render(app, "{{ v|qty }}", v=Decimal("1234.5")) == "1\xa0234,5"


def test_money_qty_passthrough_for_non_numeric(app):
    assert _render(app, "{{ v|money }}", v="abc") == "abc"
    assert _render(app, "{{ v|qty }}", v="n/a") == "n/a"
    assert _render(app, "{{ v|money }}", v=None) == ""
    assert _render(app, "{{ v|qty }}", v=None) == ""
    assert _render(app, "{{ v|money }}", v="<b>") == "&lt;b&gt;"


def test_mib_filter(app):
    assert _render(app, "{{ v|mib }}", v=10 * 1024 * 1024) == str(mib(10 * 1024 * 1024)) == "10"


def test_filters_registered_in_jinja_env(app):
    for name in ("dt", "dts", "money", "qty", "mib"):
        assert name in app.jinja_env.filters


def test_zoneinfo_warsaw_available():
    from zoneinfo import ZoneInfo
    assert ZoneInfo("Europe/Warsaw").utcoffset(datetime(2026, 7, 1)).total_seconds() == 7200
