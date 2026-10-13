"""Deterministic extraction: one message line -> zero or more Events.

Recognised report types (Hebrew, as written in the group):
  scan           "39-42 דנה סרקה נועה בדקה c2", "48-51-c2-דנה סרקה אבי בדק"
  scan_start     "21 תחילת סריקה C2", "42 תחילת סריקה דנה c2"
  check          "44 בדיקה לרון c2", "16 גיל בדק דנה C1"
  escort_start   "09 תחילת ליווי רון c2", "59-טל נכנס c1", "55 ליווי רון וטל במחסן"
  escort_end     "06 סיום ליווי", "53 המנקה יצאה מהמשרד"
  escort_join    "43 רון הצטרף לליווי c1"
  escort_handover "חילוף ליווי טל - c1 - 50", "... והמשך ליווי רון"
  storage        "36 גיל סרק מחסן"  (never becomes a DAR row)
Lines that do not fit are returned as kind="unknown" for review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from .models import HIGH, LOW, MEDIUM, Event, Message
from .normalize import Reference, norm_token

# ---------------------------------------------------------------- vocabulary
SCAN_VERBS = {"סרק", "סרקה", "סרקו", "סדק", "סרקיה"}
SELF_SCAN_VERBS = {"סרקתי"}                 # first person: the sender is the actor
SELF_CHECK_VERBS = {"בדקתי"}
SCAN_NOUNS = {"סריקה", "סריקת", "סריקות"}
CHECK_VERBS = {"בדק", "בדקה", "בדקו"}
CHECK_NOUNS = {"בדיקה", "ובדיקה"}
ESCORT_WORDS = {"ליווי", "ליוי", "לווי", "לליווי", "בליווי", "וליווי", "הליווי", "מליווי"}
START_WORDS = {"תחילת", "תחיל", "תחיחת", "התחלת", "התחלתי"}
END_WORDS = {"סיום", "וסיום"}
HANDOVER_WORDS = {"חילוף", "וחילוף", "המשך", "והמשך", "ממשיך"}
ENTER_WORDS = {"נכנס", "נכנסה", "נכנסו"}
EXIT_WORDS = {"יצא", "יצאה", "יוצא", "יוצאת", "יצאו"}
JOIN_WORDS = {"הצטרף", "הצטרפה", "הצטרפו"}
STOP_WORDS = {"את", "של", "עם", "נוסף", "נוספת", "גם", "ל", "ו", "ב", "ה", "-", "+", "זה", "אני",
              "כניסה", "ויציאה", "לכיוון", "חזר", "וחוזר", "עובר", "עוברים",
              "הוצאתי", "מהמערכת", "מהתוכנה", "מהתכנה"}
REPORT_KINDS = {"scan_verb", "scan_noun", "check_verb", "check_noun", "escort", "start", "end",
                "handover", "enter", "exit", "join"}
IGNORE_PATTERNS = [re.compile(p) for p in (
    r"^הוצאתי מה(תוכנה|מערכת)", r"^יוצאים? ל(צהריים|הפסקה)", r"^נחזור", r"^עוברים ל",
    r"^This message was deleted$", r"^<Media omitted>$", r"null$",
)]

_ZONE = re.compile(r"(?i)(?<![a-z])([cvс])\s?([12])(?!\d)")
_TIME = r"(\d{1,2})(?::(\d{2}))?"
_EXPR = re.compile(rf"(?<![\d:]){_TIME}(?:\s*-\s*{_TIME})?(?![\d:])")
_HEBREW_THEN_ZONE = re.compile(r"([֐-׿])([cCvVсС]\s?[12])")


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
    m = re.fullmatch(r"(?:זה )?(?:סריקות |סריקה )?(?:של )*(?:שעה )?(\d{1,2})(?: 00)?", s)
    if m and 0 <= int(m.group(1)) <= 23:
        return int(m.group(1))
    return None


def preclean(line: str) -> str:
    s = line.replace("–", "-").replace("—", "-").replace("־", "-")
    s = s.replace("*", " ").replace("_", " ")
    s = _HEBREW_THEN_ZONE.sub(r"\1 \2", s)
    s = re.sub(r"(תחילת|סיום)(?=[\u0590-\u05FF])", r"\1 ", s)   # "תחילתמליווי" typo
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

    # ------------------------------------------------------------ public API
    def extract(self, msg: Message) -> list[Event]:
        if msg.system or msg.deleted or not msg.text.strip():
            return []
        events: list[Event] = []
        hour_ctx: int | None = None
        self._anchor = None          # explicit "HH:MM" seen earlier in this message
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
            evs = self.extract_line(msg, line, hour_ctx, sender_officer)
            for e in evs:
                if getattr(e, "_explicit_hour", False) and e.end is not None:
                    self._anchor = e.end
            # a bare name on its own line continues the previous escort line ("וטל")
            if len(evs) == 1 and evs[0].kind == "unknown" and events:
                names = self._names_only(line)
                prev = events[-1]
                if names and prev.kind.startswith("escort"):
                    prev.subjects.extend(n for n in names if n not in prev.subjects)
                    continue
            events.extend(evs)
        return events

    # ------------------------------------------------------------ line grammar
    def extract_line(self, msg: Message, line: str, hour_ctx: int | None,
                     sender_officer: str | None) -> list[Event]:
        clean = preclean(line)
        zones, exprs, words = split_tokens(clean, self.loc_patterns)
        toks = self._classify_words(words)
        kinds = {t[1] for t in toks}
        names = [t for t in toks if t[1] in ("officer", "person", "unknown_name")]

        def ev(kind: str, **kw) -> Event:
            kw.setdefault("day", msg.ts.date())
            e = Event(kind, msg, line, **kw)
            if sender_officer is None and kind != "unknown":
                e.note("שולח לא מוכר ברשימת המאבטחים", MEDIUM)
            return e

        loc_words = [t[2] for t in toks if t[1] == "location"]
        location = loc_words[0] if loc_words else None
        zone = self._pick_zone(zones, location)

        has_escort = "escort" in kinds or "enter" in kinds or "exit" in kinds or "join" in kinds
        has_scan_verb = "scan_verb" in kinds
        has_scan_noun = "scan_noun" in kinds
        has_check_noun = "check_noun" in kinds
        has_check_verb = "check_verb" in kinds

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

        if has_escort:
            return self._escort(msg, line, toks, exprs, zone, location, hour_ctx,
                                sender_officer, has_check_noun, ev)

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
        scanner = sender_officer if scanner == "SELF" else scanner
        checker = sender_officer if checker == "SELF" else checker
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
        if "check_verb" in kinds:                             # "16 גיל בדק דנה C1"
            i = kinds.index("check_verb")
            before = [t for t in toks[:i] if t[1] in ("officer", "unknown_name")]
            after = [t for t in toks[i + 1:] if t[1] in ("officer", "person", "unknown_name")]
            if toks[i][2] == "SELF":                          # "בדקתי את רון"
                before = []
            e.actor = before[-1][2] if before else sender_officer
            subjects = [t[2] for t in after]
        else:                                                 # "44 בדיקה לרון c2"
            i = kinds.index("check_noun")
            after = [t for t in toks[i + 1:] if t[1] in ("officer", "person", "unknown_name")]
            before = [t for t in toks[:i] if t[1] in ("officer", "person", "unknown_name")]
            e.actor = sender_officer
            subjects = [t[2] for t in (after or before)]
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
        if not exprs:
            e.note("בדיקה בלי שעה", LOW)
        return [e]

    def _escort(self, msg, line, toks, exprs, zone, location, hour_ctx, sender_officer,
                has_check_noun, ev) -> list[Event]:
        kinds = [t[1] for t in toks]
        people = [t[2] for t in toks if t[1] in ("person", "unknown_name")]
        officers = [t[2] for t in toks if t[1] == "officer"]
        out: list[Event] = []
        where = zone or location

        # check + end / handover in one line:
        #   "48-50 בדיקה לרון C2 וסיום ליווי", "10:46-47 בדיקה לנועה והמשך ליווי רון"
        if has_check_noun:
            i = kinds.index("check_noun")
            after = [t for t in toks[i + 1:] if t[1] in ("officer", "person", "unknown_name")]
            subj = after[0][2] if after else (people[0] if people else None)
            chk = ev("check", zone=zone, actor=sender_officer, subjects=[subj] if subj else [])
            self._set_times(chk, exprs, msg, hour_ctx)
            if subj is None:
                chk.note("לא צוין את מי בדקו", LOW)
            out.append(chk)
            point = chk.end
            if "handover" in kinds:
                escorted = [p for p in people if p != subj]
                h = ev("escort_handover", zone=where, actor=sender_officer, subjects=escorted,
                       start=chk.start if chk.start is not None else point, day=chk.day)
                h.end = h.start
                if not escorted:
                    h.note("החלפת ליווי בלי שם המלווה - לפי הליווי הפתוח", MEDIUM)
                out.append(h)
            elif "end" in kinds:
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
        elif "end" in kinds or "exit" in kinds:               # "06 סיום ליווי", "המנקה יצאה"
            e = ev("escort_end", zone=where, actor=sender_officer, subjects=people)
        else:                                                 # start / entered / "ליווי רון"
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
                m = self.ref.lookup_phrase(cand) if n > 1 else None
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
        return out

    def _classify(self, w: str) -> tuple[str, str, str | None]:
        k = norm_token(w)
        if k in SCAN_VERBS:
            return (w, "scan_verb", None)
        if k in SELF_SCAN_VERBS:
            return (w, "scan_verb", "SELF")
        if k in SELF_CHECK_VERBS:
            return (w, "check_verb", "SELF")
        if k in SCAN_NOUNS:
            return (w, "scan_noun", None)
        if k in CHECK_VERBS:
            return (w, "check_verb", None)
        if k in CHECK_NOUNS:
            return (w, "check_noun", None)
        if k in ESCORT_WORDS:
            return (w, "escort", None)
        if k in START_WORDS:
            return (w, "start", None)
        if k in END_WORDS:
            return (w, "end", None)
        if k in HANDOVER_WORDS:
            return (w, "handover", None)
        if k in ENTER_WORDS:
            return (w, "enter", None)
        if k in EXIT_WORDS:
            return (w, "exit", None)
        if k in JOIN_WORDS:
            return (w, "join", None)
        if k in STOP_WORDS:
            return (w, "stop", None)
        loc = self.ref.location(k)
        if loc:
            return (w, "location", loc)
        m = self.ref.lookup(k)
        if m:
            return (w, m.kind, m.name)
        if re.fullmatch(r"[֐-׿]{2,}", k):
            return (w, "unknown_name", "?" + _strip_prefix(k))
        return (w, "other", None)

    def _names_only(self, line: str) -> list[str]:
        _, exprs, words = split_tokens(preclean(line), self.loc_patterns)
        if exprs:
            return []
        toks = [self._classify(w) for w in words]
        if toks and all(t[1] in ("person", "officer") for t in toks):
            return [t[2] for t in toks]
        return []

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
        end_m = x.m2 if x.is_range else x.m1
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
        elif getattr(self, "_anchor", None) is not None and \
                (self._anchor // 60) * 60 + end_m <= t_msg + self.tol + 60:
            # "11:30 בדיקה לרון c1 / 25-28 גיל סרק c1" -> same hour as the explicit time
            end = (self._anchor // 60) * 60 + end_m
            if end < self._anchor - 30:
                end += 60
            if end > t_msg + self.tol:
                end -= 60
        else:
            end = (t_msg // 60) * 60 + end_m
            if end > t_msg + self.tol:
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
        if end > t_msg + self.tol and (x.h1 is not None or x.h2 is not None or hour_ctx is not None):
            if t_msg < 6 * 60:
                e.day = msg.ts.date() - timedelta(days=1)
            else:
                e.note("שעה מאוחרת משעת שליחת ההודעה", LOW)
        if end < 0:
            e.day = msg.ts.date() - timedelta(days=1)
            start += 1440
            end += 1440
        if x.is_range and (end - start > 90 or (x.m2 < x.m1 and x.h1 is None and end - start > 20)):
            e.note(f"טווח זמן חריג ({x.text})", LOW)
            end = None
            if x.h1 is None and hour_ctx is None:       # keep the start in the message's hour
                start = (t_msg // 60) * 60 + x.m1
                if start > t_msg + self.tol:
                    start -= 60
        if hour_ctx is None and x.h1 is None and x.h2 is None and end is not None \
                and t_msg - end > 50 and e.day == msg.ts.date():
            e.note("דיווח מאוחר - השעה הוסקה משעת ההודעה", MEDIUM)
        e.single_time = not x.is_range
        if not x.is_range and not single_is_point and e.kind == "check":
            start = end - 1                    # builder lengthens it for contractors
        elif not x.is_range and not single_is_point and e.kind == "scan":
            # one time on a scan line = its start; an average scan takes a few minutes
            start, end = end, end + self.scan_minutes
            if end > t_msg + self.tol:
                start, end = start - self.scan_minutes, start
            e.note(f"נמסרה שעה אחת לסריקה - משך ממוצע {self.scan_minutes} דק'", MEDIUM)
        e.start, e.end = start, end


def _strip_prefix(k: str) -> str:
    return k[1:] if len(k) > 3 and k[0] in "לוהבמש" else k


def extract_all(msgs: list[Message], ref: Reference, future_tolerance: int = 2,
                scan_minutes: int = 3) -> list[Event]:
    ex = Extractor(ref, future_tolerance, scan_minutes)
    out: list[Event] = []
    for m in msgs:
        out.extend(ex.extract(m))
    return out
