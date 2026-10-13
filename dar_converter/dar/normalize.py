"""Reference lists and name / location normalization.

The reference file (data/reference.yaml, git-ignored) maps the Hebrew names used in
WhatsApp to the English names used in the DAR. Lookups accept Hebrew prefixes
(ל, ו, ה, ב, מ, ש) and - as a last resort - a one-letter typo, which lowers confidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

PREFIXES = "לוהבמש"

# location key -> label used in the DAR comment ("Escort Office : ...")
DEFAULT_LOCATIONS = {
    "C1": ["c1"],
    "C2": ["c2"],
    "Storage": ["מחסן", "נחסן", "מחס"],
    "Office": ["משרד"],
}


@dataclass
class Match:
    name: str
    kind: str            # officer | person
    confidence: float
    via: str             # exact | prefix | fuzzy


@dataclass
class Reference:
    officers: dict[str, dict] = field(default_factory=dict)     # name -> {aliases, priority}
    people: dict[str, dict] = field(default_factory=dict)       # name -> {aliases}
    senders: dict[str, str] = field(default_factory=dict)       # WhatsApp display name -> officer
    locations: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_LOCATIONS))
    _alias: dict[str, list[tuple[str, str]]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_dict(cls, data: dict) -> "Reference":
        ref = cls()
        for i, o in enumerate(data.get("officers", []) or []):
            ref.officers[o["name"]] = {
                "aliases": [str(a) for a in o.get("aliases", [])],
                "priority": o.get("shift_priority", 100 + i),
                "supervisor": bool(o.get("supervisor", False)),
            }
            if o.get("left"):                    # left the team: not matched from that date on
                ref.officers[o["name"]]["left"] = _as_date(o["left"])
        for p in data.get("people", []) or []:
            ref.people[p["name"]] = {"aliases": [str(a) for a in p.get("aliases", [])],
                                     "escort": bool(p.get("escort", True))}
            for key in ("default_location", "default_minutes", "escort_zones"):
                if p.get(key):
                    ref.people[p["name"]][key] = p[key]
        ref.senders = {str(k): v for k, v in (data.get("senders") or {}).items()}
        locs = data.get("locations")
        if locs:
            ref.locations = {k: [str(a).lower() for a in v] for k, v in locs.items()}
        ref._index()
        return ref

    @classmethod
    def load(cls, path: str | Path) -> "Reference":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})

    def to_dict(self) -> dict:
        return {
            "officers": [{"name": n, "aliases": v["aliases"], "shift_priority": v["priority"],
                          **({"supervisor": True} if v.get("supervisor") else {}),
                          **({"left": v["left"].isoformat()} if v.get("left") else {})}
                         for n, v in sorted(self.officers.items(), key=lambda kv: kv[1]["priority"])],
            "senders": dict(self.senders),
            "people": [{"name": n, "aliases": v["aliases"],
                        **({"escort": False} if v.get("escort") is False else {}),
                        **({k: v[k] for k in ("default_location", "default_minutes", "escort_zones")
                            if v.get(k)})}
                       for n, v in self.people.items()],
            "locations": self.locations,
        }

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.to_dict(), fh, allow_unicode=True, sort_keys=False)

    def _index(self) -> None:
        self._alias = {}
        for kind, table in (("officer", self.officers), ("person", self.people)):
            for name, info in table.items():
                for alias in [name, *info["aliases"]]:
                    key = norm_token(alias)
                    if key:
                        self._alias.setdefault(key, [])
                        if (name, kind) not in self._alias[key]:
                            self._alias[key].append((name, kind))

    def add_alias(self, alias: str, name: str, kind: str) -> bool:
        table = self.officers if kind == "officer" else self.people
        if name not in table:
            table[name] = ({"aliases": [], "escort": True} if kind == "person"
                           else {"aliases": [], "priority": 100 + len(table), "supervisor": False})
        if alias in table[name]["aliases"]:
            return False
        table[name]["aliases"].append(alias)
        self._index()
        return True

    # ------------------------------------------------------------------ lookups
    def is_officer(self, name: str | None) -> bool:
        return name in self.officers

    def needs_escort(self, person: str | None) -> bool | None:
        """True for visitors / contractors, False for employees and officers, None if unknown."""
        if person in self.officers:
            return False
        if person in self.people:
            return self.people[person].get("escort", True)
        return None

    def is_supervisor(self, officer: str | None) -> bool:
        return bool(self.officers.get(officer, {}).get("supervisor"))

    def default_supervisor(self) -> str | None:
        """The supervisor with the highest shift priority (Shift 1 when nobody else is seen)."""
        sups = [n for n, v in self.officers.items() if v.get("supervisor")]
        return min(sups, key=self.priority) if sups else None

    def namesakes(self, name: str) -> list[tuple[str, str]]:
        """Other canonical names that share a Hebrew alias with `name` (e.g. two people called גיל)."""
        out = []
        for alias, cands in self._alias.items():
            if any(c[0] == name for c in cands):
                out.extend(c for c in cands if c[0] != name and c not in out)
        return out

    def default_location(self, person: str) -> str | None:
        return self.people.get(person, {}).get("default_location")

    def is_employee(self, person: str | None) -> bool:
        """An employee who needs no escort - and may escort contractors himself."""
        return person in self.people and self.people[person].get("escort", True) is False

    def escort_zones(self, person: str | None) -> list[str] | None:
        """Places where the person needs an escort (the logistics team: only C1 / C2)."""
        z = self.people.get(person, {}).get("escort_zones")
        return [str(x) for x in z] if z else None

    def default_minutes(self, person: str) -> int | None:
        """Usual length of the person's visit (the cleaner: about an hour), used when no exit
        is reported."""
        v = self.people.get(person, {}).get("default_minutes")
        return int(v) if v else None

    def active(self, cand: tuple[str, str], on: date | None) -> bool:
        """False for an officer who had left the team by `on`."""
        name, kind = cand
        left = self.officers.get(name, {}).get("left") if kind == "officer" else None
        return not (left and on and on >= left)

    def priority(self, officer: str) -> int:
        return self.officers.get(officer, {}).get("priority", 999)

    def sender_officer(self, sender: str | None) -> str | None:
        if not sender:
            return None
        if sender in self.senders:
            return self.senders[sender]
        # "נועה - עבודה" -> try the first word(s)
        head = re.split(r"\s+-\s+|\s{2,}", sender)[0]
        m = self.lookup_phrase(head, prefer="officer")
        if m and m.kind == "officer":
            return m.name
        for word in head.split():
            m = self.lookup(word, prefer="officer")
            if m and m.kind == "officer" and m.via == "exact":
                return m.name
        return None

    def _cands(self, key: str, on: date | None) -> list[tuple[str, str]] | None:
        return [c for c in self._alias.get(key, []) if self.active(c, on)] or None

    def lookup(self, token: str, prefer: str | None = None, fuzzy: bool = True,
               on: date | None = None) -> Match | None:
        """Resolve one Hebrew/English token to a canonical name (as of the date `on`)."""
        key = norm_token(token)
        if not key:
            return None
        hit = self._pick(self._cands(key, on), prefer)
        if hit:
            return Match(hit[0], hit[1], 1.0, "exact")
        # strip up to two Hebrew prefix letters: "לרון", "ורון", "ולרון"
        for n in (1, 2):
            if len(key) > n + 1 and all(ch in PREFIXES for ch in key[:n]):
                hit = self._pick(self._cands(key[n:], on), prefer)
                if hit:
                    return Match(hit[0], hit[1], 1.0, "prefix")
        if fuzzy and len(key) >= 4:
            cands = {cand for alias, cands in self._alias.items()
                     if len(alias) >= 3 and one_edit(key, alias) for cand in cands
                     if self.active(cand, on)}
            if len(cands) == 1:
                name, kind = cands.pop()
                return Match(name, kind, 0.7, "fuzzy")
        return None

    def officer_fuzzy(self, token: str, on: date | None = None) -> str | None:
        """An officer's name with a one-letter typo ("יונתם", "עידן", "יש"). Used only where
        the grammar expects an officer (the scanner / checker of a round)."""
        key = norm_token(token)
        if len(key) < 2:
            return None
        found = {name for alias, cands in self._alias.items()
                 if len(alias) >= 3 and one_edit(key, alias)
                 for name, kind in cands if kind == "officer" and self.active((name, kind), on)}
        return found.pop() if len(found) == 1 else None

    def lookup_wildcard(self, token: str, wildcard: str, on: date | None = None) -> Match | None:
        """A name with one unreadable letter ("מנ§ה" -> "מנקה"); Hebrew prefixes allowed."""
        key = norm_token(token)
        for n in (0, 1):
            if n and not (len(key) > 3 and key[0] in PREFIXES):
                continue
            pat = re.compile("^" + re.escape(key[n:]).replace(re.escape(wildcard), ".") + "$")
            found = {c for alias, cands in self._alias.items() if pat.match(alias) for c in cands
                     if self.active(c, on)}
            if len(found) == 1:
                name, kind = found.pop()
                return Match(name, kind, 0.7, "fuzzy")
        return None

    def lookup_phrase(self, phrase: str, prefer: str | None = None,
                      on: date | None = None) -> Match | None:
        """Multi-word aliases such as 'רון שני' or 'צוות ניקיון'."""
        key = norm_token(phrase)
        hit = self._pick(self._cands(key, on), prefer)
        if hit:
            return Match(hit[0], hit[1], 1.0, "exact")
        for n in (1, 2):
            if len(key) > n + 1 and all(ch in PREFIXES for ch in key[:n]):
                hit = self._pick(self._cands(key[n:], on), prefer)
                if hit:
                    return Match(hit[0], hit[1], 1.0, "prefix")
        return None

    def multiword_aliases(self) -> list[str]:
        return sorted((a for a in self._alias if " " in a), key=len, reverse=True)

    @staticmethod
    def _pick(cands: list[tuple[str, str]] | None, prefer: str | None):
        if not cands:
            return None
        if prefer:
            for c in cands:
                if c[1] == prefer:
                    return c
        return cands[0]

    def location(self, token: str) -> str | None:
        key = norm_token(token)
        variants = [key]
        for n in (1, 2):
            if len(key) > n + 2 and all(c in PREFIXES for c in key[:n]):
                variants.append(key[n:])
        for v in variants:
            for label, aliases in self.locations.items():
                if v in (norm_token(a) for a in aliases):
                    return label
        # one-letter typo ("מהמשרס") on Hebrew location words of 4+ letters
        for v in variants:
            for label, aliases in self.locations.items():
                for a in aliases:
                    a = norm_token(a)
                    if len(a) >= 4 and re.fullmatch(r"[\u0590-\u05FF]+", a) and one_edit(v, a):
                        return label
        return None


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def norm_token(text: str) -> str:
    t = text.strip().lower()
    t = t.replace("с", "c").replace("С", "c")     # Cyrillic es typed instead of Latin c
    t = re.sub(r"[\"'`׳״.,:;!?()\[\]*]+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def one_edit(a: str, b: str) -> bool:
    """True when a and b differ by exactly one substitution / insertion / deletion
    or by two neighbouring letters swapped ("גלי" / "גיל")."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    diff = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diff += 1
            j += 1
            if diff > 1:
                return False
    return True
