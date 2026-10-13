"""End-to-end run over a date range. Sources and sinks are plain functions so a future
WhatsApp feed (WAHA -> SQLite) or a Google Sheets writer can be plugged in without changes here.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .build import Builder, DayResult
from .corrections import (Corrections, apply_to_messages, explicit_events, learn,
                          record_examples)
from .extract import extract_all
from .models import Event, Message
from .normalize import Reference
from .settings import Settings
from .validate import validate_day


@dataclass
class RunResult:
    results: list[DayResult]
    pending: list[Event]                 # lines the parser did not understand
    chatter: list[Event]                 # messages that are not reports
    messages: list[Message]
    learned: list[str] = field(default_factory=list)


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def run(messages: list[Message], start: date, end: date, settings: Settings, ref: Reference,
        corr: Corrections | None = None, reference_path: str | Path | None = None,
        examples_path: str | Path | None = None) -> RunResult:
    corr = corr or Corrections()
    if corr.holidays:
        settings = settings.with_overrides(
            {"day": {"holidays": sorted(set(settings.get("day.holidays", []) or []) | set(corr.holidays))}})
    learned = learn(corr, ref, reference_path)

    window = [m for m in messages if start - timedelta(days=1) <= m.ts.date() <= end + timedelta(days=1)]
    window = apply_to_messages(window, corr)
    events = extract_all(window, ref, int(settings.get("times.future_tolerance", 2)),
                         int(settings.get("times.scan_minutes", 3)))
    explicit_ids = {mid for mid, fix in corr.messages.items() if fix.get("events")}
    if explicit_ids:
        events = [e for e in events if e.msg.id not in explicit_ids]
        for m in window:
            if m.id in explicit_ids:
                events.extend(explicit_events(m, corr.messages[m.id]["events"], ref))
    if examples_path and corr.messages:
        record_examples(examples_path, window, events, corr)

    builder = Builder(ref, settings)
    results = []
    for d in daterange(start, end):
        res = builder.build_day(d, events, corr.roster_for(d))
        validate_day(res, settings, ref)
        results.append(res)

    in_range = [e for e in events if e.day and start <= e.day <= end]
    pending = [e for e in in_range if e.kind == "unknown"]
    chatter = [e for e in in_range if e.kind in ("chatter", "ignore")]
    return RunResult(results, pending, chatter, window, learned)


def messages_by_day(msgs: list[Message]) -> dict[date, list[Message]]:
    out = defaultdict(list)
    for m in msgs:
        out[m.ts.date()].append(m)
    return out
