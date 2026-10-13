from datetime import date

from dar.extract import hour_header
from tests.conftest import AVI, DANA, GIL, NOA, hm, msg


def one(extractor, m, kind=None):
    evs = [e for e in extractor.extract(m) if kind is None or e.kind == kind]
    assert len(evs) == 1, evs
    return evs[0]


def test_scan_pair(extractor):
    e = one(extractor, msg("07:46", NOA, "39-42 דנה סרקה נועה בדקה c2"))
    assert (e.kind, e.actor, e.partner, e.zone) == ("scan", "Dana Cohen", "Noa Bar", "C2")
    assert (hm(e.start), hm(e.end)) == ("07:39", "07:42")


def test_dash_style_and_explicit_hour(extractor):
    e = one(extractor, msg("15:35", AVI, "15:10-13-c2-נועה סרקה אבי בדק"))
    assert (e.actor, e.partner, e.zone, hm(e.start), hm(e.end)) == \
        ("Noa Bar", "Avi Levi", "C2", "15:10", "15:13")


def test_previous_hour_when_minutes_are_ahead(extractor):
    e = one(extractor, msg("10:05", DANA, "52-55 אבי סרק דנה בדקה c1"))
    assert (hm(e.start), hm(e.end)) == ("09:52", "09:55")


def test_storage_scan_is_not_a_report(extractor):
    evs = extractor.extract(msg("07:46", NOA, "39-42 דנה סרקה נועה בדקה c2\n\n43 נועה סרקה מחסן"))
    assert [e.kind for e in evs] == ["scan", "storage"]


def test_check_single_minute_and_range(extractor):
    e = one(extractor, msg("11:46", NOA, "44 בדיקה לרון c2"))
    assert (e.kind, e.actor, e.subjects, hm(e.start), hm(e.end)) == \
        ("check", "Noa Bar", ["Ron Shani"], "11:43", "11:44")
    e = one(extractor, msg("11:47", NOA, "45-46 בדיקה לטל C1"))
    assert (hm(e.start), hm(e.end), e.zone) == ("11:45", "11:46", "C1")


def test_check_verb_forms(extractor):
    e = one(extractor, msg("10:41", DANA, "40 גיל בדק את אבי c1"))
    assert (e.actor, e.subjects) == ("Gil Amir", ["Avi Levi"])
    e = one(extractor, msg("10:58", GIL, "בדקתי את רון 1056"))
    assert (e.actor, e.subjects, hm(e.end)) == ("Gil Amir", ["Ron Shani"], "10:56")


def test_escort_start_end_and_location(extractor):
    e = one(extractor, msg("09:06", AVI, "06 תחילת ליווי רון למחסן"))
    assert (e.kind, e.actor, e.subjects, e.zone, hm(e.start)) == \
        ("escort_start", "Avi Levi", ["Ron Shani"], "Storage", "09:06")
    e = one(extractor, msg("12:56", DANA, "53 המנקה יצאה מהמשרד"))
    assert (e.kind, e.subjects, e.zone) == ("escort_end", ["Mira Katz"], "Office")
    e = one(extractor, msg("14:40", DANA, "תחילת ליווי משרד רון וטל"))
    assert e.subjects == ["Ron Shani", "Tal Peretz"] and hm(e.start) == "14:40"
    assert e.confidence < 1                                     # time taken from the message


def test_check_with_escort_end_and_handover(extractor):
    evs = extractor.extract(msg("10:51", DANA, "48-50 בדיקה לרון C2 וסיום ליווי"))
    assert [e.kind for e in evs] == ["check", "escort_end"]
    evs = extractor.extract(msg("11:01", AVI, "10:46-47-בדיקה לנועה והמשך ליווי רון"))
    assert [e.kind for e in evs] == ["check", "escort_handover"]
    assert evs[0].subjects == ["Noa Bar"] and evs[1].subjects == ["Ron Shani"]
    assert evs[1].actor == "Avi Levi" and hm(evs[1].start) == "10:46"


def test_hour_header_and_late_report_after_midnight(extractor):
    assert hour_header("*של שעה 18:00* 😅") == 18
    assert hour_header("——-11:00——") == 11
    assert hour_header("50 תחילת ליווי נוסף של רון c2") is None
    evs = extractor.extract(msg("00:18", GIL, "*של שעה 18:00*\n\n40-43 נועה סרקה גיל בדק c2",
                                day=date(2026, 8, 17)))
    assert evs[0].day == date(2026, 8, 16) and hm(evs[0].start) == "18:40"


def test_explicit_hour_sets_context_for_next_lines(extractor):
    evs = extractor.extract(msg("12:27", NOA, "11:30 בדיקה לרון c1\n25-28 גיל סרק c1\n32 בדיקה לגיל c1"))
    assert [hm(e.end) for e in evs] == ["11:30", "11:28", "11:32"]


def test_typos_and_glued_words(extractor):
    e = one(extractor, msg("14:07", DANA, "03-07 נועה סרקה דנה בדק V2"))
    assert e.zone == "C2"
    e = one(extractor, msg("12:53", AVI, "48-51-с1-נועה סרקה אבי בדק"))   # Cyrillic с
    assert e.zone == "C1"
    e = one(extractor, msg("09:42", NOA, "42 תחילתמליווי טל c1"))
    assert e.kind == "escort_start" and e.subjects == ["Tal Peretz"]


def test_suspicious_range_goes_to_review(extractor):
    e = one(extractor, msg("18:46", NOA, "42-25 אבי סרק נועה בדקה c2"))
    assert e.end is None and e.confidence < 0.6


def test_unknown_name_is_not_guessed(extractor):
    e = one(extractor, msg("15:49", DANA, "49 תחילת ליווי צביקה ורון במשרד"))
    assert e.subjects == ["?צביקה", "Ron Shani"]


def test_chatter_and_unknown(extractor):
    assert one(extractor, msg("12:00", DANA, "יוצאים לצהריים")).kind == "ignore"
    assert one(extractor, msg("12:00", DANA, "פגשנו את רון למטה")).kind == "chatter"
    assert one(extractor, msg("10:51", DANA, "50 רון חוזר ל-c1")).kind == "unknown"
