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


def test_solo_scan_and_following_check_merge(ref, settings):
    res = build(ref, settings, [msg("11:53", NOA, "50-53 נועה סרקה c2"),
                                msg("11:55", DANA, "54-55 בדיקה לנועה C2")])
    (p,), (s,) = rows_of(res, PATROL), rows_of(res, SEARCH)
    assert (p.officer, hm(p.start), hm(p.end)) == ("Noa Bar", "11:50", "11:55")
    assert (s.officer, s.comment) == ("Dana Cohen", "Metal screening C2 : Noa Bar - Declined to sit")


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


def test_roster_priorities_and_assumed_post(ref, settings):
    res = build(ref, settings, [msg("07:46", NOA, "39-42 גיל סרק נועה בדקה c2"),
                                msg("10:10", DANA, "05-08 אבי סרק דנה בדקה c1")])
    ap = [(r.shift, r.officer, hm(r.start), hm(r.end)) for r in rows_of(res, ASSUMED_POST)]
    assert ap == [("Shift 1", "Dana Cohen", "07:00", "19:00"), ("Shift 2", "Avi Levi", "07:00", "19:00"),
                  ("Shift 3", "Noa Bar", "07:00", "19:00"), (None, "Gil Amir", "07:00", "19:00")]
    # Gil is a 4th officer that does not fit a split post -> no shift, flagged, day issue
    gil = [r for r in res.rows if r.officer == "Gil Amir"]
    assert all(r.shift is None and r.flags for r in gil)
    assert any("Gil Amir" in i.message for i in res.issues)
    assert res.rows[0].action == ASSUMED_POST and res.rows[0].d_e_f[0] == 7 * 3600


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


def test_unknown_person_goes_to_review_but_known_one_stays(ref, settings):
    res = build(ref, settings, [msg("15:49", DANA, "49 תחילת ליווי צביקה ורון במשרד"),
                                msg("16:12", DANA, "12 סיום ליווי במשרד")])
    esc = {r.comment: r for r in rows_of(res, ESCORT)}
    assert esc["Escort Office : Ron Shani"].confidence == 1.0
    unknown = esc[None]
    assert unknown.confidence < 0.6 and any("צביקה" in f for f in unknown.flags)
