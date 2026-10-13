from datetime import datetime

from dar.parse import parse_lines

ANDROID = """14/01/2024, 9:50 - Messages and calls are end-to-end encrypted. Only people in this chat can read them.
14/01/2024, 9:50 - ‎‫דנה מנהלת‬‎ created group "סריקות"
05/08/2026, 7:46 - נועה - עבודה - חברה: 39-42 דנה סרקה נועה בדקה c2

43 נועה בדקה מחסן
05/08/2026, 9:52 - דנה - עבודה: 50 תחילת ליווי רון c2 <This message was edited>
05/08/2026, 9:53 - אבי לוי: This message was deleted
05/08/2026, 9:53 - אבי לוי: This message was deleted
"""


def test_android_multiline_system_edited_deleted():
    msgs = parse_lines(ANDROID.splitlines(keepends=True))
    assert len(msgs) == 6
    assert msgs[0].system and msgs[1].system
    m = msgs[2]
    assert m.sender == "נועה - עבודה - חברה"
    assert m.ts == datetime(2026, 8, 5, 7, 46)
    assert m.text.splitlines() == ["39-42 דנה סרקה נועה בדקה c2", "", "43 נועה בדקה מחסן"]
    assert msgs[3].edited and msgs[3].text == "50 תחילת ליווי רון c2"
    assert msgs[4].deleted
    assert len({x.id for x in msgs}) == len(msgs)          # ids stay unique for repeated text


def test_ios_format_and_ampm():
    lines = ["[05/08/2026, 07:46:10] דנה - עבודה: 39-42 נועה סרקה c2\n",
             "1/5/24, 9:50 PM - אבי לוי: 44 בדיקה לרון c1\n"]
    msgs = parse_lines(lines)
    assert msgs[0].ts == datetime(2026, 8, 5, 7, 46, 10) and msgs[0].sender == "דנה - עבודה"
    assert msgs[1].ts == datetime(2024, 5, 1, 21, 50)


def test_month_first_order():
    msgs = parse_lines(["8/5/2026, 07:46 - דנה - עבודה: x\n"], date_order="MDY")
    assert msgs[0].ts == datetime(2026, 8, 5, 7, 46)
