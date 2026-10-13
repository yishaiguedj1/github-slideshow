"""Events of one day -> DAR rows.

Rules (learned from the manual entries, see config/settings.yaml):
  * scan "a-b X סרק Y בדק cZ"  -> Patrol(X) + Material Search(Y, "Metal screening cZ : X")
  * the two zones of one round are contiguous (C1 starts where C2 ended)
  * a solo scan followed within a few minutes by a check of the scanner -> one pair
  * check "בדיקה ל<P> cZ"        -> Material Search(sender, "Metal screening cZ : P")
  * escort: one row per escorted person and location segment; it ends at an explicit
    end, at the person's exit check in that zone, or at a hand-over / location change
  * Assumed Post 07:00-19:00 for each officer on duty (split posts 07-13 / 13-19)
  * F = start, G = end, D = F - 60s, E = F - 30s
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .models import (ASSUMED_POST, ESCORT, HIGH, LOW, MEDIUM, PATROL, SEARCH, Event, Issue,
                     Message, Row, fmt_minutes)
from .normalize import Reference
from .settings import Settings, hhmm

ZONES = ("C1", "C2")


@dataclass
class RosterEntry:
    officer: str
    slot: int
    start: int
    end: int
    inferred: bool = False
    note: str = ""


@dataclass
class DayResult:
    day: date
    rows: list[Row] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    roster: list[RosterEntry] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


def _tkey(e: Event) -> tuple:
    t = e.start if e.start is not None else (e.end if e.end is not None else
                                              e.msg.ts.hour * 60 + e.msg.ts.minute)
    return (t, e.msg.ts, e.msg.line_no)


class Builder:
    def __init__(self, ref: Reference, settings: Settings):
        self.ref = ref
        self.s = settings
        self._seq = 0
        self._segments: list[dict] = []

    # ================================================================ public
    def build_day(self, day: date, events: list[Event],
                  roster_override: list[dict] | None = None) -> DayResult:
        res = DayResult(day)
        evs = sorted([e for e in events if e.day == day], key=_tkey)
        res.events = evs
        for e in evs:
            e.used = False
        self._dedupe(evs, res)
        self._resolve_namesakes(evs)
        self._resolve_scan_starts(evs, res)
        if int(self.s.get("rules.merge_scan_and_check_gap", 0)) > 0:
            self._merge_scan_and_check(evs)
        self._zone_from_pair(evs)
        self._join_zone_pairs(evs)
        self._infer_missing_zone(evs, res)
        rows: list[Row] = []
        self._segments = self._escort_segments(evs, res)
        rows += self._scan_rows(evs, res)
        rows += self._check_rows(evs, res)
        rows += self._escort_rows(self._segments)
        self._mark_missing_zone(evs, rows)
        roster = self._roster(day, evs, res, roster_override)
        res.roster = roster
        rows += self._assumed_post_rows(day, roster)
        self._assign_shifts(rows, roster, res)
        self._apply_busy_checker(rows)
        for r in rows:
            self._finish_times(r)
        fix_below = float(self.s.get("review.fix_below", 0.6))
        for r in rows:
            if r.confidence < fix_below:
                for f in r.flags:
                    r.need_fix(f)
        rows.sort(key=lambda r: (0 if r.action == ASSUMED_POST else 1,
                                 r.d_e_f[0] if r.d_e_f and r.d_e_f[0] is not None else 10 ** 9,
                                 r.seq))
        res.rows = rows
        return res

    # ================================================================ helpers
    def _row(self, day, action, officer, start, end, comment, sources, conf=HIGH) -> Row:
        self._seq += 1
        uniq = list({m.id: m for m in sources}.values())
        return Row(day=day, action=action, officer=officer, start=start, end=end,
                   comment=comment, sources=uniq, confidence=conf, seq=self._seq)

    @staticmethod
    def _carry(row: Row, *events: Event) -> Row:
        for e in events:
            for n in e.notes:
                row.flag(n)
            for n in e.info:
                if n not in row.info:
                    row.info.append(n)
            row.confidence = min(row.confidence, e.confidence)
        return row

    # ---------------------------------------------------------------- dedupe
    def _dedupe(self, evs: list[Event], res: DayResult) -> None:
        """Two officers often report the same scan / check / escort."""
        def close(a, b, tol=1):
            return a is not None and b is not None and abs(a - b) <= tol

        for i, a in enumerate(evs):
            if a.used:
                continue
            for b in evs[i + 1:]:
                if b.used or b.kind != a.kind:
                    continue
                same = False
                if a.kind == "scan":
                    same = (a.actor == b.actor and a.zone == b.zone and close(a.start, b.start)
                            and close(a.end, b.end))
                    if same and not a.partner and b.partner:
                        a.partner = b.partner
                elif a.kind == "check":
                    same = (set(a.subjects) == set(b.subjects) and a.zone == b.zone
                            and close(a.end, b.end) and (a.actor == b.actor or b.actor is None))
                elif a.kind in ("escort_start", "escort_end", "scan_start"):
                    same = (set(a.subjects) == set(b.subjects) and a.zone == b.zone
                            and close(a.start, b.start, 2) and a.actor == b.actor)
                if same:
                    b.used = True
                    b.note("כפילות של דיווח קודם")

    # ---------------------------------------------------------------- namesakes
    def _resolve_namesakes(self, evs: list[Event]) -> None:
        """A checked / escorted name shared by an officer and another person (e.g. "גיל").

        Officers are never escorted, so in escort lines the name is the other person.
        In a check:
          - the officer never checks himself -> the other person;
          - an escorted visitor namesake is meant only while that visitor is being escorted;
          - an employee namesake (no escort) is meant unless the check belongs to the officer's
            own work: right after his own scan in that zone, or an escort hand-over in the same
            message. The employee is checked only a few times a day, entering C1 / C2.
        """
        handover_msgs = {e.msg.id for e in evs if e.kind in ("escort_handover", "escort_end")}
        escort_kinds = ("escort_start", "escort_end", "escort_join", "escort_handover", "escort_move")

        def person_namesake(subj: str) -> str | None:
            if not self.ref.is_officer(subj):
                return None
            others = [n for n, kind in self.ref.namesakes(subj) if kind == "person"]
            return others[0] if others else None

        for e in evs:                                   # pass 1: escort lines
            if e.kind in escort_kinds and not e.used:
                new = []
                for subj in e.subjects:
                    p = person_namesake(subj)
                    if p:
                        e.info.append(f"'{subj}' בליווי זוהה כ-{p}")
                    new.append(p or subj)
                e.subjects = new

        for e in evs:                                   # pass 2: checks
            if e.kind != "check" or e.used:
                continue
            new = []
            for subj in e.subjects:
                p = person_namesake(subj)
                if not p:
                    new.append(subj)
                    continue
                t = e.start if e.start is not None else e.end
                if e.actor == subj:
                    pick = p
                elif self.ref.needs_escort(p):
                    escorted = any(x.kind in escort_kinds and p in x.subjects and x.start is not None
                                   and t is not None and 0 <= t - x.start <= 240 for x in evs)
                    pick = p if escorted else subj
                else:
                    after_own_scan = any(x.kind == "scan" and x.actor == subj and x.end is not None
                                         and x.zone in (e.zone, None) and t is not None
                                         and 0 <= t - x.end <= 5 for x in evs)
                    pick = subj if (after_own_scan or e.msg.id in handover_msgs) else p
                if pick != subj:
                    e.info.append(f"'{subj}' זוהה כ-{pick} לפי ההקשר")
                new.append(pick)
            e.subjects = new

    # ---------------------------------------------------------------- scan starts
    def _resolve_scan_starts(self, evs: list[Event], res: DayResult) -> None:
        scans = [e for e in evs if e.kind == "scan" and not e.used]
        checks = [e for e in evs if e.kind == "check" and not e.used]
        for st in [e for e in evs if e.kind == "scan_start" and not e.used]:
            st.used = True
            if any(s.actor == st.actor and (st.zone is None or s.zone in (st.zone, None))
                   and s.start is not None and abs(s.start - st.start) <= 2 for s in scans):
                continue                                   # the full report came later
            # "42 תחילת סריקה דנה c2" with no full report: the scan gets the average
            # length; a later "48 בדיקה לדנה" stays a separate Material Search row
            minutes = int(self.s.get("times.scan_minutes", 3))
            evs.append(Event("scan", st.msg, st.line, day=st.day, start=st.start,
                             end=st.start + minutes, zone=st.zone, actor=st.actor,
                             confidence=min(st.confidence, MEDIUM),
                             notes=st.notes + [f"דווחה רק תחילת סריקה - משך ממוצע {minutes} דק'"]))
        evs.sort(key=_tkey)

    # ---------------------------------------------------------------- solo scan + check
    def _merge_scan_and_check(self, evs: list[Event]) -> None:
        gap = int(self.s.get("rules.merge_scan_and_check_gap", 3))
        for sc in [e for e in evs if e.kind == "scan" and not e.used and not e.partner
                   and e.end is not None]:
            for c in [e for e in evs if e.kind == "check" and not e.used and sc.actor in e.subjects
                      and len(e.subjects) == 1 and e.zone in (sc.zone, None) and e.end is not None]:
                c_start = c.start if c.start is not None else c.end - 1
                if not (0 <= c_start - sc.end <= gap):
                    continue
                busy = any(o for o in evs if o is not c and o.kind == "check" and not o.used
                           and o.actor == c.actor and o.end is not None
                           and sc.end <= o.end <= c_start)
                if busy:
                    continue
                sc.partner = c.actor
                sc.end = c.end
                sc.info.append("סריקה ובדיקה שדווחו בנפרד אוחדו לזוג")
                sc.extra_sources.append(c.msg)
                c.used = True
                break

    # ---------------------------------------------------------------- zone pairs
    def _zone_from_pair(self, evs: list[Event]) -> None:
        """'17-20-c1-גיל סרק...' + '20-23-גיל סרק...' -> the second one is C2.

        Also "42-45 ... C2" followed right away by "45-48 ... C2" by the same pair: a round
        always covers both zones, so the second one is C1 (typo in the chat).
        """
        gap = int(self.s.get("rules.join_max_gap", 3))
        scans = [e for e in evs if e.kind == "scan" and not e.used and e.start is not None
                 and e.end is not None]
        scans.sort(key=lambda e: e.start)
        for a, b in zip(scans, scans[1:]):
            if a.zone in ZONES and a.zone == b.zone and a.actor == b.actor and a.partner == b.partner \
                    and a.partner and 0 <= b.start - a.end <= gap:
                other = "C1" if a.zone == "C2" else "C2"
                b.note(f"שתי סריקות {a.zone} ברצף - השנייה נרשמה כ-{other}", MEDIUM)
                b.zone = other
        for e in [x for x in scans if x.zone is None]:
            for o in scans:
                if o is e or o.zone not in ZONES or o.actor != e.actor or o.partner != e.partner:
                    continue
                if 0 <= e.start - o.end <= gap or 0 <= o.start - e.end <= gap:
                    e.zone = "C1" if o.zone == "C2" else "C2"
                    e.note(f"האזור ({e.zone}) הוסק מהסריקה הצמודה ({o.zone})", MEDIUM)
                    break

    def _join_zone_pairs(self, evs: list[Event]) -> None:
        if not self.s.get("rules.join_zone_pairs", True):
            return
        gap = int(self.s.get("rules.join_max_gap", 3))
        mode = self.s.get("rules.join_mode", "c1_starts_at_c2_end")
        scans = sorted([e for e in evs if e.kind == "scan" and not e.used
                        and e.start is not None and e.end is not None], key=lambda e: e.start)
        for i, a in enumerate(scans):
            for b in scans[i + 1:]:
                if b.actor != a.actor or b.partner != a.partner:
                    continue
                if {a.zone, b.zone} != set(ZONES):
                    continue
                d = b.start - a.end
                if 0 < d <= gap:
                    if mode == "c1_starts_at_c2_end" or (mode == "auto" and d == 1):
                        b.start = a.end
                    elif mode == "c2_ends_at_c1_start":
                        a.end = b.start
                    elif mode == "auto":
                        a.end = b.start = a.end + 1
                    b.info.append(f"שני האזורים הוצמדו (פער של {d} דק')")
                break

    def _infer_missing_zone(self, evs: list[Event], res: DayResult) -> None:
        if not self.s.get("rules.infer_missing_zone", False):
            return
        minutes = int(self.s.get("rules.infer_missing_zone_minutes", 3))
        scans = [e for e in evs if e.kind == "scan" and not e.used and e.partner
                 and e.zone in ZONES and e.end is not None]
        for a in scans:
            other = "C1" if a.zone == "C2" else "C2"
            if any(b.actor == a.actor and b.zone == other and b.start is not None
                   and abs(b.start - a.end) <= 15 for b in scans):
                continue
            evs.append(Event("scan", a.msg, a.line, day=a.day, start=a.end, end=a.end + minutes,
                             zone=other, actor=a.actor, partner=a.partner, confidence=MEDIUM,
                             notes=[f"{other} לא דווח - נוסף לפי ההגדרה infer_missing_zone"],
                             inferred=True))

    def _mark_missing_zone(self, evs: list[Event], rows: list[Row]) -> None:
        """A checked scan of one zone with no scan of the other zone around it."""
        scans = [e for e in evs if e.kind == "scan" and not e.used and e.zone in ZONES
                 and e.start is not None and e.end is not None]
        for a in scans:
            if not a.partner:
                continue
            other = "C1" if a.zone == "C2" else "C2"
            people = {a.actor, a.partner}
            # the other zone may be covered by another officer (e.g. the one escorting in C1)
            if any(b.zone == other and (abs(b.start - a.end) <= 15 or abs(a.start - b.end) <= 15)
                   for b in scans):
                continue
            for r in rows:
                if r.action in (PATROL, SEARCH) and r.start == a.start and r.end == a.end \
                        and r.officer in people and a.msg in r.sources:
                    r.need_fix(f"דווח רק {a.zone} - אם נסרק גם {other}, להוסיף שורות")

    # ---------------------------------------------------------------- rows: scans
    def _scan_rows(self, evs: list[Event], res: DayResult) -> list[Row]:
        rows = []
        for e in sorted([e for e in evs if e.kind == "scan" and not e.used], key=_tkey):
            srcs = [e.msg] + e.extra_sources
            p = self._row(e.day, PATROL, e.actor, e.start, e.end, "Routine Patrol", srcs)
            self._carry(p, e)
            p.inferred = e.inferred
            if e.actor is None or str(e.actor).startswith("?"):
                p.officer = None
                p.flag("לא ברור מי סרק", LOW)
            rows.append(p)
            if e.partner:
                subj = e.actor if e.actor and not str(e.actor).startswith("?") else None
                comment = self._ms_comment(e.zone, subj)
                ms = self._row(e.day, SEARCH, e.partner, e.start, e.end, comment, srcs)
                self._carry(ms, e)
                ms.inferred = p.inferred
                if str(e.partner).startswith("?"):
                    ms.officer = None
                    ms.flag("לא ברור מי בדק", LOW)
                if comment is None:
                    ms.flag("אזור או נבדק לא ידועים - ההערה נשארה ריקה", LOW)
                rows.append(ms)
        return rows

    @staticmethod
    def _ms_comment(zone: str | None, subject: str | None) -> str | None:
        if zone not in ZONES or not subject:
            return None
        return f"Metal screening {zone} : {subject} - Declined to sit"

    # ---------------------------------------------------------------- rows: checks
    def _check_rows(self, evs: list[Event], res: DayResult) -> list[Row]:
        rows = []
        for c in sorted([e for e in evs if e.kind == "check" and not e.used], key=_tkey):
            subjects = c.subjects or [None]
            for i, subj in enumerate(subjects):
                zone = c.zone
                row_notes = []
                if zone is None and subj:
                    zone, how = self._zone_from_context(subj, c, evs)
                    if zone:
                        row_notes.append(how)
                name = subj if subj and not subj.startswith("?") else None
                if subj and subj.startswith("?"):
                    row_notes.append(f"!שם לא מוכר: {subj[1:]}")
                start = c.start if c.start is not None else (c.end - 1 if c.end is not None else None)
                end = c.end
                if len(subjects) > 1 and start is not None and end is not None:
                    # "45 בדיקה לרון, טל c2" -> 44-45, 45-46: one person after the other
                    span = end - start
                    step = max(1, span // len(subjects))
                    start = start + i * step
                    end = end if (i == len(subjects) - 1 and span >= len(subjects)) else start + step
                elif c.single_time and end is not None and self.ref.needs_escort(name):
                    start = end - int(self.s.get("times.check_minutes_contractor", 1))
                r = self._row(c.day, SEARCH, c.actor, start, end, self._ms_comment(zone, name),
                              [c.msg])
                self._carry(r, c)
                for n in row_notes:
                    if n.startswith("!"):
                        r.flag(n[1:], LOW)
                    else:
                        r.flag(n, MEDIUM)
                if r.comment is None:
                    r.flag("אזור או נבדק לא ידועים - ההערה נשארה ריקה", LOW)
                rows.append(r)
        return rows

    def _zone_from_context(self, subject: str, c: Event, evs: list[Event]) -> tuple[str | None, str]:
        t = c.end if c.end is not None else 0
        for seg in self._segments:
            s0, s1 = seg["start"], seg["end"]
            if seg["loc"] in ZONES and s0 is not None and s0 <= t and (s1 is None or t <= s1 + 1):
                if seg["officer"] == subject:
                    return seg["loc"], f"האזור ({seg['loc']}) נלקח מהליווי שהנבדק ביצע"
                if seg["person"] == subject:
                    return seg["loc"], f"האזור ({seg['loc']}) נלקח מהליווי של הנבדק"
        scans = [e for e in evs if e.kind == "scan" and e.actor == subject and e.zone in ZONES
                 and e.end is not None and 0 <= t - e.end <= 30]
        if scans:
            z = max(scans, key=lambda e: e.end).zone
            return z, f"האזור ({z}) נלקח מהסריקה האחרונה של הנבדק"
        esc = [e for e in evs if e.kind in ("escort_start", "escort_join", "escort_handover", "escort_move")
               and subject in e.subjects and e.zone in ZONES and e.start is not None and e.start <= t]
        if esc:
            z = max(esc, key=lambda e: e.start).zone
            return z, f"האזור ({z}) נלקח מהליווי של הנבדק"
        return None, ""

    # ---------------------------------------------------------------- rows: escorts
    def _escort_segments(self, evs: list[Event], res: DayResult) -> list[dict]:
        """Escort intervals per escorted person: [{person, officer, loc, start, end, ...}]."""
        kinds = ("escort_start", "escort_join", "escort_handover", "escort_move", "escort_end")
        stream = [e for e in evs if (e.kind in kinds and not e.used) or e.kind == "check"]
        stream.sort(key=lambda e: ((e.start if e.kind != "check" else e.end) or 0,
                                   e.msg.ts, e.msg.line_no))
        open_: dict[str, dict] = {}
        segments: list[dict] = []
        closed_by_msg: set[tuple[str, str]] = set()   # (person, message id) closed by a check

        def start(p: str, ev: Event, t: int, loc: str | None, handover: bool = False):
            info = []
            if loc is None and self.ref.default_location(p):
                loc = self.ref.default_location(p)
                info.append(f"מיקום ברירת מחדל של {p}: {loc}")
            open_[p] = {"person": p, "officer": ev.actor, "loc": loc, "start": t, "end": None,
                        "events": [ev], "notes": [], "info": info, "handover": handover}

        def close(p: str, t: int | None):
            seg = open_.pop(p)
            seg["end"] = t
            segments.append(seg)

        for ev in stream:
            if ev.kind == "check":
                for p in ev.subjects:
                    o = open_.get(p)
                    if not o or ev.end is None or ev.end < o["start"]:
                        continue
                    if o["loc"] in ZONES and ev.zone in ZONES and o["loc"] != ev.zone:
                        o["exit_elsewhere"] = ev               # checked out in the other zone
                    if o["loc"] in (None, ev.zone) or ev.zone is None:
                        if o["loc"] is None and ev.zone:
                            o["loc"] = ev.zone
                            o["notes"].append(f"מיקום הליווי ({ev.zone}) נלקח מבדיקת היציאה")
                        o["events"].append(ev)
                        close(p, ev.end)
                        closed_by_msg.add((p, ev.msg.id))
                continue
            t = ev.start
            if "*" in ev.subjects:                   # "כולם": every open escort (of this place)
                ev.subjects = [p for p, o in open_.items()
                               if ev.kind != "escort_end" or ev.zone in (None, o["loc"])]
                if ev.kind in ("escort_start", "escort_join"):
                    ev.kind = "escort_move"
                if not ev.subjects:
                    res.issues.append(Issue(ev.day, "all_without_escort",
                                            "'כולם' בלי ליווי פתוח", sources=[ev.msg]))
                    continue
            if ev.kind in ("escort_start", "escort_join"):
                for p in ev.subjects:
                    if p in open_:
                        close(p, t)
                    start(p, ev, t, ev.zone)
            elif ev.kind == "escort_handover":
                targets = [p for p in ev.subjects if p in open_] or \
                          [p for p, o in open_.items() if ev.zone in (None, o["loc"])
                           and o["officer"] != ev.actor]
                for p in ev.subjects:
                    if p not in open_ and p not in targets:
                        # "47 המשך ליווי רון c1" after his exit check: the escort starts again
                        start(p, ev, t, ev.zone)
                if not targets and not ev.subjects:
                    res.issues.append(Issue(ev.day, "handover_without_escort",
                                            "החלפת ליווי בלי ליווי פתוח", sources=[ev.msg]))
                for p in targets:
                    loc = open_[p]["loc"] if p in open_ else ev.zone
                    if p in open_:
                        open_[p]["events"].append(ev)
                        close(p, t)
                    start(p, ev, t, ev.zone or loc, handover=True)
                    if not ev.subjects:
                        open_[p]["notes"].append("המלווה בהחלפה נקבע לפי הליווי הפתוח")
            elif ev.kind == "escort_move":
                # "32 עוברים לליווי ב C2": the open escort(s) continue in another place
                targets = [p for p in ev.subjects if p in open_] or \
                          [p for p, o in open_.items() if o["officer"] == ev.actor] or \
                          (list(open_) if len(open_) == 1 else [])
                if not targets:
                    res.issues.append(Issue(ev.day, "move_without_escort",
                                            "מעבר מקום בלי ליווי פתוח", sources=[ev.msg]))
                for p in targets:
                    if t is None or open_[p]["loc"] == ev.zone or ev.zone is None:
                        continue
                    officer = open_[p]["officer"]
                    open_[p]["events"].append(ev)
                    close(p, t)
                    start(p, ev, t, ev.zone)
                    open_[p]["officer"] = ev.actor or officer
            elif ev.kind == "escort_end":
                targets = [p for p in ev.subjects if p in open_]
                if not ev.subjects:
                    cands = [p for p, o in open_.items()
                             if (ev.zone is None or o["loc"] in (ev.zone, None))]
                    mine = [p for p in cands if open_[p]["officer"] == ev.actor]
                    pool = mine or cands
                    if pool:
                        latest = max(open_[p]["start"] for p in pool)
                        targets = [p for p in pool if open_[p]["start"] == latest]
                        if not mine:
                            for p in targets:
                                open_[p]["notes"].append("סיום ליווי בלי שם - שויך לליווי הפתוח האחרון")
                missing = [p for p in ev.subjects if p not in open_
                           and (p, ev.msg.id) not in closed_by_msg]
                for p in missing:
                    res.issues.append(Issue(ev.day, "end_without_start",
                                            f"סיום ליווי בלי תחילה: {p}", sources=[ev.msg]))
                if not targets and not missing and not ev.subjects:
                    res.issues.append(Issue(ev.day, "end_without_start",
                                            "סיום ליווי בלי ליווי פתוח", sources=[ev.msg]))
                for p in targets:
                    open_[p]["events"].append(ev)
                    if open_[p]["loc"] is None and ev.zone:
                        open_[p]["loc"] = ev.zone
                        open_[p]["notes"].append(f"מיקום הליווי ({ev.zone}) נלקח מהודעת הסיום")
                    close(p, ev.end if ev.end is not None else t)
        for p in list(open_):
            # no end reported: the last check of the person in the other zone ends it
            # ("21 ליווי רון c2" ... "33-35-c1-בדיקה רון" -> 12:21-12:35)
            last = open_[p].get("exit_elsewhere")
            if last is not None:
                open_[p]["events"].append(last)
                open_[p]["notes"].append(f"הליווי הסתיים בבדיקת היציאה ב-{last.zone}")
                close(p, last.end)
            else:
                close(p, None)

        # a hand-over continues in the same place: copy the location back to the
        # earlier segment ("16 תחילת ליווי רון" ... "המשך ליווי רון" ... "23 בדיקה לרון c1")
        by_person: dict[str, list[dict]] = defaultdict(list)
        for seg in segments:
            by_person[seg["person"]].append(seg)
        for segs in by_person.values():
            segs.sort(key=lambda x: x["start"] if x["start"] is not None else 0)
            for a, b in reversed(list(zip(segs, segs[1:]))):
                if a["loc"] is None and b["loc"] and b["handover"] and a["end"] == b["start"]:
                    a["loc"] = b["loc"]
                    a["notes"].append(f"מיקום הליווי ({b['loc']}) נלקח מהמשך הליווי")
        return segments

    def _escort_rows(self, segments: list[dict]) -> list[Row]:
        rows = []
        for seg in sorted(segments, key=lambda x: (x["start"] or 0, x["events"][0].msg.ts)):
            p, loc, s, e = seg["person"], seg["loc"], seg["start"], seg["end"]
            if s is not None and e is not None and e <= s:
                s = e - int(self.s.get("times.single_minute", 1))   # "06 תחילת ליווי ... 06 סיום"
            name = None if p.startswith("?") else p
            comment = f"Escort {loc} : {name}" if loc and name else None
            r = self._row(seg["events"][0].day, ESCORT, seg["officer"], s, e, comment,
                          [x.msg for x in seg["events"]])
            if name is None:
                r.flag(f"שם לא מוכר: {p[1:]} - להוסיף לרשימת השמות", LOW)
            elif self.ref.needs_escort(name) is False:
                r.flag(f"{name} לא צריך ליווי - לבדוק את ההודעה", LOW)
            self._carry(r, *[x for x in seg["events"] if x.kind != "check"])
            for n in seg["notes"]:
                r.flag(n, MEDIUM)
            r.info.extend(seg["info"])
            if comment is None:
                r.flag("מיקום או שם המלווה לא ידועים - ההערה נשארה ריקה", LOW)
            if e is None:
                r.flag("לא נמצא סיום ליווי - שעת הסיום נשארה ריקה", MEDIUM)
            rows.append(r)
        return rows

    # ---------------------------------------------------------------- roster
    def _roster(self, day: date, evs: list[Event], res: DayResult,
                override: list[dict] | None) -> list[RosterEntry]:
        day_start, day_end = self.s.day_bounds(day)
        split = hhmm(self.s.get("day.split_at", "13:00"))
        if override:
            out = []
            for o in override:
                out.append(RosterEntry(o["name"], int(o.get("slot", 0)),
                                       hhmm(o["start"]) if o.get("start") else day_start,
                                       hhmm(o["end"]) if o.get("end") else day_end))
            return out

        # presence = officers who report or act (scan / check / escort); being only the
        # subject of a check is not enough (it may be a namesake visitor)
        span: dict[str, list[int]] = {}
        scans: dict[str, int] = defaultdict(int)
        for e in evs:
            if e.kind in ("unknown", "chatter", "ignore", "storage") or (e.used and e.kind != "scan_start"):
                continue
            t0 = e.start if e.start is not None else e.end
            t1 = e.end if e.end is not None else e.start
            if t0 is None:
                continue
            for o in (e.actor, e.partner):
                if o and self.ref.is_officer(o):
                    sp = span.setdefault(o, [t0, t1])
                    sp[0], sp[1] = min(sp[0], t0), max(sp[1], t1)
                    if e.kind == "scan":
                        scans[o] += 1
        officers = sorted(span, key=self.ref.priority)
        default_sup = self.s.get("roster.default_supervisor")
        if default_sup == "auto":
            default_sup = self.ref.default_supervisor()
        if not officers and not default_sup:
            return []

        # working hours = the hours of the officer's own reports (07-13 / 13-19 / full day)
        def hours(o: str) -> tuple[int, int]:
            if o not in span or not day_start < split < day_end or day_end - day_start < 9 * 60:
                return day_start, day_end                  # short day (holiday eve): no split
            first, last = span[o]
            if first >= split - 45:
                return split, day_end                      # arrived at 13:00
            if last <= split + 45:
                return day_start, split                    # left at 13:00
            return day_start, day_end

        hrs = {o: hours(o) for o in officers}
        morning, afternoon, full = (day_start, split), (split, day_end), (day_start, day_end)
        guard_like = int(self.s.get("roster.supervisor_max_scans", 11))

        # Shift 1 = the supervisor. He hardly reports, so his day is 07-19, except when a
        # second supervisor only arrives at 13:00 and the first one has no reports after
        # 13:00 - then they split Shift 1. A supervisor who scans like a guard all day is a
        # guard that day; if no supervisor is seen, the configured default one is assumed.
        roster: list[RosterEntry] = []
        taken: set[str] = set()
        sups = [o for o in officers if self.ref.is_supervisor(o) and scans[o] <= guard_like
                or (self.ref.is_supervisor(o) and self.ref.priority(o) == 1)]
        sup = sups[0] if sups else None
        if sup is None and default_sup:
            sup = default_sup
            roster.append(RosterEntry(sup, 1, day_start, day_end, True,
                                      "המפקח לא מופיע בצ'אט היום - נרשם לפי ברירת המחדל"))
            taken.add(sup)
        elif sup is None:
            res.issues.append(Issue(day, "no_supervisor",
                                    "לא זוהה מפקח (Shift 1) בצ'אט - להוסיף ידנית את שורת ה-Assumed Post שלו"))
        else:
            late = [o for o in officers if o != sup and self.ref.is_supervisor(o)
                    and hrs[o] == afternoon and scans[o] <= guard_like
                    and (sup not in span or span[sup][1] <= split)]
            if late:
                roster.append(RosterEntry(sup, 1, day_start, split, True, "המפקח סיים ב-13:00"))
                roster.append(RosterEntry(late[0], 1, split, day_end, True,
                                          "מפקח אחר הצהריים (13:00-19:00)"))
                taken |= {sup, late[0]}
            else:
                roster.append(RosterEntry(sup, 1, day_start, day_end))
                taken.add(sup)

        others = [o for o in officers if o not in taken]
        # The supervisor left at noon (no reports of his after 13:00) while a supervisor-type
        # guard stopped scanning at noon and a new guard arrived: that guard took over the
        # supervision for the afternoon and stays on the full day; the newcomer is an extra.
        sup1 = next((r for r in roster if r.slot == 1), None)
        if sup1 and len([r for r in roster if r.slot == 1]) == 1 and \
                (sup1.officer not in span or span[sup1.officer][1] <= split):
            acting = [o for o in others if self.ref.is_supervisor(o) and hrs[o] == morning]
            newcomers = [o for o in others if hrs[o] == afternoon]
            if acting and newcomers:
                sup1.end, sup1.inferred = split, True
                sup1.note = "המפקח סיים ב-13:00 והמאבטח-מפקח המשיך עד הערב"
                hrs[acting[0]] = full
        # full-day officers by priority, then posts shared by a morning + an afternoon officer
        used: set[str] = set()
        pairs: list[list[str]] = []
        for a in [o for o in others if hrs[o] == morning]:
            b = next((x for x in others if x not in used and x != a and hrs[x] == afternoon), None)
            if b:
                pairs.append([a, b])
                used |= {a, b}
            elif self.ref.is_supervisor(a):
                hrs[a] = full          # a supervisor-type officer who stops scanning at noon
        fulls = sorted([[o] for o in others if o not in used and hrs[o] == full],
                       key=lambda g: self.ref.priority(g[0]))
        used |= {g[0] for g in fulls}
        rest = [[o] for o in others if o not in used]
        ordered = fulls + pairs + rest
        for i, g in enumerate(ordered):
            slot = 2 + i
            if slot > 3:
                if all(hrs[o] != full for o in g):
                    slot = 3                                # a partial post shares the last slot
                else:
                    res.issues.append(Issue(day, "roster",
                                            "יותר מאבטחים מעמדות - לבדוק את ה-Shift של: " + ", ".join(g)))
            for o in sorted(g, key=lambda o: hrs[o][0]):
                a, b = hrs[o]
                partial = (a, b) != full
                roster.append(RosterEntry(o, slot, a, b, partial,
                                          "שעות העבודה הוסקו מהסריקות והבדיקות בצ'אט" if partial else ""))
        return roster

    def _assumed_post_rows(self, day: date, roster: list[RosterEntry]) -> list[Row]:
        rows = []
        for r in sorted(roster, key=lambda r: (r.start, r.slot)):
            row = self._row(day, ASSUMED_POST, r.officer, r.start, r.end, None, [])
            if r.inferred:
                row.flag(r.note or "שעות העמדה הוסקו", MEDIUM)
            rows.append(row)
        return rows

    def _assign_shifts(self, rows: list[Row], roster: list[RosterEntry], res: DayResult) -> None:
        slot = {}
        for r in roster:
            slot.setdefault(r.officer, r.slot)
        for row in rows:
            if row.officer in slot and 1 <= slot[row.officer] <= 3:
                row.shift = f"Shift {slot[row.officer]}"
            elif row.officer in slot:
                row.need_fix("אין עמדה פנויה (Shift) למאבטח הזה ביום")
            elif row.officer:
                row.flag("המאבטח לא נמצא ברשימת המשמרת של היום", MEDIUM)

    def _apply_busy_checker(self, rows: list[Row]) -> None:
        if not self.s.get("rules.busy_checker_last_minute", False):
            return
        searches = [r for r in rows if r.action == SEARCH and r.start is not None and r.end is not None]
        for r in searches:
            others = [o for o in searches if o is not r and o.officer == r.officer
                      and r.start <= o.start and o.end <= r.end and (o.end - o.start) < (r.end - r.start)]
            if others and r.end - r.start > 1:
                r.start = r.end - 1
                r.flag("הבודק היה עסוק בבדיקה אחרת - הבדיקה נרשמה בדקה האחרונה")

    # ---------------------------------------------------------------- times
    def _finish_times(self, r: Row) -> None:
        if r.start is None:
            r.d_e_f = (None, None, None)
            if r.action != ASSUMED_POST:
                r.flag("שעת התחלה לא ידועה", LOW)
            return
        f = r.start * 60
        if r.action == ASSUMED_POST:
            r.d_e_f = (f, f, f)
            return
        d = f - int(self.s.get("times.d_offset_seconds", 60))
        e = f - int(self.s.get("times.e_offset_seconds", 30))
        r.d_e_f = (d, e, f)


def group_by_day(events: list[Event]) -> dict[date, list[Event]]:
    out: dict[date, list[Event]] = defaultdict(list)
    for e in events:
        if e.day is not None:
            out[e.day].append(e)
    return out


def sources_text(msgs: list[Message]) -> str:
    return "\n".join(f"[{m.stamp}] {m.sender}: {m.text}" for m in msgs)
