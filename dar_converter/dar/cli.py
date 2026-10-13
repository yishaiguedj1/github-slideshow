"""Command line:  python -m dar <command> ...

  convert   --from 2026-08-01 --to 2026-08-31      chat -> DAR file + review file
  evaluate  --days 2026-08-16,2026-08-17           compare with the real DAR (gap report)
  pending   --from ... --to ...                    unrecognised lines (JSON) for a Claude session
  learn                                            merge corrections into the reference lists
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from .corrections import Corrections, learn
from .evaluate import FIELDS, evaluate, format_summary, load_actual, write_report
from .normalize import Reference
from .parse import parse_file
from .pipeline import messages_by_day, run
from .settings import load_settings
from .sheets import build_plan, format_requests
from .write import (load_template, retarget_month, template_month, write_dar, write_pending_json,
                    write_review)


def _date(s: str) -> date:
    return date.fromisoformat(s)


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--settings", help="settings.yaml (ברירת מחדל: config/settings.yaml)")
    p.add_argument("--chat", help="קובץ ייצוא הצ'אט")
    p.add_argument("--reference", help="קובץ השמות (reference.yaml)")
    p.add_argument("--corrections", help="קובץ התיקונים (corrections.yaml)")


def _load(args):
    s = load_settings(args.settings)
    chat = Path(args.chat) if args.chat else s.path("chat")
    ref_path = Path(args.reference) if args.reference else s.path("reference")
    corr_path = Path(args.corrections) if args.corrections else s.path("corrections")
    msgs = parse_file(chat, s.get("locale.date_order", "DMY"))
    ref = Reference.load(ref_path)
    corr = Corrections.load(corr_path)
    return s, msgs, ref, corr, ref_path


def cmd_convert(args) -> int:
    s, msgs, ref, corr, ref_path = _load(args)
    start, end = args.date_from, args.date_to
    out_dir = Path(args.out_dir) if args.out_dir else s.data_dir / s.get("paths.out_dir", "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    template = Path(args.template) if args.template else s.path("template")

    rr = run(msgs, start, end, s, ref, corr, ref_path, s.data_dir / "examples.jsonl")
    wb = load_template(template, s)
    if args.retarget:
        # no official file for this month at hand: build it from another month's file
        retarget_month(wb, start.year, start.month)
    y, mth = template_month(wb)
    other = sorted({(d.year, d.month) for d in (start, end)} - {(y, mth)})
    if other:
        print(f"התבנית היא של {mth:02d}/{y}, והטווח כולל חודש אחר ({other}). "
              "צריך תבנית לכל חודש - הרץ כל חודש בנפרד עם --template.", file=sys.stderr)
        return 2
    where = write_dar(wb, rr.results, s)
    tag = f"{start:%Y-%m-%d}_{end:%Y-%m-%d}"
    dar_path = out_dir / (args.name or f"DAR_{tag}.xlsx")
    review_path = out_dir / f"review_{tag}.xlsx"
    pending_path = out_dir / f"pending_{tag}.json"
    wb.save(dar_path)
    write_review(review_path, rr.results, where, s, rr.pending, rr.chatter)
    write_pending_json(pending_path, rr.pending, messages_by_day(rr.messages))

    n_rows = sum(1 for k in where)
    n_fix = sum(1 for res in rr.results for r in res.rows if r.fix and (res.day, r.seq) in where)
    n_flag = sum(1 for res in rr.results for r in res.rows
                 if r.flags and not r.fix and (res.day, r.seq) in where)
    n_issues = sum(len(res.issues) for res in rr.results)
    print(f"נכתבו {n_rows} שורות: {n_fix} מסומנות באדום 'דרוש תיקון', {n_flag} עם הערה לבדיקה. "
          f"{n_issues} הערות ברמת יום, {len(rr.pending)} שורות צ'אט שלא זוהו.")
    for line in rr.learned:
        print("נלמד:", line)
    print("DAR:    ", dar_path)
    print("בדיקה:  ", review_path)
    print("לא זוהו:", pending_path)
    return 0


def cmd_evaluate(args) -> int:
    s, msgs, ref, corr, ref_path = _load(args)
    actual_path = Path(args.actual) if args.actual else s.path("template")
    if args.days == "auto":
        from .evaluate import set_reference, user_days
        set_reference(ref)
        who = ref.default_supervisor() if args.who == "auto" else args.who
        days = user_days(actual_path, who)
        if not days:
            print("לא נמצאו ימים שבהם", who, "פותח כ-Shift 1")
            return 1
    elif args.days:
        days = [_date(d) for d in args.days.split(",")]
    else:
        days, d = [], args.date_from
        while d <= args.date_to:
            days.append(d)
            d += timedelta(days=1)
    rr = run(msgs, min(days), max(days), s, ref, corr)
    th = float(s.get("review.min_confidence_main", 0))
    pred = {res.day: [r for r in res.rows if r.confidence >= th] for res in rr.results}
    actual = load_actual(actual_path, days)
    fields = tuple(args.fields.split(",")) if args.fields else FIELDS
    res = evaluate(pred, actual, days, fields, ref)
    title = f"השוואה ל-{actual_path.name}, ימים: " + ", ".join(f"{d:%d/%m}" for d in days)
    print(format_summary(res, title))
    if args.report:
        write_report(args.report, res, messages_by_day(rr.messages), title)
        print("דוח פערים:", args.report)
    return 0


def cmd_pending(args) -> int:
    s, msgs, ref, corr, ref_path = _load(args)
    rr = run(msgs, args.date_from, args.date_to, s, ref, corr)
    out = Path(args.out) if args.out else s.data_dir / s.get("paths.out_dir", "out") / \
        f"pending_{args.date_from}_{args.date_to}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_pending_json(out, rr.pending, messages_by_day(rr.messages))
    print(f"{len(rr.pending)} שורות שלא זוהו -> {out}")
    return 0


def cmd_sheets_plan(args) -> int:
    import json
    s, msgs, ref, corr, ref_path = _load(args)
    rr = run(msgs, args.date_from, args.date_to, s, ref, corr, ref_path)
    existing = {}
    if args.existing:
        with open(args.existing, encoding="utf-8") as fh:
            existing = json.load(fh)
    plan = build_plan(rr.results, s, existing, args.tab_format)
    out = Path(args.out) if args.out else s.data_dir / s.get("paths.out_dir", "out") / \
        f"sheets_plan_{args.date_from}_{args.date_to}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    n_rows = sum(len(t["values"][0]["values"]) for t in plan["tabs"])
    n_fix = sum(len(t["fix_rows"]) for t in plan["tabs"])
    print(f"{len(plan['tabs'])} לשוניות, {n_rows} שורות ({n_fix} דרוש תיקון) -> {out}")
    return 0


def cmd_sheets_requests(args) -> int:
    import json
    s = load_settings(args.settings)
    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    with open(args.sheet_ids, encoding="utf-8") as fh:
        ids = {k: int(v) for k, v in json.load(fh).items()}
    reqs = format_requests(plan, ids, str(s.get("review.fix_fill", "FFC7CE")))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"requests": reqs}, fh, ensure_ascii=False)
    print(f"{len(reqs)} בקשות עיצוב -> {args.out}")
    return 0


def cmd_learn(args) -> int:
    s, msgs, ref, corr, ref_path = _load(args)
    learned = learn(corr, ref, ref_path)
    print("\n".join(learned) if learned else "אין כינויים חדשים ללמוד.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dar", description="WhatsApp -> DAR")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("convert", help="המרה של טווח תאריכים לקובץ DAR")
    _common(c)
    c.add_argument("--from", dest="date_from", type=_date, required=True)
    c.add_argument("--to", dest="date_to", type=_date, required=True)
    c.add_argument("--template")
    c.add_argument("--out-dir")
    c.add_argument("--name", help="שם קובץ הפלט")
    c.add_argument("--retarget", action="store_true",
                   help="התבנית של חודש אחר: לשנות שמות לשוניות ותאריכים לחודש של הטווח")
    c.set_defaults(func=cmd_convert)

    e = sub.add_parser("evaluate", help="השוואה לאקסל אמיתי")
    _common(e)
    e.add_argument("--days", help="2026-08-16,2026-08-17  או  auto = הימים שבהם --who פותח כ-Shift 1")
    e.add_argument("--who", default="auto", help="למצב --days auto (ברירת מחדל: המפקח הראשון ברשימה)")
    e.add_argument("--from", dest="date_from", type=_date)
    e.add_argument("--to", dest="date_to", type=_date)
    e.add_argument("--actual", help="האקסל האמיתי (ברירת מחדל: התבנית)")
    e.add_argument("--fields", help="שדות להשוואה, למשל officer,action,F,G,comment")
    e.add_argument("--report", help="קובץ xlsx לדוח הפערים")
    e.set_defaults(func=cmd_evaluate)

    pnd = sub.add_parser("pending", help="שורות שלא זוהו, עם הקשר")
    _common(pnd)
    pnd.add_argument("--from", dest="date_from", type=_date, required=True)
    pnd.add_argument("--to", dest="date_to", type=_date, required=True)
    pnd.add_argument("--out")
    pnd.set_defaults(func=cmd_pending)

    sp = sub.add_parser("sheets-plan", help="תוכנית כתיבה לגוגל שייטס (עותק של הקובץ הרשמי)")
    _common(sp)
    sp.add_argument("--from", dest="date_from", type=_date, required=True)
    sp.add_argument("--to", dest="date_to", type=_date, required=True)
    sp.add_argument("--existing", help="JSON {tab: [[A..L], ...]} - הערכים שכבר בקובץ (שורות מוקד)")
    sp.add_argument("--tab-format", default="%m/%d", help="שם לשונית יום (ברירת מחדל 08/05)")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_sheets_plan)

    sr = sub.add_parser("sheets-requests", help="בקשות עיצוב (אדום + הערות) לפי sheetId")
    sr.add_argument("--settings")
    sr.add_argument("--plan", required=True)
    sr.add_argument("--sheet-ids", required=True, help='JSON {"08/05": 123456, ...}')
    sr.add_argument("--out", required=True)
    sr.set_defaults(func=cmd_sheets_requests)

    lr = sub.add_parser("learn", help="הוספת כינויים מקובץ התיקונים לרשימות")
    _common(lr)
    lr.set_defaults(func=cmd_learn)

    args = ap.parse_args(argv)
    if args.cmd == "evaluate" and not args.days and not (args.date_from and args.date_to):
        ap.error("evaluate צריך --days או --from/--to")
    return args.func(args)
