"""Write plan for Google Sheets.

The converter has no Google credentials. It produces a plan (cell ranges + values) that a
Claude session applies with the Google Sheets connector, on a *copy of the month's official
DAR* - so tab names ("08/05"), formatting, dropdowns and formulas stay exactly as the original.

Only A-G and K-L of the day tabs and the badge cells C4:C5 are written; H-J are the sheet's
own formulas. Rows that are not ours (camera-company alarms, admin notes) are kept in place
and our rows are merged with them by time.
"""
from __future__ import annotations

import re
from datetime import date

from .build import DayResult
from .models import ASSUMED_POST, OUR_ACTIONS, Row
from .settings import Settings

FIRST_ROW = 10
FIX_PREFIX = "⚠ דרוש תיקון: "


def tab_name(d: date, fmt: str = "%m/%d") -> str:
    return d.strftime(fmt)


def hms(sec: int | None) -> str:
    if sec is None:
        return ""
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def parse_hms(text) -> int | None:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*", str(text or ""))
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3) or 0)


def row_cells(r: Row) -> tuple[list, list]:
    """(A..G, K..L) for one converter row."""
    d, e, f, g = r.times_seconds()
    comment = r.comment or (FIX_PREFIX + r.fix[0] if r.fix else "")
    return ([r.shift or "", r.officer or "", r.action, hms(d), hms(e), hms(f), hms(g)],
            [comment, ""])


def merge_day(existing: list[list], ours: list[Row]) -> list[dict]:
    """Keep rows that are not ours (A..L strings from the sheet), add ours, sort by D."""
    items = []
    for i, vals in enumerate(existing):
        vals = [("" if v is None else str(v)) for v in (list(vals) + [""] * 12)[:12]]
        if not any(v.strip() for v in vals[:7]):
            continue
        if vals[2].strip() in OUR_ACTIONS:
            continue                                  # replaced by the converter's rows
        items.append({"ag": vals[:7], "kl": vals[10:12], "row": None,
                      "key": (parse_hms(vals[3]) if parse_hms(vals[3]) is not None else 10 ** 6, 1, i)})
    for r in ours:
        ag, kl = row_cells(r)
        d = r.times_seconds()[0]
        items.append({"ag": ag, "kl": kl, "row": r,
                      "key": (d if d is not None else 10 ** 6, 0 if r.action == ASSUMED_POST else 2, r.seq)})
    items.sort(key=lambda x: x["key"])
    return items


def build_plan(results: list[DayResult], s: Settings, existing: dict[str, list] | None = None,
               tab_format: str = "%m/%d") -> dict:
    existing = existing or {}
    badges = s.get("badges", {}) or {}
    tabs = []
    for res in results:
        name = tab_name(res.day, tab_format)
        old = existing.get(name, [])
        items = merge_day(old, res.rows)
        n_old = sum(1 for v in old if any(str(x or "").strip() for x in (list(v) + [""] * 7)[:7]))
        n = max(len(items), n_old)
        if n == 0:
            continue
        last = FIRST_ROW + n - 1
        ag = [it["ag"] for it in items] + [[""] * 7] * (n - len(items))
        kl = [it["kl"] for it in items] + [[""] * 2] * (n - len(items))
        tab = {"tab": name, "date": res.day.isoformat(),
               "values": [{"range": f"'{name}'!A{FIRST_ROW}:G{last}", "values": ag},
                          {"range": f"'{name}'!K{FIRST_ROW}:L{last}", "values": kl}],
               "fix_rows": [], "notes": {}}
        if any(r.action != ASSUMED_POST for r in res.rows) and badges.get("employee") is not None:
            tab["values"].append({"range": f"'{name}'!C4:C5",
                                  "values": [[badges.get("employee")], [badges.get("visitor", 0)]]})
        for i, it in enumerate(items):
            r = it["row"]
            if r is None:
                continue
            row_no = FIRST_ROW + i
            if r.fix:
                tab["fix_rows"].append(row_no)
                tab["notes"][f"C{row_no}"] = "דרוש תיקון:\n" + "\n".join(f"- {f}" for f in r.fix)
            elif r.flags:
                tab["notes"][f"C{row_no}"] = "לבדיקה:\n" + "\n".join(f"- {f}" for f in r.flags)
        tabs.append(tab)
    return {"tab_format": tab_format, "tabs": tabs}


def format_requests(plan: dict, sheet_ids: dict[str, int], fill: str = "FFC7CE") -> list[dict]:
    """Sheets API batchUpdate requests: red fill on rows that need a fix, notes on column C."""
    rgb = {k: int(fill[i:i + 2], 16) / 255 for k, i in (("red", 0), ("green", 2), ("blue", 4))}
    reqs = []
    for tab in plan["tabs"]:
        sid = sheet_ids.get(tab["tab"])
        if sid is None:
            continue
        for row_no in tab["fix_rows"]:
            for c0, c1 in ((0, 7), (10, 11)):                 # A:G and K
                reqs.append({"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": row_no - 1, "endRowIndex": row_no,
                              "startColumnIndex": c0, "endColumnIndex": c1},
                    "cell": {"userEnteredFormat": {"backgroundColor": rgb}},
                    "fields": "userEnteredFormat.backgroundColor"}})
        for a1, text in tab["notes"].items():
            row_no = int(a1[1:])
            reqs.append({"updateCells": {
                "range": {"sheetId": sid, "startRowIndex": row_no - 1, "endRowIndex": row_no,
                          "startColumnIndex": 2, "endColumnIndex": 3},
                "rows": [{"values": [{"note": text}]}], "fields": "note"}})
    return reqs
