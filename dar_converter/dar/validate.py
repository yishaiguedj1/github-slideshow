"""Code-level checks on the built rows: values, times, duplicates, overlaps, gaps."""
from __future__ import annotations

from collections import defaultdict

from .build import DayResult
from .models import (ASSUMED_POST, ESCORT, LOW, MEDIUM, OUR_ACTIONS, PATROL, SEARCH, Issue,
                     fmt_minutes)
from .normalize import Reference
from .settings import Settings

SHIFTS = ("Shift 1", "Shift 2", "Shift 3")


def validate_day(res: DayResult, s: Settings, ref: Reference) -> None:
    day_start, day_end = s.day_bounds(res.day)
    limits = {PATROL: s.get("validation.max_patrol_minutes", 15),
              SEARCH: s.get("validation.max_check_minutes", 10),
              ESCORT: s.get("validation.max_escort_minutes", 360)}
    rows = [r for r in res.rows]

    for r in rows:
        if r.action not in OUR_ACTIONS:
            r.flag(f"פעולה לא ברשימה: {r.action}", LOW)
        if r.shift not in SHIFTS:
            r.flag("Shift חסר או לא תקין", MEDIUM)
        if r.officer is None:
            r.flag("שם המאבטח חסר", LOW)
        elif not ref.is_officer(r.officer):
            r.flag(f"מאבטח לא ברשימה: {r.officer}", LOW)
        if r.action == ASSUMED_POST:
            continue
        if r.start is not None and r.end is not None:
            dur = r.end - r.start
            if dur < 0:
                r.flag("שעת הסיום לפני שעת ההתחלה", LOW)
            elif dur > limits.get(r.action, 999):
                r.flag(f"משך חריג: {dur} דק'", MEDIUM)
        if r.start is not None and not (day_start - 30 <= r.start <= day_end + 30):
            r.flag(f"מחוץ לשעות היום ({fmt_minutes(r.start)})", MEDIUM)

    # exact duplicates (same officer, action, comment and times)
    seen: dict[tuple, object] = {}
    for r in rows:
        if r.action == ASSUMED_POST:
            continue
        key = (r.officer, r.action, r.comment, r.start, r.end)
        if key in seen:
            r.flag("שורה כפולה", LOW)
            res.issues.append(Issue(res.day, "duplicate", "שורה כפולה: " + _short(r), row=r,
                                    sources=r.sources))
        else:
            seen[key] = r

    # one officer cannot patrol twice at the same time
    by_officer = defaultdict(list)
    for r in rows:
        if r.action == PATROL and r.start is not None and r.end is not None:
            by_officer[r.officer].append(r)
    for officer, rs in by_officer.items():
        rs.sort(key=lambda r: r.start)
        for a, b in zip(rs, rs[1:]):
            if b.start < a.end:
                b.flag("חופף לסריקה אחרת של אותו מאבטח", MEDIUM)

    # gaps: rounds are reported about once an hour
    work = [r for r in rows if r.action == PATROL and r.start is not None]
    if work and s.is_workday(res.day):
        hole = int(s.get("validation.hole_minutes", 90))
        starts = sorted(r.start for r in work)
        points = [day_start] + starts + [day_end]
        for a, b in zip(points, points[1:]):
            if b - a > hole:
                res.issues.append(Issue(res.day, "gap",
                                        f"אין סריקה בין {fmt_minutes(a)} ל-{fmt_minutes(b)}"))
    if s.is_workday(res.day) and rows and not s.is_holiday(res.day):
        last = max((r.end or r.start or 0) for r in rows if r.action != ASSUMED_POST) \
            if any(r.action != ASSUMED_POST for r in rows) else 0
        if 0 < last < 15 * 60:
            res.issues.append(Issue(res.day, "short_day",
                                    f"הפעילות האחרונה ב-{fmt_minutes(last)} - ערב חג? "
                                    "(אם כן, להוסיף את התאריך ל-holidays)"))
    if not rows and s.is_workday(res.day):
        res.issues.append(Issue(res.day, "empty", "אין דיווחים ביום עבודה"))


def _short(r) -> str:
    return f"{r.officer} | {r.action} | {fmt_minutes(r.start)}-{fmt_minutes(r.end)} | {r.comment or ''}"
