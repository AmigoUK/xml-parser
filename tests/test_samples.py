import csv
import io
import json
from pathlib import Path

from lxml import etree

SAMPLES = Path(__file__).resolve().parent.parent / "demo" / "samples"
EXPECTED = {"alfa-1.xml", "alfa-2.xml", "beta-ksef.xml", "gamma-ubl.xml", "delta.csv", "epsilon.json"}


def test_all_samples_present():
    assert EXPECTED <= {p.name for p in SAMPLES.iterdir()}


def test_xml_samples_well_formed():
    for name in ("alfa-1.xml", "alfa-2.xml", "beta-ksef.xml", "gamma-ubl.xml"):
        etree.fromstring((SAMPLES / name).read_bytes())


def test_json_and_csv_parse():
    json.loads((SAMPLES / "epsilon.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(io.StringIO((SAMPLES / "delta.csv").read_text(encoding="utf-8")), delimiter=";"))
    assert len(rows) == 2
