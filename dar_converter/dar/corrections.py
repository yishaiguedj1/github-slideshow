"""User / Claude corrections and the learning loop.

data/corrections.yaml (git-ignored):

    aliases:
      officers: {"דנוש": "Dana Cohen"}
      people:   {"רוני": "Ron Shani"}
    messages:                       # keyed by message id (see the review file)
      "20260812-1846-a1b2c3": {text: "42-45 אבי סרק נועה בדקה c2"}   # corrected text
      "20260809-1521-d4e5f6": {ignore: true}
      "20260819-1359-0a1b2c": {events: [{kind: check, start: "13:57", end: "13:58",
                                          zone: C1, actor: Noa Bar, subjects: [Tal Peretz]}]}
    roster:
      "2026-08-19":
        - {name: Dana Cohen, slot: 1}
        - {name: Noa Bar, slot: 3, end: "13:00"}
    holidays: ["2026-09-20"]

Learning: new aliases are merged into data/reference.yaml, and every corrected message is
stored in data/examples.jsonl with the events it produces - a regression set for the tests.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .models import HIGH, Event, Message
from .normalize import Reference

EVENT_KINDS = {"scan", "check", "escort_start", "escort_end", "escort_join", "escort_handover"}
ZONES = {"C1", "C2", "Office", "Storage", "TLV13", None}
_HHMM = re.compile(r"^\d{1,2}:\d{2}$")


@dataclass
class Corrections:
    officer_aliases: dict[str, str] = field(default_factory=dict)
    people_aliases: dict[str, str] = field(default_factory=dict)
    messages: dict[str, dict] = field(default_factory=dict)
    roster: dict[str, list[dict]] = field(default_factory=dict)
    holidays: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Corrections":
        p = Path(path)
        if not p.exists():
            return cls()
        with open(p, encoding="utf-8") as fh:
            d = yaml.safe_load(fh) or {}
        al = d.get("aliases") or {}
        return cls(officer_aliases={str(k): v for k, v in (al.get("officers") or {}).items()},
                   people_aliases={str(k): v for k, v in (al.get("people") or {}).items()},
                   messages={str(k): v for k, v in (d.get("messages") or {}).items()},
                   roster={str(k): v for k, v in (d.get("roster") or {}).items()},
                   holidays=[str(h) for h in d.get("holidays") or []])

    def roster_for(self, day: date) -> list[dict] | None:
        return self.roster.get(day.isoformat())


def event_problems(ev: dict, ref: Reference) -> list[str]:
    """Strict schema check for explicit events (same fields as config/event.schema.json)."""
    errs = []
    kind = ev.get("kind")
    if kind not in EVENT_KINDS:
        errs.append(f"kind לא חוקי: {kind}")
    for k in ("start", "end"):
        if ev.get(k) is not None and not _HHMM.match(str(ev[k])):
            errs.append(f"{k} צריך להיות HH:MM")
    if kind in ("scan", "check") and not ev.get("end"):
        errs.append("חסר end")
    if kind in ("scan", "escort_start", "escort_join") and not ev.get("start"):
        errs.append("חסר start")
    if ev.get("zone") not in ZONES:
        errs.append(f"zone לא חוקי: {ev.get('zone')}")
    for k in ("actor", "partner"):
        if ev.get(k) and not ref.is_officer(ev[k]):
            errs.append(f"{k} לא ברשימת המאבטחים: {ev[k]}")
    for sub in ev.get("subjects") or []:
        if not ref.is_officer(sub) and sub not in ref.people:
            errs.append(f"שם לא ברשימות: {sub}")
    unknown = set(ev) - {"kind", "start", "end", "zone", "actor", "partner", "subjects", "day"}
    if unknown:
        errs.append(f"שדות לא מוכרים: {sorted(unknown)}")
    return errs


def _minutes(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def explicit_events(msg: Message, specs: list[dict], ref: Reference) -> list[Event]:
    out = []
    for sp in specs:
        errs = event_problems(sp, ref)
        if errs:
            raise ValueError(f"תיקון להודעה {msg.id}: " + "; ".join(errs))
        start, end = _minutes(sp.get("start")), _minutes(sp.get("end"))
        if start is None:
            start = end
        if end is None and sp["kind"] != "escort_start":
            end = start
        day = date.fromisoformat(sp["day"]) if sp.get("day") else msg.ts.date()
        out.append(Event(sp["kind"], msg, f"[תיקון] {msg.text}", day=day, start=start, end=end,
                         zone=sp.get("zone"), actor=sp.get("actor"), partner=sp.get("partner"),
                         subjects=list(sp.get("subjects") or []), confidence=HIGH,
                         notes=["תוקן ידנית (corrections.yaml)"]))
    return out


def apply_to_messages(msgs: list[Message], corr: Corrections) -> list[Message]:
    """Text overrides and ignores. Explicit events are applied after extraction."""
    out = []
    for m in msgs:
        fix = corr.messages.get(m.id)
        if fix and fix.get("ignore"):
            continue
        if fix and fix.get("text"):
            m = Message(m.id, m.ts, m.sender, str(fix["text"]), m.system, m.edited, m.deleted,
                        m.line_no)
        out.append(m)
    return out


def learn(corr: Corrections, ref: Reference, reference_path: str | Path | None) -> list[str]:
    """Merge new aliases into the reference lists (persisted). Returns what was learned."""
    learned = []
    for alias, name in corr.officer_aliases.items():
        if ref.add_alias(alias, name, "officer"):
            learned.append(f"מאבטח: {alias} -> {name}")
    for alias, name in corr.people_aliases.items():
        kind = "officer" if ref.is_officer(name) else "person"
        if ref.add_alias(alias, name, kind):
            learned.append(f"שם: {alias} -> {name}")
    if learned and reference_path:
        ref.save(reference_path)
    return learned


def record_examples(path: str | Path, msgs: list[Message], events: list[Event],
                    corr: Corrections) -> int:
    """Append corrected messages and the events they now produce to examples.jsonl."""
    p = Path(path)
    known = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                known.add(json.loads(line)["id"])
    by_id = {m.id: m for m in msgs}
    new = 0
    with open(p, "a", encoding="utf-8") as fh:
        for mid, fix in corr.messages.items():
            if mid in known or mid not in by_id or fix.get("ignore"):
                continue
            m = by_id[mid]
            evs = [summarize(e) for e in events if e.msg.id == mid and e.kind not in ("chatter",)]
            fh.write(json.dumps({"id": mid, "ts": m.ts.isoformat(), "sender": m.sender,
                                 "text": m.text, "fix": fix, "expected": evs},
                                ensure_ascii=False) + "\n")
            new += 1
    return new


def summarize(e: Event) -> dict:
    def hhmm(x):
        return None if x is None else f"{x // 60:02d}:{x % 60:02d}"
    return {"kind": e.kind, "day": e.day.isoformat() if e.day else None, "start": hhmm(e.start),
            "end": hhmm(e.end), "zone": e.zone, "actor": e.actor, "partner": e.partner,
            "subjects": e.subjects}
