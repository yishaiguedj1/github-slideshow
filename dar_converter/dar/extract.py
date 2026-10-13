"""Deterministic extraction: one message line -> zero or more Events.

Recognised report types (Hebrew, as written in the group):
  scan           "39-42 דנה סרקה נועה בדקה c2", "48-51-c2-דנה סרקה אבי בדק"
  scan_start     "21 תחילת סריקה C2", "42 תחילת סריקה דנה c2"
  check          "44 בדיקה לרון c2", "16 גיל בדק דנה C1"
  escort_start   "09 תחילת ליווי רון c2", "59-טל נכנס c1", "55 ליווי רון וטל במחסן"
  escort_end     "06 סיום ליווי", "53 המנקה יצאה מהמשרד"
  escort_join    "43 רון הצטרף לליווי c1"
  escort_handover "חילוף ליווי טל - c1 - 50", "... והמשך ליווי רון"
  escort_move    "32 עוברים לליווי ב C2"   (the open escort moves to another place)
  storage        "36 גיל סרק מחסן"  (never becomes a DAR row)
Also: "23 רון חזר ל-c2" (escort again), "47-48 כניסה ויציאה רון C1" (escort + exit check),
"15-17 בדיקה לטל C1 דנה" (the officer named last did the check).
Lines that do not fit are returned as kind="unknown" for review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from .models import HIGH, LOW, MEDIUM, Event, Message
from .normalize import PREFIXES, Reference, norm_token, one_edit

# ---------------------------------------------------------------- vocabulary
# (typos seen in the group are listed with the right word: "סרש", "סרקהה", "ליוו", "תחיח" ...)
SCAN_VERBS = {"סרק", "סרקה", "סרקו", "סדק", "סרקיה", "סרש", "סרשה", "סרקהה", "שרק", "שרקה",
              "סורק", "סורקת"}
SELF_SCAN_VERBS = {"סרקתי", "ברקתי"}       # first person: the sender is the actor
SELF_CHECK_VERBS = {"בדקתי"}
SCAN_NOUNS = {"סריקה", "סריקת", "סריקות", "לסרוק"}
CHECK_VERBS = {"בדק", "בדקה", "בדקו", "בודק", "בודקת"}
CHECK_NOUNS = {"בדיקה", "ובדיקה", "בדיקת"}
ESCORT_WORDS = {"ליווי", "ליוי", "לווי", "לליווי", "בליווי", "וליווי", "הליווי", "מליווי",
                "ליוו", "ליווו", "ליויי"}
START_WORDS = {"תחילת", "תחיל", "תחיחת", "תחיח", "התחלת", "התחלתי", "התחיל", "התחילה"}
END_WORDS = {"סיום", "וסיום", "סוף", "וסוף", "סיים", "סיימה", "סיימתי", "מסיים", "הסתיים",
             "הסתיימה"}
HANDOVER_WORDS = {"חילוף", "וחילוף", "המשך", "והמשך", "ממשיך", "ממשיכה", "החלפת", "והחלפת",
                  "החלפה", "והחלפה", "מחליף", "מחליפה"}
ENTER_WORDS = {"נכנס", "נכנסה", "נכנסו", "נכנסת"}
EXIT_WORDS = {"יצא", "יצאה", "יוצא", "יוצאת", "יצאו", "יוצאים"}
JOIN_WORDS = {"הצטרף", "הצטרפה", "הצטרפו", "מצטרף", "מצטרפת", "מצטרפים"}
RETURN_WORDS = {"חזר", "חזרה", "חזרו", "חוזר", "חוזרת", "חוזרים"}      # "23 רון חזר ל-c2"
MOVE_WORDS = {"עוברים", "עובר", "עוברת", "עברנו", "עברו"}              # "32 עוברים לליווי ב C2"
ENTRY_NOUNS = {"כניסה", "וכניסה"}                                       # "כניסה ויציאה רון C1"
EXIT_NOUNS = {"יציאה", "ויציאה"}
OFFICER_HINTS = {"מאבטח", "המאבטח", "מאבטחת", "המאבטחת"}                # "בדיקה לגיל מאבטח"
AFTER_OFFICER_SCAN = {"ברק", "רק"}       # typo of סרק, only right after an officer's name
BEFORE_ESCORT_END = {"סיון"}             # typo of סיום, only right before "ליווי"
STOP_WORDS = {"את", "של", "עם", "נוסף", "נוספת", "גם", "ל", "ו", "ב", "ה", "-", "+", "זה", "אני",
              "לכיוון", "הוצאתי", "מהמערכת", "מהתוכנה", "מהתכנה", "תוכנה", "לתוכנה",
              "הפסקה", "להפסקה", "הפסקת", "צהריים", "לצהריים",
              "מביא", "להביא", "הביא", "משהו", "אוטו", "האוטו", "רכב", "הרכב", "חלק",
              "הולך", "הולכת", "שירותים", "לשירותים", "היא", "הוא", "הם", "מחוץ", "בחוץ",
              "זמני", "זמנית", "בינתיים", "בנתיים", "הכנסת", "ארונות", "אזעקה", "אחרי", "לפני",
              "שכיבה", "מתי", "כולל", "דק", "דקות", "כמה", "עכשיו", "שוב", "בהמשך"}
ALL_WORDS = {"כולם", "לכולם", "הכל"}                                   # "סיום ליווי לכולם"
VOCAB: dict[str, tuple[str, str | None]] = {}
for _words, _kind, _val in (
        (SCAN_VERBS, "scan_verb", None), (SELF_SCAN_VERBS, "scan_verb", "SELF"),
        (SELF_CHECK_VERBS, "check_verb", "SELF"), (SCAN_NOUNS, "scan_noun", None),
        (CHECK_VERBS, "check_verb", None), (CHECK_NOUNS, "check_noun", None),
        (ESCORT_WORDS, "escort", None), (START_WORDS, "start", None), (END_WORDS, "end", None),
        (HANDOVER_WORDS, "handover", None), (ENTER_WORDS, "enter", None),
        (EXIT_WORDS, "exit", None), (JOIN_WORDS, "join", None), (RETURN_WORDS, "return", None),
        (MOVE_WORDS, "move", None), (ENTRY_NOUNS, "entry_noun", None),
        (EXIT_NOUNS, "exit_noun", None), (OFFICER_HINTS, "officer_hint", None),
        (ALL_WORDS, "all", None)):
    for _w in _words:
        VOCAB[_w] = (_kind, _val)
# long words that may carry a one-letter typo ("נכננסה", "לחווי"); short or common-looking
# words (סיום, מסיים ...) are left out on purpose - "מסכים" must not become "מסיים"
FUZZY_VOCAB = {w: VOCAB[w] for w in (
    "ליווי", "לליווי", "בליווי", "וליווי", "הליווי", "מליווי", "נכנסה", "נכנסו", "נכנסת",
    "יוצאת", "הצטרף", "הצטרפה", "הצטרפו", "התחלתי", "התחלת", "תחילת", "סריקה", "סריקות",
    "בדיקה", "ובדיקה", "סרקתי", "בדקתי")}
NO_PREFIX_KINDS = {"handover"}            # "בהמשך היום" is not "המשך ליווי"
REPORT_KINDS = {"scan_verb", "scan_noun", "check_verb", "check_noun", "escort", "start", "end",
                "handover", "enter", "exit", "join", "entry_noun", "exit_noun"}
NAME_KINDS = ("officer", "person", "unknown_name")
IGNORE_PATTERNS = [re.compile(p) for p in (
    r"^הוצאתי מה(תוכנה|מערכת)", r"^יוצאים? ל(צהריים|הפסקה)", r"^נחזור", r"^עוברים ל",
    r"^This message was deleted$", r"^<Media omitted>$", r"null$",
)]
_SIGNATURE = re.compile(r"(?:(?<![A-Za-z])[cvс]\s?[12]|-)\s*-?\s*([\u0590-\u05FF§]+)"
                        r"\s*(?:-?\s*(?<![A-Za-z])[cvс]\s?[12])?\s*$", re.I)
_INLINE_HOUR = re.compile(r"\s*\*?\s*של\s+שעה\s+(\d{1,2})(?::00)?\s*\*?\s*$")
_MOVE_WORD = re.compile(r"(?<![\u0590-\u05FF])[לוהבמש]?(?:" +
                        "|".join(sorted(MOVE_WORDS | RETURN_WORDS, key=len, reverse=True)) +
                        r")(?![\u0590-\u05FF])")

_ZONE = re.compile(r"(?i)(?<![a-z])([cvс])\s?([12])(?!\d)")
_TIME = r"(\d{1,2})(?::(\d{2}))?"
_EXPR = re.compile(rf"(?<![\d:]){_TIME}(?:\s*-\s*{_TIME})?(?![\d:])")
_HEBREW_THEN_ZONE = re.compile(r"([֐-׿])([cCvVсС]\s?[12])")
_ZONE_THEN_HEBREW = re.compile(r"(?<![A-Za-z])([cCvVсС][12])(?=[֐-׿])")


@dataclass
class TimeExpr:
    h1: int | None
    m1: int
    h2: int | None
    m2: int | None
    text: str

    @property
    def is_range(self) -> bool:
        return self.m2 is not None


def is_ignorable(line: str) -> bool:
    return any(p.search(line) for p in IGNORE_PATTERNS)


def hour_header(line: str) -> int | None:
    """'*של שעה 18:00*', 'שעה 7', '——-11:00——', 'סריקה של 14' -> hour."""
    if not re.search(r"של|שעה|[—–\-]{2,}", line):
        return None
    s = re.sub(r"[^֐-׿a-zA-Z0-9: ]", " ", line)
    s = re.sub(r":", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # "שעה 16:00-17:00", "של שעה 10:00-11:" -> the first hour
    m = re.fullmatch(r"(?:(?:זה|מעודכן|עדכון|סריקות|סריקה|של) )*(?:ל?שעה )?(\d{1,2})(?: 00)?"
                     r"(?: \d{1,2}(?: 00)?)?", s)
    if m and 0 <= int(m.group(1)) <= 23:
        return int(m.group(1))
    return None


def preclean(line: str) -> str:
    s = line.replace("–", "-").replace("—", "-").replace("־", "-")
    s = re.sub(r"(?<=[\u0590-\u05FF])\*(?=[\u0590-\u05FF])", "", s)      # "בד*ק"
    s = s.replace("*", " ").replace("_", " ")
    s = _HEBREW_THEN_ZONE.sub(r"\1 \2", s)
    s = _ZONE_THEN_HEBREW.sub(r"\1 ", s)                                  # "C2דנה"
    s = re.sub(r"(תחילת|סיום)(?=[\u0590-\u05FF])", r"\1 ", s)   # "תחילתמליווי" typo
    s = re.sub(r"(בדיקה|סריקה)(?=[\u0590-\u05FF]{2})", r"\1 ", s)   # "בדיקהמרון"
    s = re.sub(r"(?<=[\u0590-\u05FF])\d(?=[\u0590-\u05FF])", "§", s)    # "מנ1ה": typo letter
    if re.match(r"\s*\d", s):                                            # "סרקה דנה בדק0"
        s = re.sub(r"(?<=[\u0590-\u05FF])\d[\u0590-\u05FF]?\s*$", "", s)
    s = re.sub(r"(\d{1,2}):\s+(\d{2})(?!\d)", r"\1:\2", s)              # "13: 28"
    s = re.sub(r"(?<![\d:])(\d{1,2}):(\d{2})-(\d{1,2})-(\d{2})(?![\d:])", r"\1:\2-\3:\4", s)
    s = re.sub(r"(?<![\d:])([01]\d|2[0-3])([0-5]\d)(?![\d:])", r"\1:\2", s)  # "1151" -> 11:51
    return re.sub(r"\s+", " ", s).strip()


def location_patterns(ref: Reference) -> list[tuple[re.Pattern, str]]:
    """Location names that contain digits ("bldg 7") must be removed before reading times."""
    out = []
    for label, aliases in ref.locations.items():
        for a in aliases:
            if label not in ("C1", "C2") and any(ch.isdigit() for ch in a):
                body = r"\s?".join(re.escape(part) for part in a.split())
                out.append((re.compile(rf"(?i)(?<![\w]){body}(?![\w])"), label))
    return out


def split_tokens(line: str, loc_patterns=()) -> tuple[list[str], list[TimeExpr], list[str]]:
    """Return (zones, time expressions, remaining words)."""
    zones = []
    for m in _ZONE.finditer(line):
        zones.append("C" + m.group(2))
    s = _ZONE.sub(" ", line)
    for pat, label in loc_patterns:
        if pat.search(s):
            zones.append(label)
            s = pat.sub(" ", s)
    exprs = []
    for m in _EXPR.finditer(s):
        h1, m1, h2, m2 = m.groups()
        if m1 is None:                       # "44" -> minutes only
            exprs.append(TimeExpr(None, int(h1), None, int(h2) if h2 else None, m.group(0)))
        else:                                # "10:46" or "10:46-47"
            if h2 is not None and m2 is None:
                exprs.append(TimeExpr(int(h1), int(m1), None, int(h2), m.group(0)))
            else:
                exprs.append(TimeExpr(int(h1), int(m1), int(h2) if m2 else None,
                                      int(m2) if m2 else None, m.group(0)))
    s = _EXPR.sub(" ", s)
    s = re.sub(r"[-–—,.:;!?()\[\]|/\\]+", " ", s)
    words = [w for w in s.split() if w]
    return zones, exprs, words


class Extractor:
    def __init__(self, ref: Reference, future_tolerance: int = 2, scan_minutes: int = 3):
        self.ref = ref
        self.tol = future_tolerance
        self.scan_minutes = scan_minutes      # average scan when only one time is given
        self.loc_patterns = location_patterns(ref)
        self._signature: str | None = None
        self._anchor = None
        self._anchor_day = None
        self._on = None              # date of the message: officers who left are not matched

    # ------------------------------------------------------------ public API
    def extract(self, msg: Message) -> list[Event]:
        if msg.system or msg.deleted or not msg.text.strip():
            return []
        events: list[Event] = []
        hour_ctx: int | None = None
        self._anchor = None          # explicit "HH:MM" seen earlier in this message
        self._anchor_day = None      # ... and the day it was given to
        self._on = msg.ts.date()
        sender_officer = self.ref.sender_officer(msg.sender)
        for raw in msg.text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            hh = hour_header(line)
            if hh is not None:
                hour_ctx = hh
                continue
            if is_ignorable(line):
                events.append(Event("ignore", msg, line, day=msg.ts.date()))
                continue
            line_hour = hour_ctx
            m = _INLINE_HOUR.search(line)              # "45-49 ... C2 של שעה 14:00*"
            if m and m.start() > 0 and 0 <= int(m.group(1)) <= 23:
                line_hour = int(m.group(1))
                line = line[:m.start()]
            evs = self.extract_line(msg, line, line_hour, sender_officer)
            for e in evs:
                if getattr(e, "_explicit_hour", False) and e.end is not None:
                    self._anchor, self._anchor_day = e.end, e.day
            if len(evs) == 1 and evs[0].kind == "check" and not evs[0].subjects and events \
                    and events[-1].kind.startswith("escort") and events[-1].subjects \
                    and events[-1].msg is msg:
                evs = [self._check_of_escorted(msg, line, evs[0], events[-1])]
            if len(evs) == 1 and evs[0].kind in ("unknown", "chatter") and events:
                if self._continue_list(msg, line, events, line_hour):
                    continue
            events.extend(evs)
        return events

    @staticmethod
    def _check_of_escorted(msg: Message, line: str, c: Event, esc: Event) -> Event:
        """"41 ליווי רון למחסן" + "+ בדיקה": the escorted people were checked then."""
        e = Event("check", msg, line, day=esc.day, zone=c.zone or esc.zone,
                  actor=c.actor or esc.actor, subjects=[p for p in esc.subjects if p != "*"])
        no_time = "בדיקה בלי שעה - נלקחה שעת שליחת ההודעה" in c.notes
        if no_time and esc.start is not None:
            e.start, e.end = esc.start - 1, esc.start
        else:
            e.start, e.end = c.start, c.end
        e.single_time = True
        for n in c.notes:
            if n not in ("לא צוין את מי בדקו", "בדיקה בלי שעה - נלקחה שעת שליחת ההודעה"):
                e.note(n, MEDIUM)
        return e

    def _continue_list(self, msg: Message, line: str, events: list[Event],
                       hour_ctx: int | None) -> bool:
        """Names on their own line continue the line above:
        an escort ("09 תחילת ליווי רון" / "וטל") or a list of checks
        ("בדקתי את c1" / "רון 1153" / "טל")."""
        _, exprs, words = split_tokens(preclean(line), self.loc_patterns)
        toks = [self._classify(w) for w in words]
        toks = [t for t in toks if t[1] != "stop"]
        if not toks or not all(t[1] in ("person", "officer") for t in toks) or len(exprs) > 1:
            return False
        names = [t[2] for t in toks]
        prev = events[-1]
        if prev.kind.startswith("escort") and not exprs:
            prev.subjects.extend(n for n in names if n not in prev.subjects)
            return True
        if prev.kind != "check" or prev.zone is None:
            return False
        if not prev.subjects:                      # "בדקתי את c1" + "רון 1153"
            e = Event("check", msg, prev.line, day=prev.day, zone=prev.zone, actor=prev.actor,
                      subjects=names)
            if exprs:
                self._set_times(e, exprs, msg, hour_ctx)
            else:
                e.start, e.end, e.single_time = prev.start, prev.end, prev.single_time
                for n in prev.notes:
                    if n != "לא צוין את מי בדקו":
                        e.note(n, MEDIUM)
            events[-1] = e
            return True
        e = Event("check", msg, line, day=prev.day, zone=prev.zone, actor=prev.actor,
                  subjects=names)
        if exprs:
            self._set_times(e, exprs, msg, hour_ctx)
        elif prev.end is not None:
            e.start, e.end, e.single_time = prev.end, prev.end + 1, True
            e.note("שעה משוערת - שורה ברשימת בדיקות בלי שעה", MEDIUM)
        events.append(e)
        return True

    # ------------------------------------------------------------ line grammar
    def extract_line(self, msg: Message, line: str, hour_ctx: int | None,
                     sender_officer: str | None) -> list[Event]:
        clean = preclean(line)
        zones, exprs, words = split_tokens(clean, self.loc_patterns)
        if len(exprs) > 1 and len(exprs[-1].text.strip()) == 1 and clean.endswith(exprs[-1].text.strip()):
            exprs = exprs[:-1]                     # "... גיל בדק  1": a stray digit at the end
        toks = self._classify_words(words)
        sig = _SIGNATURE.search(clean)
        self._signature = norm_token(sig.group(1)) if sig else None   # "... C1 דנה"
        kinds = {t[1] for t in toks}
        dest = None
        if kinds & {"move", "return"}:
            # "22 בדיקה לרון c2 עובר לc1": the zone after the verb is where he goes next
            mv = _MOVE_WORD.search(clean)
            if mv:
                before = ["C" + z.group(2) for z in _ZONE.finditer(clean[:mv.start()])]
                after = ["C" + z.group(2) for z in _ZONE.finditer(clean[mv.end():])]
                if after:
                    dest = after[0]
                    zones = before or after

        def ev(kind: str, **kw) -> Event:
            kw.setdefault("day", msg.ts.date())
            e = Event(kind, msg, line, **kw)
            if sender_officer is None and kind != "unknown":
                e.note("שולח לא מוכר ברשימת המאבטחים", MEDIUM)
            return e

        loc_words = [t[2] for t in toks if t[1] == "location"]
        location = loc_words[0] if loc_words else None
        zone = self._pick_zone(zones, location)

        has_escort = bool(kinds & {"escort", "enter", "exit", "join"}) or \
            bool(exprs and kinds & {"entry_noun", "exit_noun"})     # "יציאה של רון" in a question
        has_scan_verb = "scan_verb" in kinds
        has_scan_noun = "scan_noun" in kinds
        has_check_noun = "check_noun" in kinds
        has_check_verb = "check_verb" in kinds
        moving = bool(kinds & {"move", "return"}) and not (
            has_scan_verb or has_scan_noun or has_check_noun or has_check_verb)

        # storage scans / checks never become rows
        if location == "Storage" and not has_escort and (has_scan_verb or has_scan_noun
                                                         or has_check_verb or has_check_noun):
            e = ev("storage", zone="Storage")
            self._set_times(e, exprs, msg, hour_ctx)
            actor = self._name_before(toks, ("scan_verb", "check_verb"))
            e.actor = sender_officer if actor in (None, "SELF") else actor
            return [e]

        if len(exprs) > 1:
            e = ev("unknown")
            e.note("יותר מביטוי זמן אחד בשורה", LOW)
            return [e]

        if has_escort or moving:
            if moving and not exprs and not has_escort:
                return [ev("ignore")]                  # "עוברים לC1" - the next line has the time
            return self._escort(msg, line, toks, exprs, zone, location, hour_ctx,
                                sender_officer, has_check_noun, ev, dest)

        if has_scan_verb or has_scan_noun:
            return self._scan(toks, exprs, zone, msg, hour_ctx, sender_officer, ev)

        if has_check_noun or has_check_verb:
            return self._check(toks, exprs, zone, msg, hour_ctx, sender_officer, ev)

        if not exprs and not (kinds & REPORT_KINDS):
            return [ev("chatter")]
        e = ev("unknown")
        e.note("שורה שלא זוהתה", LOW)
        return [e]

    # ------------------------------------------------------------ report types
    def _scan(self, toks, exprs, zone, msg, hour_ctx, sender_officer, ev) -> list[Event]:
        kinds = [t[1] for t in toks]
        if "start" in kinds:                                  # "21 תחילת סריקה C2"
            e = ev("scan_start", zone=zone)
            self._set_times(e, exprs, msg, hour_ctx, single_is_point=True)
            officers = [t for t in toks if t[1] == "officer"]
            e.actor = officers[0][2] if officers else sender_officer
            if not exprs:
                e.start = e.end = self._msg_minutes(e, msg)
                e.note("תחילת סריקה בלי שעה - נלקחה שעת ההודעה", MEDIUM)
            return [e]

        e = ev("scan", zone=zone)
        scanner = self._name_before(toks, ("scan_verb",))
        checker = self._name_before(toks, ("check_verb",))
        scanner = sender_officer if scanner == "SELF" else self._officer_slot(scanner, e)
        checker = sender_officer if checker == "SELF" else self._officer_slot(checker, e)
        if scanner is None:
            # "30-35 סריקה C1 דנה" / "09-12 סריקה c2" / "00-04 סריקה C2 דנה ונועה"
            officers = [t[2] for t in toks if t[1] == "officer"]
            if len(officers) == 1:
                scanner = officers[0]
            elif not officers:
                scanner = sender_officer
                e.note("לא צוין מי סרק - נלקח השולח", MEDIUM)
            else:
                e.note("כמה מאבטחים בלי פועל - לא ברור מי סרק ומי בדק", LOW)
        e.actor = scanner
        e.partner = checker if checker != scanner else None
        if scanner and scanner.startswith("?"):
            e.note(f"שם לא מוכר: {scanner[1:]}", LOW)
        if checker and checker.startswith("?"):
            e.note(f"שם לא מוכר: {checker[1:]}", LOW)
        if zone is None:
            e.note("לא צוין אזור (C1/C2)", MEDIUM)
        self._set_times(e, exprs, msg, hour_ctx)
        if not exprs:
            e.note("סריקה בלי שעות", LOW)
        elif e.end is None or e.start is None:
            e.note("סריקה בלי שעת סיום", LOW)
        return [e]

    def _check(self, toks, exprs, zone, msg, hour_ctx, sender_officer, ev) -> list[Event]:
        e = ev("check", zone=zone)
        kinds = [t[1] for t in toks]
        noun_first = "check_noun" in kinds and (
            "check_verb" not in kinds or kinds.index("check_noun") < kinds.index("check_verb"))
        if noun_first:                                        # "44 בדיקה לרון c2"
            i = kinds.index("check_noun")
            tail = []
            for t in toks[i + 1:]:
                if t[1] in ("move", "return", "join", "exit", "enter"):
                    break                                     # "... עובר ומצטרף לגיל ב C2"
                tail.append(t)
            after = [t for t in tail if t[1] in NAME_KINDS]
            before = [t for t in toks[:i] if t[1] in NAME_KINDS]
            e.actor = sender_officer
            tail_kinds = [t[1] for t in tail]
            if "check_verb" in tail_kinds:
                # "33-36 בדיקה לטל C1 גיל בדק": the name before the verb did the check
                j = tail_kinds.index("check_verb")
                names = [t for t in tail[:j] if t[1] in NAME_KINDS]
                who = self._officer_of(names[-1]) if names and tail[j][2] != "SELF" else None
                if who:
                    e.actor, after = who, names[:-1]
            elif len(after) >= 2 and norm_token(after[-1][0]) == self._signature:
                # "15-17 בדיקה לטל C1 דנה": an officer's name after the zone signs the check
                who = self._officer_of(after[-1], bare=True)
                if who:
                    e.actor, after = who, after[:-1]
                    if who != sender_officer:
                        e.note(f"הבודק ({who}) נלקח מהשם בסוף השורה", MEDIUM)
            subjects = [t[2] for t in (after or before)]
        else:                                                 # "16 גיל בדק דנה C1"
            i = kinds.index("check_verb")
            before = [t for t in toks[:i] if t[1] in ("officer", "unknown_name")]
            after = [t for t in toks[i + 1:] if t[1] in NAME_KINDS]
            if toks[i][2] == "SELF":                          # "בדקתי את רון"
                before = []
            e.actor = self._officer_slot(before[-1][2], e) if before else sender_officer
            subjects = [t[2] for t in after]
        e.subjects = list(dict.fromkeys(subjects))
        if not e.subjects:
            e.note("לא צוין את מי בדקו", LOW)
        for s in e.subjects:
            # a namesake employee ("גיל") is resolved later from the day's context
            if s == e.actor and not any(k == "person" for _, k in self.ref.namesakes(s)):
                e.note("הבודק והנבדק אותו אדם - כנראה אדם אחר עם אותו שם", LOW)
        if len(e.subjects) > 1:
            e.note("כמה נבדקים בשורה אחת", MEDIUM)
        if e.actor is None:
            e.note("לא ידוע מי בדק", LOW)
        self._set_times(e, exprs, msg, hour_ctx)
        if not exprs:                                         # "בדיקה לרון c1" (sent 11:11)
            e.end = self._msg_minutes(e, msg)
            e.start, e.single_time = e.end - 1, True
            e.note("בדיקה בלי שעה - נלקחה שעת שליחת ההודעה", MEDIUM)
        return [e]

    def _escort(self, msg, line, toks, exprs, zone, location, hour_ctx, sender_officer,
                has_check_noun, ev, dest=None) -> list[Event]:
        out = self._escort_events(msg, line, toks, exprs, zone, location, hour_ctx,
                                  sender_officer, has_check_noun, ev, dest)
        # an employee may escort contractors himself ("37 תחילת ליווי תום c2",
        # "רון נכנס עם תום לc2"): only escorts done by the security team are written
        for i, e in enumerate(out):
            emp = [p for p in e.subjects if self.ref.is_employee(p)]
            if e.kind.startswith("escort") and emp:
                out[i] = Event("ignore", msg, line, day=e.day,
                               notes=[f"ליווי של העובד {emp[0]} - לא נרשם ב-DAR"])
        return out

    def _escort_events(self, msg, line, toks, exprs, zone, location, hour_ctx, sender_officer,
                       has_check_noun, ev, dest=None) -> list[Event]:
        orig = toks
        toks = self._escorted_namesakes(toks)
        kinds = [t[1] for t in toks]
        people = [t[2] for t in toks if t[1] in ("person", "unknown_name")]
        if not people and "all" in kinds:
            people = ["*"]                                   # "סיום ליווי לכולם"

        officers = [t[2] for t in toks if t[1] == "officer"]
        out: list[Event] = []
        where = dest or zone or location

        if "entry_noun" in kinds and "exit_noun" in kinds and exprs and exprs[0].is_range \
                and not has_check_noun:
            # "47-48 כניסה ויציאה רון C1": escorted in and out -> escort + exit check
            st = ev("escort_start", zone=where, actor=sender_officer, subjects=people)
            self._set_times(st, exprs, msg, hour_ctx, single_is_point=True)
            chk = ev("check", zone=zone, actor=sender_officer, subjects=list(people), day=st.day)
            chk.start = None if st.end is None else st.end - 1
            chk.end, chk.single_time = st.end, True
            if not people:
                st.note("לא צוין מי מלווה", LOW)
            return [st, chk]
        moving_all = people == ["*"] and not set(kinds) & {"end", "exit", "exit_noun"}
        if ("move" in kinds or moving_all) and not set(kinds) & {"end", "handover", "join"} \
                and not has_check_noun:
            # "32 עוברים לליווי ב C2": the open escort continues in another place
            e = ev("escort_move", zone=where, actor=sender_officer, subjects=people)
            self._set_times(e, exprs, msg, hour_ctx, single_is_point=True)
            if where is None:
                e.note("לא צוין לאן עבר הליווי", LOW)
            return [e]

        # check + end / handover in one line:
        #   "48-50 בדיקה לרון C2 וסיום ליווי", "10:46-47 בדיקה לנועה והמשך ליווי רון"
        if has_check_noun:
            # the checked name keeps its first reading ("בדיקה לעומר והחלפת ליווי" may be the
            # officer); the builder decides between namesakes from the day's context
            i = kinds.index("check_noun")
            after = [j for j in range(i + 1, len(orig)) if orig[j][1] in NAME_KINDS]
            subj = orig[after[0]][2] if after else (people[0] if people else None)
            people = [t[2] for j, t in enumerate(toks)
                      if t[1] in ("person", "unknown_name") and not (after and j == after[0])]
            chk = ev("check", zone=zone, actor=sender_officer, subjects=[subj] if subj else [])
            self._set_times(chk, exprs, msg, hour_ctx)
            if subj is None:
                chk.note("לא צוין את מי בדקו", LOW)
            out.append(chk)
            point = chk.end
            esc_i = kinds.index("escort") if "escort" in kinds else None
            plain = not set(kinds) & {"handover", "end", "exit", "exit_noun", "join"}
            if esc_i is not None and esc_i < i and plain and subj:
                # "12-26 ליווי ובדיקה לרון בc2": escorted over the range, checked at the end;
                # "תחילת ליווי ובדיקה לרון" - the check is on the way in and comes first
                escorted = toks[after[0]][2] if after else subj     # the visitor namesake
                st = ev("escort_start", zone=where, actor=sender_officer, subjects=[escorted],
                        start=chk.start, end=chk.start, day=chk.day)
                if "start" in kinds:
                    return [chk, st]
                if not (exprs and exprs[0].is_range):
                    # "45 ליווי רון למחסן + בדיקה": checked on the way, escorted from then on
                    st.start = st.end = chk.end
                    return [chk, st]
                if chk.start is not None and chk.end is not None and chk.end - chk.start > 2:
                    chk.start = chk.end - 1          # a long escort: the exit check is the last minute
                return [st, chk]
            if esc_i is not None and esc_i > i and plain:
                # "13 בדיקה לטל וליווי לרון בc2": one person checked, another escorted from now
                escorted = [t[2] for t in toks[esc_i + 1:] if t[1] in ("person", "unknown_name")]
                if escorted:
                    out.append(ev("escort_start", zone=where, actor=sender_officer, subjects=escorted,
                                  start=chk.start, end=chk.start, day=chk.day))
                    return out
            if "handover" in kinds:
                escorted = list(people)
                h = ev("escort_handover", zone=where, actor=sender_officer, subjects=escorted,
                       start=chk.start if chk.start is not None else point, day=chk.day)
                h.end = h.start
                if not escorted:
                    h.note("החלפת ליווי בלי שם המלווה - לפי הליווי הפתוח", MEDIUM)
                out.append(h)
            elif "end" in kinds or "exit_noun" in kinds:
                end = ev("escort_end", zone=where, actor=sender_officer,
                         subjects=[subj] if subj and subj not in officers else people,
                         start=point, end=point, day=chk.day)
                out.append(end)
            return out

        if "join" in kinds:                                   # "43 רון הצטרף לליווי c1"
            e = ev("escort_join", zone=where, actor=sender_officer, subjects=people)
        elif "handover" in kinds:                             # "חילוף ליווי טל - c1 - 50"
            e = ev("escort_handover", zone=where, actor=sender_officer, subjects=people)
            if len(officers) > 1:
                e.note("החלפת ליווי בין מאבטחים - לבדוק מי ממשיך", MEDIUM)
        elif set(kinds) & {"end", "exit", "exit_noun"}:          # "06 סיום ליווי", "המנקה יצאה"
            e = ev("escort_end", zone=where, actor=sender_officer, subjects=people)
        else:                                                 # start / entered / "רון חזר ל-c2"
            e = ev("escort_start", zone=where, actor=sender_officer, subjects=people)
            if officers and "start" in kinds and len(officers) == 1 and not people:
                e.note("ליווי של מאבטח? לבדוק", LOW)
        self._set_times(e, exprs, msg, hour_ctx, single_is_point=True)
        if not exprs:
            e.start = e.end = self._msg_minutes(e, msg)
            e.note("בלי שעה בהודעה - נלקחה שעת שליחת ההודעה", MEDIUM)
        if e.kind in ("escort_start", "escort_join") and not e.subjects:
            e.note("לא צוין מי מלווה", LOW)
        out.append(e)
        return out

    # ------------------------------------------------------------ helpers
    def _classify_words(self, words: list[str]) -> list[tuple[str, str, str | None]]:
        """-> list of (word, kind, value). Multi-word aliases are joined first."""
        out: list[tuple[str, str, str | None]] = []
        i = 0
        multi = self.ref.multiword_aliases()
        while i < len(words):
            joined = None
            for a in multi:
                n = a.count(" ") + 1
                cand = " ".join(words[i:i + n])
                m = self.ref.lookup_phrase(cand, on=self._on) if n > 1 else None
                if m and norm_token(cand).endswith(a):
                    joined = (cand, m, n)
                    break
            if joined:
                cand, m, n = joined
                out.append((cand, m.kind, m.name))
                i += n
                continue
            out.append(self._classify(words[i]))
            i += 1
        # typos that depend on the neighbours: "אבי ברק מחסן" (סרק), "סיון ליווי" (סיום);
        # "בדיקה לגיל מאבטח" - the officer, not a namesake
        for i, (w, kind, val) in enumerate(out):
            k = norm_token(w)
            if kind in ("other", "unknown_name") and k in AFTER_OFFICER_SCAN and i \
                    and out[i - 1][1] == "officer":
                out[i] = (w, "scan_verb", None)
            elif kind in ("other", "unknown_name", "person") and k in BEFORE_ESCORT_END \
                    and i + 1 < len(out) and out[i + 1][1] == "escort":
                out[i] = (w, "end", None)
            elif kind == "officer_hint" and i and out[i - 1][1] in ("person", "officer"):
                m = self.ref.lookup(out[i - 1][0], prefer="officer", fuzzy=False, on=self._on)
                if m and m.kind == "officer":
                    out[i - 1] = (out[i - 1][0], "officer", m.name)
        return out

    def _classify(self, w: str) -> tuple[str, str, str | None]:
        k = norm_token(w)
        if k in VOCAB:
            return (w, *VOCAB[k])
        if k in STOP_WORDS:
            return (w, "stop", None)
        loc = self.ref.location(k)
        if loc:
            return (w, "location", loc)
        m = self.ref.lookup(k, fuzzy=False, on=self._on)
        if m:
            return (w, m.kind, m.name)
        if len(k) > 2 and k[0] in PREFIXES:                 # "לסריקה", "בסיום", "מבחוץ"
            if k[1:] in VOCAB and VOCAB[k[1:]][0] not in NO_PREFIX_KINDS:
                return (w, *VOCAB[k[1:]])
            if k[1:] in STOP_WORDS:
                return (w, "stop", None)
        if len(k) >= 5:                                      # "נכננסה", "לחווי"
            hits = {v for word, v in FUZZY_VOCAB.items() if one_edit(k, word)}
            if len(hits) == 1:
                return (w, *hits.pop())
        if "§" in k:                                         # "מנ1ה": one unreadable letter
            m = self.ref.lookup_wildcard(k, "§", on=self._on)
            if m:
                return (w, m.kind, m.name)
        m = self.ref.lookup(k, on=self._on)
        if m:
            return (w, m.kind, m.name)
        if re.fullmatch(r"[֐-׿§]{2,}", k):
            return (w, "unknown_name", "?" + _strip_prefix(k))
        return (w, "other", None)

    def _officer_slot(self, name: str | None, e: Event) -> str | None:
        """An unknown name where only an officer fits (scanner / checker): accept a one-letter
        typo of an officer's name ("יונתם", "עידן", "יש")."""
        if name and name.startswith("?"):
            o = self.ref.officer_fuzzy(name[1:], on=self._on)
            if o:
                e.info.append(f"'{name[1:]}' זוהה כ-{o} (שגיאת כתיב)")
                return o
        return name

    def _officer_of(self, tok, bare: bool = False) -> str | None:
        """The officer a name token stands for. bare=True: only a name written without a
        Hebrew prefix ("דנה", not "לדנה" - that one is a checked person)."""
        word, kind, val = tok
        if kind == "unknown_name":
            return self.ref.officer_fuzzy(val[1:], on=self._on)
        m = self.ref.lookup(word, prefer="officer", fuzzy=False, on=self._on)
        if m and m.kind == "officer" and (not bare or m.via == "exact"):
            return m.name
        return None

    def _escorted_namesakes(self, toks):
        """In an escort line a name shared by an officer and an escorted visitor ("עומר") is
        the visitor - officers are not escorted - unless the officer is the one who acts
        ("עומר סיים ליווי", "עומר ממשיך") or is called a guard ("עומר המאבטח")."""
        kinds = [t[1] for t in toks]
        # "חילוף אבי ועומר בליווי רון": in a hand-over the names before "ליווי" are officers
        first_escort = kinds.index("escort") if "handover" in kinds and "escort" in kinds else -1
        out = []
        for i, t in enumerate(toks):
            if t[1] == "officer" and i > first_escort:
                nxt = kinds[i + 1] if i + 1 < len(toks) else None
                visitors = [n for n, k in self.ref.namesakes(t[2])
                            if k == "person" and self.ref.needs_escort(n)]
                signature = i == len(toks) - 1 and i > 0 and \
                    norm_token(t[0]) == self._signature            # "... c1 - עומר"
                if visitors and not signature and nxt not in (
                        "end", "handover", "officer_hint", "scan_verb", "check_verb"):
                    out.append((t[0], "person", visitors[0]))
                    continue
            out.append(t)
        return out

    @staticmethod
    def _name_before(toks, verb_kinds) -> str | None:
        for i, t in enumerate(toks):
            if t[1] in verb_kinds:
                if t[2] == "SELF":
                    return "SELF"
                for j in range(i - 1, -1, -1):
                    if toks[j][1] in ("officer", "unknown_name"):
                        return toks[j][2]
                    if toks[j][1] in ("scan_verb", "check_verb"):
                        break
                return None
        return None

    @staticmethod
    def _pick_zone(zones: list[str], location: str | None) -> str | None:
        z = list(dict.fromkeys(zones))
        if len(z) == 1:
            return z[0]
        if len(z) > 1:
            return None
        return location if location not in (None, "C1", "C2") else None

    # ------------------------------------------------------------ time resolution
    def _msg_minutes(self, e: Event, msg: Message) -> int:
        e.day = msg.ts.date()
        return msg.ts.hour * 60 + msg.ts.minute

    def _set_times(self, e: Event, exprs: list[TimeExpr], msg: Message, hour_ctx: int | None,
                   single_is_point: bool = False) -> None:
        """Resolve minute-only times against the message time (or an hour header).

        Ranges become start/end. A single minute is a 1-minute action ending then
        ("44 בדיקה" -> 43-44), except escort / scan-start points (start=end).
        """
        e.day = msg.ts.date()
        if not exprs:
            return
        x = exprs[0]
        e._explicit_hour = x.h1 is not None or x.h2 is not None
        t_msg = msg.ts.hour * 60 + msg.ts.minute
        # an edited message keeps its first send time, while the text may report the
        # next minutes ("50 תחילת ליווי" edited into a message sent at :47)
        tol = max(self.tol, 15) if msg.edited else self.tol
        end_m = x.m2 if x.is_range else x.m1
        anchored_day = None
        # ---- end time
        if x.h2 is not None:
            end = x.h2 * 60 + end_m
        elif x.h1 is not None:
            end = x.h1 * 60 + end_m
            if x.is_range and end_m < x.m1:
                end += 60
        elif hour_ctx is not None:
            end = hour_ctx * 60 + end_m
            if x.is_range and end_m < x.m1:
                end += 60
        elif getattr(self, "_anchor", None) is not None and (
                self._anchor_day not in (None, msg.ts.date())
                or (self._anchor // 60) * 60 + end_m <= t_msg + tol + 60):
            # "11:30 בדיקה לרון c1 / 25-28 גיל סרק c1" -> same hour as the explicit time
            end = (self._anchor // 60) * 60 + end_m
            if end < self._anchor - 30:
                end += 60
            if self._anchor_day not in (None, msg.ts.date()):
                anchored_day = self._anchor_day      # the rest of yesterday's evening report
            elif end > t_msg + tol:
                end -= 60
        else:
            end = (t_msg // 60) * 60 + end_m
            if end > t_msg + tol:
                end -= 60
        # ---- start time
        if x.is_range:
            if x.h1 is not None:
                start = x.h1 * 60 + x.m1
            else:
                start = (end // 60) * 60 + x.m1
                if x.m1 > end_m:
                    start -= 60
        else:
            start = end
        # ---- day attribution (late report after midnight, "*של שעה 18:00*" at 00:18)
        if anchored_day is not None:
            e.day = anchored_day
        elif end > t_msg + tol and (x.h1 is not None or x.h2 is not None or hour_ctx is not None):
            if t_msg < 6 * 60:
                e.day = msg.ts.date() - timedelta(days=1)
            elif t_msg < 10 * 60 and end >= 16 * 60:
                # "18:46-49-c2-..." sent at 07:46: yesterday's last round, reported in the morning
                e.day = msg.ts.date() - timedelta(days=1)
                e.note("דיווח של אתמול בערב שנשלח בבוקר", MEDIUM)
            else:
                e.note("שעה מאוחרת משעת שליחת ההודעה", LOW)
        if end < 0:
            e.day = msg.ts.date() - timedelta(days=1)
            start += 1440
            end += 1440
        if x.is_range and x.h1 is None and x.h2 is None and x.m2 < x.m1 and end - start > 20 \
                and e.kind in ("scan", "check", "storage"):
            fixed = self._fix_reversed(x, e.kind)          # "49-46" / "42-25"
            if fixed is not None:
                self._set_times(e, [fixed], msg, hour_ctx, single_is_point)
                e.note(f"טווח הפוך בצ'אט ({x.text.strip()}) - נרשם {fixed.m1:02d}-{fixed.m2:02d}",
                       MEDIUM)
                return
        if x.is_range and (end - start > 90 or (x.m2 < x.m1 and x.h1 is None and end - start > 20
                                                and not e.kind.startswith("escort"))):
            e.note(f"טווח זמן חריג ({x.text})", LOW)
            end = None
            if x.h1 is None and hour_ctx is None:       # keep the start in the message's hour
                start = (t_msg // 60) * 60 + x.m1
                if start > t_msg + tol:
                    start -= 60
        if hour_ctx is None and x.h1 is None and x.h2 is None and end is not None \
                and t_msg - end > 50 and e.day == msg.ts.date():
            e.note("דיווח מאוחר - השעה הוסקה משעת ההודעה", MEDIUM)
        e.single_time = not x.is_range
        if not x.is_range and not single_is_point and e.kind == "check":
            start = end - 1                    # builder lengthens it for contractors
        elif not x.is_range and not single_is_point and e.kind == "scan":
            # one time on a scan line = its start ("20 סריקה בc2" -> 20-23, as in the DAR)
            start, end = end, end + self.scan_minutes
            e.note(f"נמסרה שעה אחת לסריקה - משך ממוצע {self.scan_minutes} דק'", MEDIUM)
        e.start, e.end = start, end

    def _fix_reversed(self, x: TimeExpr, kind: str) -> TimeExpr | None:
        """A reversed minute range: swapped ("49-46" -> 46-49) or a typo in the tens of the
        end ("42-25" -> 42-45). The reading whose length is closest to a usual scan (or
        check) wins - this matched the manual entries in 8 of 9 cases."""
        target = 1 if kind == "check" else self.scan_minutes
        cands = []
        swap = x.m1 - x.m2
        if 1 <= swap <= 15:
            cands.append((abs(swap - target), TimeExpr(None, x.m2, None, x.m1, x.text)))
        typo = ((x.m2 % 10) - (x.m1 % 10)) % 10
        if typo >= 1 and x.m1 + typo <= 59:
            cands.append((abs(typo - target), TimeExpr(None, x.m1, None, x.m1 + typo, x.text)))
        return min(cands, key=lambda c: c[0])[1] if cands else None


def _strip_prefix(k: str) -> str:
    """An unknown name keeps its first letter unless it is ל / ו ("לטל", "וטל"):
    names such as מאיה or בועז start with other prefix letters."""
    return k[1:] if len(k) > 3 and k[0] in "לו" else k


def extract_all(msgs: list[Message], ref: Reference, future_tolerance: int = 2,
                scan_minutes: int = 3) -> list[Event]:
    ex = Extractor(ref, future_tolerance, scan_minutes)
    out: list[Event] = []
    for m in msgs:
        out.extend(ex.extract(m))
    return out
