"""Shared fixtures. Tests use the fictional names of config/reference.example.yaml only."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dar.extract import Extractor  # noqa: E402
from dar.models import Message  # noqa: E402
from dar.normalize import Reference  # noqa: E402
from dar.settings import load_settings  # noqa: E402

DAY = date(2026, 8, 5)
DANA = "Dana Cohen"      # sender "דנה - עבודה"
AVI = "Avi Levi"         # sender "אבי לוי"
NOA = "Noa Bar"          # sender "נועה - עבודה - חברה"
GIL = "Gil Amir"
SENDERS = {DANA: "דנה - עבודה", AVI: "אבי לוי", NOA: "נועה - עבודה - חברה", GIL: "גיל אמיר"}


@pytest.fixture(scope="session")
def ref() -> Reference:
    return Reference.load(ROOT / "config" / "reference.example.yaml")


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture
def extractor(ref) -> Extractor:
    return Extractor(ref)


_counter = [0]


def msg(hhmm: str, who: str, text: str, day: date = DAY) -> Message:
    _counter[0] += 1
    h, m = map(int, hhmm.split(":"))
    return Message(f"t{_counter[0]}", datetime(day.year, day.month, day.day, h, m),
                   SENDERS.get(who, who), text, line_no=_counter[0])


def hm(minutes: int | None) -> str | None:
    return None if minutes is None else f"{minutes // 60:02d}:{minutes % 60:02d}"
