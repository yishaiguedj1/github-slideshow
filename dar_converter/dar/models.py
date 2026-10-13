"""Plain data classes shared by all pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Actions that come from the WhatsApp group. Alarms / admin notes / night-owl rows
# are entered by the camera company (SOC) and are out of scope.
PATROL = "Patrol: Interior"
SEARCH = "Material Search"
ESCORT = "Escort: Foot"
ASSUMED_POST = "Assumed Post"
OUR_ACTIONS = (PATROL, SEARCH, ESCORT, ASSUMED_POST)

HIGH = 1.0     # read directly from the message
MEDIUM = 0.8   # filled by a documented rule (e.g. zone taken from the closing check)
LOW = 0.4      # ambiguous - goes to the review sheet only


@dataclass
class Message:
    """One WhatsApp message (possibly multi-line)."""
    id: str
    ts: datetime
    sender: str | None
    text: str
    system: bool = False
    edited: bool = False
    deleted: bool = False
    line_no: int = 0

    @property
    def stamp(self) -> str:
        return self.ts.strftime("%d/%m/%Y %H:%M")


@dataclass
class Event:
    """A single fact extracted from one line of a message.

    kind: scan | scan_start | check | escort_start | escort_end | escort_join |
          escort_handover | storage | ignore | unknown
    Times are minutes since midnight of `day` (may exceed 1440 only transiently).
    """
    kind: str
    msg: Message
    line: str
    day: date | None = None
    start: int | None = None
    end: int | None = None
    zone: str | None = None
    actor: str | None = None          # scanner / checker / escorting officer
    partner: str | None = None        # checker of a scan
    subjects: list[str] = field(default_factory=list)  # checked / escorted persons
    confidence: float = HIGH
    notes: list[str] = field(default_factory=list)
    used: bool = False                # consumed while building rows
    inferred: bool = False            # created by a rule, not reported in the chat
    extra_sources: list[Message] = field(default_factory=list)
    info: list[str] = field(default_factory=list)   # documented rule applied (not a warning)
    single_time: bool = False         # the line gave one time, not a range

    def note(self, text: str, confidence: float | None = None) -> None:
        self.notes.append(text)
        if confidence is not None:
            self.confidence = min(self.confidence, confidence)


@dataclass
class Row:
    """One DAR row (columns A-G, K) plus provenance."""
    day: date
    action: str
    officer: str | None
    start: int | None                 # minutes since midnight -> column F
    end: int | None                   # column G
    comment: str | None = None        # column K
    shift: str | None = None          # column A
    d_e_f: tuple[int | None, int | None, int | None] | None = None  # seconds, filled by build
    confidence: float = HIGH
    flags: list[str] = field(default_factory=list)
    sources: list[Message] = field(default_factory=list)
    seq: int = 0                      # creation order, used as sort tie-breaker
    inferred: bool = False            # row that is not reported in the chat at all
    info: list[str] = field(default_factory=list)   # documented rules applied to this row
    fix: list[str] = field(default_factory=list)    # needs a human fix - shown prominently

    def need_fix(self, text: str) -> None:
        if text not in self.fix:
            self.fix.append(text)

    def flag(self, text: str, confidence: float | None = None) -> None:
        if text not in self.flags:
            self.flags.append(text)
        if confidence is not None:
            self.confidence = min(self.confidence, confidence)

    @property
    def g_seconds(self) -> int | None:
        return None if self.end is None else self.end * 60

    def times_seconds(self) -> tuple[int | None, int | None, int | None, int | None]:
        if self.d_e_f is None:
            return (None, None, None, self.g_seconds)
        d, e, f = self.d_e_f
        return (d, e, f, self.g_seconds)


@dataclass
class Issue:
    """A validation finding that is not tied to a single row (or is, via `row`)."""
    day: date
    kind: str
    message: str
    row: Row | None = None
    sources: list[Message] = field(default_factory=list)


def fmt_minutes(m: int | None) -> str:
    if m is None:
        return ""
    return f"{m // 60:02d}:{m % 60:02d}"


def fmt_seconds(s: int | None) -> str:
    if s is None:
        return ""
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
