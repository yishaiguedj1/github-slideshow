"""Regression guard on the verified days. Runs only where the private data/ folder exists."""
from datetime import date

import pytest

from dar.corrections import Corrections
from dar.evaluate import evaluate, load_actual
from dar.normalize import Reference
from dar.parse import parse_file
from dar.pipeline import run
from dar.settings import load_settings

S = load_settings()
NEEDED = [S.path("chat"), S.path("template"), S.path("reference")]
pytestmark = pytest.mark.skipif(not all(p.exists() for p in NEEDED), reason="private data/ not present")

TEST_DAYS = [date(2026, 8, 16), date(2026, 8, 17), date(2026, 8, 19)]


def test_held_out_days_accuracy():
    msgs = parse_file(S.path("chat"))
    ref = Reference.load(S.path("reference"))
    rr = run(msgs, min(TEST_DAYS), max(TEST_DAYS), S, ref, Corrections())
    pred = {r.day: [x for x in r.rows if x.confidence >= 0.6] for r in rr.results}
    t = evaluate(pred, load_actual(S.path("template"), TEST_DAYS), TEST_DAYS).totals()
    assert t["recall"] >= 0.97 and t["precision"] >= 0.97
    assert t["exact_rows"] / t["actual_rows"] >= 0.85
    assert min(t["time_within_1min"].values()) >= 0.97
