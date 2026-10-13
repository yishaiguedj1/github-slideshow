"""Deterministic parser for WhatsApp chat exports (Android and iOS formats).

Each message gets: send time, sender, text (multi-line), and flags for system /
edited / deleted messages. Nothing here interprets the report content.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import Message

# Bidi / invisible marks WhatsApp sprinkles around names and system lines.
_BIDI = re.compile("[‎‏‪-‮⁦-⁩﻿]")
_SPACES = re.compile("[   ]")

_ANDROID = re.compile(
    r"^(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.](?P<y>\d{2,4}),?\s+"
    r"(?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?\s?(?P<ampm>[AaPp]\.?[Mm]\.?)?\s+[-–]\s+(?P<rest>.*)$"
)
_IOS = re.compile(
    r"^\[(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.](?P<y>\d{2,4}),?\s+"
    r"(?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?\s?(?P<ampm>[AaPp]\.?[Mm]\.?)?\]\s+(?P<rest>.*)$"
)

EDITED_MARKERS = ("<This message was edited>", "<ההודעה נערכה>", "<הודעה זו נערכה>")
DELETED_TEXTS = ("This message was deleted", "You deleted this message",
                 "ההודעה נמחקה", "הודעה זו נמחקה", "מחקת את ההודעה הזו")


def clean(text: str) -> str:
    return _SPACES.sub(" ", _BIDI.sub("", text))


def _to_datetime(g: dict, date_order: str) -> datetime:
    a, b, y = int(g["d"]), int(g["m"]), int(g["y"])
    day, month = (a, b) if date_order.upper().startswith("D") else (b, a)
    if y < 100:
        y += 2000
    hour, minute = int(g["H"]), int(g["M"])
    ampm = (g.get("ampm") or "").lower().replace(".", "")
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return datetime(y, month, day, hour, minute, int(g.get("S") or 0))


def _split_sender(rest: str, known_senders: set[str]) -> tuple[str | None, str, bool]:
    """Return (sender, text, is_system).

    System lines ("X added Y", "Messages are end-to-end encrypted") have no
    "sender: " prefix; Android also marks them with a leading LRM mark.
    """
    raw_rest = rest
    rest = clean(rest)
    if raw_rest.startswith("‎"):
        return None, rest, True
    if ": " in rest:
        sender, text = rest.split(": ", 1)
        sender = sender.strip()
        if sender in known_senders or len(sender) <= 60:
            return sender, text, False
    return None, rest, True


def message_id(ts: datetime, sender: str | None, text: str) -> str:
    h = hashlib.sha1(f"{sender}|{text}".encode("utf-8")).hexdigest()[:6]
    return f"{ts:%Y%m%d-%H%M}-{h}"


def parse_lines(lines: Iterable[str], date_order: str = "DMY") -> list[Message]:
    msgs: list[Message] = []
    lines = list(lines)
    # first pass: collect senders of normal messages so system detection is reliable
    senders: set[str] = set()
    for line in lines:
        m = _ANDROID.match(clean(line)) or _IOS.match(clean(line))
        if m and ": " in clean(m.group("rest")) and not m.group("rest").startswith("‎"):
            senders.add(clean(m.group("rest")).split(": ", 1)[0].strip())

    for no, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        probe = line.lstrip("‎‏﻿")
        m = _ANDROID.match(probe) or _IOS.match(probe)
        if not m:
            if msgs:                                  # continuation of a multi-line message
                msgs[-1].text += "\n" + clean(line)
            continue
        g = m.groupdict()
        ts = _to_datetime(g, date_order)
        sender, text, system = _split_sender(g["rest"], senders)
        msgs.append(Message(id="", ts=ts, sender=sender, text=text, system=system, line_no=no))

    seen: Counter[str] = Counter()
    for msg in msgs:
        text = msg.text
        for marker in EDITED_MARKERS:
            if marker in text:
                msg.edited = True
                text = text.replace(marker, "")
        msg.text = text.strip()
        msg.deleted = msg.text in DELETED_TEXTS
        base = message_id(msg.ts, msg.sender, msg.text)
        seen[base] += 1
        msg.id = base if seen[base] == 1 else f"{base}-{seen[base]}"
    return msgs


def parse_file(path: str | Path, date_order: str = "DMY") -> list[Message]:
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return parse_lines(fh, date_order)
