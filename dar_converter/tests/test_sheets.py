from dar.build import Builder
from dar.extract import extract_all
from dar.sheets import build_plan, format_requests, merge_day, parse_hms
from tests.conftest import DAY, NOA, msg


def day(ref, settings, messages):
    return Builder(ref, settings).build_day(DAY, extract_all(messages, ref))


def test_merge_keeps_other_rows_and_replaces_ours(ref, settings):
    res = day(ref, settings, [msg("07:46", NOA, "39-42 אבי סרק נועה בדקה c2\n42-45 אבי סרק נועה בדקה c1")])
    existing = [["Shift 1", "Someone", "Alarm: Forced Level 1-3", "6:57:00", "6:57:10", "6:57:20", "6:58:00",
                 "", "", "", "office door forced", "ALARM ONLY: X"],
                ["Shift 2", "Old", "Patrol: Interior", "7:00:00", "", "", "", "", "", "", "stale", ""]]
    items = merge_day(existing, res.rows)
    assert items[0]["ag"][2].startswith("Alarm") and items[0]["kl"] == ["office door forced", "ALARM ONLY: X"]
    assert all(it["ag"][1] != "Old" for it in items)
    starts = [parse_hms(it["ag"][3]) for it in items]
    assert starts == sorted(starts)


def test_plan_ranges_badges_and_fix_formatting(ref, settings):
    res = day(ref, settings, [msg("13:51", NOA, "48-51 אבי סרק נועה בדקה c2")])   # only C2 -> fix
    plan = build_plan([res], settings, {"08/05": [["", "", "", "", "", "", ""]] * 3}, "%m/%d")
    (tab,) = plan["tabs"]
    assert tab["tab"] == "08/05"
    ranges = [v["range"] for v in tab["values"]]
    assert ranges[0].startswith("'08/05'!A10:G") and ranges[1].startswith("'08/05'!K10:L")
    assert "'08/05'!C4:C5" in ranges
    assert tab["fix_rows"] and all(f"C{r}" in tab["notes"] for r in tab["fix_rows"])
    reqs = format_requests(plan, {"08/05": 42})
    assert any("repeatCell" in r for r in reqs) and any("updateCells" in r for r in reqs)
    assert all((r.get("repeatCell") or r.get("updateCells"))["range"]["sheetId"] == 42 for r in reqs)
