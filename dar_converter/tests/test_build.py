from dar.build import Builder
from dar.extract import extract_all
from dar.models import ASSUMED_POST, ESCORT, PATROL, SEARCH
from tests.conftest import AVI, DANA, DAY, GIL, NOA, hm, msg


def build(ref, settings, messages, overrides=None):
    s = settings.with_overrides(overrides) if overrides else settings
    evs = extract_all(messages, ref)
    return Builder(ref, s).build_day(DAY, evs)


def rows_of(res, action):
    return [r for r in res.rows if r.action == action]


def test_pair_becomes_patrol_and_search_with_contiguous_zones(ref, settings):
    res = build(ref, settings, [msg("07:46", NOA, "39-42 דנה סרקה נועה בדקה c2\n\n43 נועה סרקה מחסן\n\n43-46 דנה סרקה נועה בדקה c1")])
    patrols, searches = rows_of(res, PATROL), rows_of(res, SEARCH)
    assert [(hm(r.start), hm(r.end)) for r in patrols] == [("07:39", "07:42"), ("07:42", "07:46")]
    assert all(r.officer == "Dana Cohen" and r.comment == "Routine Patrol" for r in patrols)
    assert [r.comment for r in searches] == ["Metal screening C2 : Dana Cohen - Declined to sit",
                                             "Metal screening C1 : Dana Cohen - Declined to sit"]
    d, e, f, g = patrols[0].times_seconds()
    assert (d, e, f, g) == (7 * 3600 + 38 * 60, 7 * 3600 + 38 * 60 + 30, 7 * 3600 + 39 * 60, 7 * 3600 + 42 * 60)


def test_auto_join_moves_boundary_after_a_two_minute_gap(ref, settings):
    res = build(ref, settings, [msg("08:46", NOA, "37-40 אבי סרק נועה בדקה c2\n42-45 אבי סרק נועה בדקה c1")])
    assert [(hm(r.start), hm(r.end)) for r in rows_of(res, PATROL)] == [("08:37", "08:41"), ("08:41", "08:45")]


def test_far_apart_zones_are_not_joined(ref, settings):
    res = build(ref, settings, [msg("12:20", NOA, "17-20 אבי סרק נועה בדקה c2"),
                                msg("12:46", NOA, "24-27 אבי סרק נועה בדקה c1")])
    assert [(hm(r.start), hm(r.end)) for r in rows_of(res, PATROL)] == [("12:17", "12:20"), ("12:24", "12:27")]


def test_scan_and_later_check_stay_separate(ref, settings):
    res = build(ref, settings, [msg("11:53", NOA, "50-53 נועה סרקה c2"),
                                msg("11:55", DANA, "54-55 בדיקה לנועה C2")])
    (p,), (s,) = rows_of(res, PATROL), rows_of(res, SEARCH)
    assert (p.officer, hm(p.start), hm(p.end)) == ("Noa Bar", "11:50", "11:53")
    assert (s.officer, hm(s.start), hm(s.end), s.comment) == \
        ("Dana Cohen", "11:54", "11:55", "Metal screening C2 : Noa Bar - Declined to sit")


def test_scan_start_only_gets_average_length(ref, settings):
    res = build(ref, settings, [msg("12:43", NOA, "42 תחילת סריקה נועה c2"),
                                msg("12:48", AVI, "48-c2-בדיקה לנועה")])
    (p,), (s,) = rows_of(res, PATROL), rows_of(res, SEARCH)
    assert (hm(p.start), hm(p.end)) == ("12:42", "12:45") and p.flags
    assert (s.officer, hm(s.start), hm(s.end)) == ("Avi Levi", "12:47", "12:48")


def test_contractor_check_minutes_follow_settings(ref, settings):
    msgs = [msg("11:50", NOA, "50 בדיקה לרון c2"),       # visitor (escorted)
            msg("11:52", NOA, "52 בדיקה לגיל c2")]       # employee / officer
    s1, s2 = rows_of(build(ref, settings, msgs), SEARCH)
    assert (hm(s1.start), hm(s1.end)) == ("11:49", "11:50")
    assert (hm(s2.start), hm(s2.end)) == ("11:51", "11:52")
    s1, s2 = rows_of(build(ref, settings, msgs, {"times": {"check_minutes_contractor": 2}}), SEARCH)
    assert (hm(s1.start), hm(s1.end)) == ("11:48", "11:50")
    assert (hm(s2.start), hm(s2.end)) == ("11:51", "11:52")


def test_zone_inferred_from_the_other_half_of_the_round(ref, settings):
    res = build(ref, settings, [msg("10:20", AVI, "17-20-c1-גיל סרק אבי בדק"),
                                msg("10:24", AVI, "20-23-גיל סרק אבי בדק")])
    assert [r.comment for r in rows_of(res, SEARCH)] == \
        ["Metal screening C1 : Gil Amir - Declined to sit", "Metal screening C2 : Gil Amir - Declined to sit"]


def test_escort_ends_at_exit_check_and_one_row_per_person(ref, settings):
    res = build(ref, settings, [msg("09:09", NOA, "09 תחילת ליווי רון c2"),
                                msg("11:46", NOA, "45-46 בדיקה לרון c2"),
                                msg("11:56", NOA, "55 ליווי רון וטל במחסן"),
                                msg("12:08", NOA, "05 סיום ליווי רון וטל במחסן")])
    esc = [(r.officer, r.comment, hm(r.start), hm(r.end)) for r in rows_of(res, ESCORT)]
    assert esc == [("Noa Bar", "Escort C2 : Ron Shani", "09:09", "11:46"),
                   ("Noa Bar", "Escort Storage : Ron Shani", "11:55", "12:05"),
                   ("Noa Bar", "Escort Storage : Tal Peretz", "11:55", "12:05")]


def test_handover_location_backfilled_from_exit_check(ref, settings):
    res = build(ref, settings, [msg("09:20", NOA, "16 תחילת ליווי רון"),
                                msg("11:01", AVI, "10:46-47-בדיקה לנועה והמשך ליווי רון"),
                                msg("12:26", NOA, "23 בדיקה לרון c1")])
    esc = [(r.officer, r.comment, hm(r.start), hm(r.end)) for r in rows_of(res, ESCORT)]
    assert esc == [("Noa Bar", "Escort C1 : Ron Shani", "09:16", "10:46"),
                   ("Avi Levi", "Escort C1 : Ron Shani", "10:46", "12:23")]
    check_noa = [r for r in rows_of(res, SEARCH) if "Noa Bar" in (r.comment or "")]
    assert check_noa and check_noa[0].comment.startswith("Metal screening C1")


def test_same_minute_escort_gets_one_minute(ref, settings):
    res = build(ref, settings, [msg("09:06", AVI, "06 תחילת ליווי רון למחסן"),
                                msg("09:06", AVI, "06 סיום ליווי")])
    (r,) = rows_of(res, ESCORT)
    assert (hm(r.start), hm(r.end)) == ("09:05", "09:06")


def test_supervisor_is_shift_1_and_others_by_priority(ref, settings):
    res = build(ref, settings, [msg("07:46", NOA, "39-42 גיל סרק נועה בדקה c2"),
                                msg("17:46", NOA, "39-42 גיל סרק נועה בדקה c2"),
                                msg("10:10", DANA, "05-08 אבי סרק דנה בדקה c1"),
                                msg("17:10", DANA, "05-08 אבי סרק דנה בדקה c1")])
    ap = [(r.shift, r.officer, hm(r.start), hm(r.end)) for r in rows_of(res, ASSUMED_POST)]
    assert ap == [("Shift 1", "Dana Cohen", "07:00", "19:00"), ("Shift 2", "Avi Levi", "07:00", "19:00"),
                  ("Shift 3", "Noa Bar", "07:00", "19:00"), (None, "Gil Amir", "07:00", "19:00")]
    # Gil is a 4th full-day officer: no free post -> marked for a fix, day issue
    gil = [r for r in res.rows if r.officer == "Gil Amir"]
    assert all(r.shift is None and r.fix for r in gil)
    assert any("Gil Amir" in i.message for i in res.issues)
    assert res.rows[0].action == ASSUMED_POST and res.rows[0].d_e_f[0] == 7 * 3600


def test_no_supervisor_in_chat_gets_the_default_supervisor(ref, settings):
    msgs = [msg("07:46", NOA, "39-42 אבי סרק נועה בדקה c2"),
            msg("17:46", NOA, "39-42 אבי סרק נועה בדקה c2")]
    res = build(ref, settings, msgs)                  # default_supervisor: auto
    ap = [(r.shift, r.officer) for r in rows_of(res, ASSUMED_POST)]
    assert ap == [("Shift 1", "Dana Cohen"), ("Shift 2", "Avi Levi"), ("Shift 3", "Noa Bar")]
    assert rows_of(res, ASSUMED_POST)[0].flags        # assumed, not seen in the chat
    res = build(ref, settings, msgs, {"roster": {"default_supervisor": None}})
    ap = [(r.shift, r.officer) for r in rows_of(res, ASSUMED_POST)]
    assert ap == [("Shift 2", "Avi Levi"), ("Shift 3", "Noa Bar")]
    assert any(i.kind == "no_supervisor" for i in res.issues)


def test_namesake_employee_vs_officer(ref, settings):
    # Gil Amir (officer) is on duty and just scanned -> "בדיקה לגיל" is the officer;
    # later, a check of "גיל" that Gil himself sends is the employee Gil Dror.
    res = build(ref, settings, [msg("10:10", NOA, "05-08 גיל סרק c2"),
                                msg("10:10", NOA, "09 בדיקה לגיל c2"),
                                msg("15:10", GIL, "09 בדיקה לגיל c1")])
    comments = [r.comment for r in rows_of(res, SEARCH)]
    assert comments == ["Metal screening C2 : Gil Amir - Declined to sit",
                        "Metal screening C1 : Gil Dror - Declined to sit"]


def test_split_post_07_13_and_13_19(ref, settings):
    res = build(ref, settings, [msg("08:00", AVI, "50-53 אבי סרק דנה בדקה c2"),
                                msg("09:00", NOA, "50-53 נועה סרקה דנה בדקה c1"),
                                msg("15:00", GIL, "50-53 גיל סרק דנה בדקה c1"),
                                msg("16:00", AVI, "50-53 אבי סרק דנה בדקה c1")])
    ap = sorted((r.shift, r.officer, hm(r.start), hm(r.end)) for r in rows_of(res, ASSUMED_POST))
    assert ("Shift 3", "Noa Bar", "07:00", "13:00") in ap
    assert ("Shift 3", "Gil Amir", "13:00", "19:00") in ap


def test_holiday_ends_at_14(ref, settings):
    res = build(ref, settings, [msg("08:00", AVI, "50-53 אבי סרק דנה בדקה c2")],
                {"day": {"holidays": [DAY.isoformat()]}})
    assert {hm(r.end) for r in rows_of(res, ASSUMED_POST)} == {"14:00"}


def test_unknown_person_is_marked_for_fix_but_known_one_is_clean(ref, settings):
    res = build(ref, settings, [msg("15:49", DANA, "49 תחילת ליווי צביקה ורון במשרד"),
                                msg("16:12", DANA, "12 סיום ליווי במשרד")])
    esc = {r.comment: r for r in rows_of(res, ESCORT)}
    assert esc["Escort Office : Ron Shani"].confidence == 1.0 and not esc["Escort Office : Ron Shani"].fix
    unknown = esc[None]
    assert unknown.confidence < 0.6 and any("צביקה" in f for f in unknown.fix)


def test_one_zone_with_checker_is_marked(ref, settings):
    res = build(ref, settings, [msg("13:51", NOA, "48-51 אבי סרק נועה בדקה c2")])
    assert all(any("C1" in f for f in r.fix) for r in rows_of(res, PATROL) + rows_of(res, SEARCH))


def test_several_people_in_one_check_get_consecutive_minutes(ref, settings):
    res = build(ref, settings, [msg("10:47", AVI, "45 בדיקה לרון, טל c2"),
                                msg("15:20", AVI, "18-20 בדיקה לרון וטל c1")])
    got = [(hm(r.start), hm(r.end), r.comment.split(":")[1].split("-")[0].strip())
           for r in rows_of(res, SEARCH)]
    assert got == [("10:44", "10:45", "Ron Shani"), ("10:45", "10:46", "Tal Peretz"),
                   ("15:18", "15:19", "Ron Shani"), ("15:19", "15:20", "Tal Peretz")]


def test_open_escort_moves_to_another_place(ref, settings):
    res = build(ref, settings, [msg("11:24", DANA, "22 תחילת ליווי רון C1"),
                                msg("11:33", DANA, "32 עוברים לליווי ב C2"),
                                msg("11:37", DANA, "34-35 בדיקה לרון C2")])
    esc = [(r.comment, hm(r.start), hm(r.end)) for r in rows_of(res, ESCORT)]
    assert esc == [("Escort C1 : Ron Shani", "11:22", "11:32"), ("Escort C2 : Ron Shani", "11:32", "11:35")]


def test_end_for_everyone_closes_all_open_escorts(ref, settings):
    res = build(ref, settings, [msg("10:09", DANA, "09 תחילת ליווי רון וטל במחסן"),
                                msg("10:14", DANA, "13 סיום ליווי מחסן לכולם")])
    assert [(hm(r.start), hm(r.end)) for r in rows_of(res, ESCORT)] == [("10:09", "10:13")] * 2
    assert not res.issues or all("כולם" not in i.message for i in res.issues)


def test_continue_escort_after_exit_check_starts_a_new_one(ref, settings):
    res = build(ref, settings, [msg("09:40", AVI, "37 תחילת ליווי רון c1"),
                                msg("09:43", AVI, "42 בדיקה רון c1"),
                                msg("09:48", AVI, "47 המשך ליווי רון c1"),
                                msg("10:29", NOA, "29 בדיקה לרון c1")])
    esc = [(hm(r.start), hm(r.end)) for r in rows_of(res, ESCORT)]
    assert esc == [("09:37", "09:42"), ("09:47", "10:29")]


def test_escort_without_end_closes_at_the_exit_check_in_the_other_zone(ref, settings):
    res = build(ref, settings, [msg("12:21", AVI, "21 תחילת ליווי רון c2"),
                                msg("12:36", AVI, "33-35-c1-בדיקה רון")])
    (r,) = rows_of(res, ESCORT)
    assert (r.comment, hm(r.start), hm(r.end)) == ("Escort C2 : Ron Shani", "12:21", "12:35")
    assert r.flags and not r.fix
