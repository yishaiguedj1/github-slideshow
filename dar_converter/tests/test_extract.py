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


def test_reversed_range_is_read_like_the_manual_entries(extractor):
    e = one(extractor, msg("18:55", NOA, "49-46 אבי סרק נועה בדקה c2"))      # swapped
    assert (hm(e.start), hm(e.end)) == ("18:46", "18:49") and e.confidence == 0.8
    e = one(extractor, msg("18:46", NOA, "42-25 אבי סרק נועה בדקה c2"))      # 25 typed for 45
    assert (hm(e.start), hm(e.end)) == ("18:42", "18:45") and e.notes


def test_suspicious_range_goes_to_review(extractor):
    e = one(extractor, msg("18:46", NOA, "55-20 אבי סרק נועה בדקה c2"))
    assert e.end is None and e.confidence < 0.6


def test_unknown_name_is_not_guessed(extractor):
    e = one(extractor, msg("15:49", DANA, "49 תחילת ליווי צביקה ורון במשרד"))
    assert e.subjects == ["?צביקה", "Ron Shani"]


def test_chatter_and_unknown(extractor):
    assert one(extractor, msg("12:00", DANA, "יוצאים לצהריים")).kind == "ignore"
    assert one(extractor, msg("12:00", DANA, "פגשנו את רון למטה")).kind == "chatter"
    assert one(extractor, msg("10:51", DANA, "50 רון ממתין למטה")).kind == "unknown"


def test_location_with_digits_is_not_read_as_a_time(extractor):
    e = one(extractor, msg("12:54", DANA, "49 תחילת ליווי רון bldg 7"))
    assert (e.kind, e.zone, hm(e.start)) == ("escort_start", "BLDG7", "12:49")


def test_signature_after_the_zone_names_the_checker(extractor):
    e = one(extractor, msg("12:18", DANA, "15-17 בדיקה לרון C1 דנה"))
    assert (e.actor, e.subjects, e.confidence) == ("Dana Cohen", ["Ron Shani"], 1.0)
    e = one(extractor, msg("12:18", NOA, "54-55 בדיקה לרון - דנה c1"))     # another officer signs
    assert (e.actor, e.subjects) == ("Dana Cohen", ["Ron Shani"]) and e.confidence == 0.8
    e = one(extractor, msg("10:47", NOA, "45 בדיקה לרון, טל, גיל c2"))      # a list, no signature
    assert e.actor == "Noa Bar" and len(e.subjects) == 3


def test_name_before_the_verb_did_the_check(extractor):
    e = one(extractor, msg("11:37", DANA, "33-36 בדיקה לטל C1 גיל בדק"))
    assert (e.actor, e.subjects) == ("Gil Amir", ["Tal Peretz"])


def test_returning_and_moving_escorts(extractor):
    e = one(extractor, msg("10:24", AVI, "23 רון חזר חc2"))
    assert (e.kind, e.subjects, e.zone, hm(e.start)) == ("escort_start", ["Ron Shani"], "C2", "10:23")
    e = one(extractor, msg("11:33", DANA, "32 עוברים לליווי ב C2"))
    assert (e.kind, e.zone, hm(e.start)) == ("escort_move", "C2", "11:32")
    assert one(extractor, msg("09:56", DANA, "עוברים לC1")).kind == "ignore"
    e = one(extractor, msg("18:22", AVI, "22 בדיקה לטל c2 עובר לc1"))
    assert (e.kind, e.zone) == ("check", "C2")


def test_entry_and_exit_is_an_escort_with_an_exit_check(extractor):
    evs = extractor.extract(msg("10:51", AVI, "47-48 כניסה ויציאה רון C1\n48-51 כניסה ויציאה רון C2"))
    assert [(e.kind, e.zone, hm(e.start), hm(e.end)) for e in evs] == [
        ("escort_start", "C1", "10:47", "10:48"), ("check", "C1", "10:47", "10:48"),
        ("escort_start", "C2", "10:48", "10:51"), ("check", "C2", "10:50", "10:51")]


def test_check_without_a_time_takes_the_message_time(extractor):
    e = one(extractor, msg("11:11", AVI, "בדיקה לרון c1"))
    assert (hm(e.start), hm(e.end), e.confidence) == ("11:10", "11:11", 0.8)


def test_hour_headers_with_a_range():
    assert hour_header("——-שעה 16:00-17:00——-") == 16
    assert hour_header("*————-של שעה 10:00-11:———*") == 10


def test_time_typos_and_inline_hour(extractor):
    e = one(extractor, msg("15:00", AVI, "45-49 גיל סרק נועה בד*ק C2 של שעה 14:00*"))
    assert (e.actor, e.partner, hm(e.start), hm(e.end)) == ("Gil Amir", "Noa Bar", "14:45", "14:49")
    e = one(extractor, msg("15:45", AVI, "13:25-13: 28 גיל סרק נועה בדקה c1"))
    assert (hm(e.start), hm(e.end)) == ("13:25", "13:28")
    e = one(extractor, msg("17:58", AVI, "17:47-17-50 גיל סרק נועה בדקה c2"))
    assert (hm(e.start), hm(e.end)) == ("17:47", "17:50")
    for text in ("55-59-c1-גיל סרק נועה בדק0", "8:45-8:48 גיל סרק נועה בדק  1"):
        assert one(extractor, msg("10:59", AVI, text)).kind == "scan"


def test_officer_typos_where_an_officer_is_expected(extractor):
    e = one(extractor, msg("16:31", AVI, "27-31 אבי סרק דנ בדק C1"))
    assert (e.actor, e.partner, e.confidence) == ("Avi Levi", "Dana Cohen", 1.0)
    e = one(extractor, msg("10:20", AVI, "16-19 אבי ברק גיל בדק c1"))
    assert (e.kind, e.actor, e.partner) == ("scan", "Avi Levi", "Gil Amir")
    assert one(extractor, msg("09:46", AVI, "43-אבי ברק מחסן")).kind == "storage"


def test_single_time_scan_starts_at_that_time(extractor):
    e = one(extractor, msg("10:20", AVI, "20 סריקה בc2"))
    assert (hm(e.start), hm(e.end)) == ("10:20", "10:23")


def test_escort_namesake_is_the_visitor(extractor):
    e = one(extractor, msg("11:09", AVI, "09 תחילת ליווי רון ועומר c1"))
    assert e.subjects == ["Ron Shani", "Omer Gold"] and e.confidence == 1.0
    e = one(extractor, msg("10:26", AVI, "חילוף עומר ואבי בליווי רון c2"))      # officers swap
    assert (e.kind, e.subjects) == ("escort_handover", ["Ron Shani"])
    e = one(extractor, msg("11:53", AVI, "52 תחילת ליווי רון c1 - עומר"))       # signature
    assert e.subjects == ["Ron Shani"]
    evs = extractor.extract(msg("15:42", AVI, "42 בדיקה לעומר והחלפת ליווי c1"))
    assert [(x.kind, x.subjects) for x in evs] == [("check", ["Omer Paz"]), ("escort_handover", [])]


def test_glued_and_misspelt_words(extractor):
    assert one(extractor, msg("11:29", AVI, "27-28 בדיקהמרון c2")).subjects == ["Ron Shani"]
    e = one(extractor, msg("11:54", AVI, "54-מי1ה נכנסה למשרד"))
    assert (e.kind, e.subjects, e.zone) == ("escort_start", ["Mira Katz"], "Office")
    e = one(extractor, msg("12:54", AVI, "12:20-רון נכננסה למשרד"))
    assert (e.kind, e.subjects) == ("escort_start", ["Ron Shani"])
    assert one(extractor, msg("09:27", AVI, "וואלה מסכים")).kind == "chatter"


def test_escort_and_check_in_one_line(extractor):
    evs = extractor.extract(msg("12:27", AVI, "12-26 ליווי ובדיקה לרון בc2"))
    assert [(e.kind, e.subjects, hm(e.start), hm(e.end)) for e in evs] == [
        ("escort_start", ["Ron Shani"], "12:12", "12:12"), ("check", ["Ron Shani"], "12:25", "12:26")]
    evs = extractor.extract(msg("10:14", AVI, "13 בדיקה לטל וליווי לרון בc2"))
    assert [(e.kind, e.subjects, hm(e.start)) for e in evs] == [
        ("check", ["Tal Peretz"], "10:12"), ("escort_start", ["Ron Shani"], "10:12")]


def test_edited_message_may_report_the_next_minutes(extractor):
    m = msg("09:47", AVI, "51 תחילת ליווי רון c1")
    m.edited = True
    assert hm(one(extractor, m).start) == "09:51"
    assert hm(one(extractor, msg("09:47", AVI, "51 תחילת ליווי רון c1")).start) == "08:51"


def test_updated_for_hour_header():
    assert hour_header("מעודכן לשעה 13:00:") == 13
