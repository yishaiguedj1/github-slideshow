"""Reference lists and name / location normalization.

The reference file (data/reference.yaml, git-ignored) maps the Hebrew names used in
WhatsApp to the English names used in the DAR. Lookups accept Hebrew prefixes
(ל, ו, ה, ב, מ, ש) and - as a last resort - a one-letter typo, which lowers confidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PREFIXES = "לוהבמש"

# location key -> label used in the DAR comment ("Escort Office : ...")
DEFAULT_LOCATIONS = {
    "C1": ["c1"],
    "C2": ["c2"],
    "Storage": ["מחסן", "נחסן", "מחס"],
    "Office": ["משרד"],
    "TLV13": ["tlv13", "tlv 13"],
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
            }
        for p in data.get("people", []) or []:
            ref.people[p["name"]] = {"aliases": [str(a) for a in p.get("aliases", [])]}
            if p.get("default_location"):
                ref.people[p["name"]]["default_location"] = p["default_location"]
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
            "officers": [{"name": n, "aliases": v["aliases"], "shift_priority": v["priority"]}
                         for n, v in sorted(self.officers.items(), key=lambda kv: kv[1]["priority"])],
            "senders": dict(self.senders),
            "people": [{"name": n, "aliases": v["aliases"],
                        **({"default_location": v["default_location"]} if v.get("default_location") else {})}
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
            table[name] = {"aliases": []} if kind == "person" else {"aliases": [], "priority": 100 + len(table)}
        if alias in table[name]["aliases"]:
            return False
        table[name]["aliases"].append(alias)
        self._index()
        return True

    # ------------------------------------------------------------------ lookups
    def is_officer(self, name: str | None) -> bool:
        return name in self.officers

    def default_location(self, person: str) -> str | None:
        return self.people.get(person, {}).get("default_location")

    def priority(self, officer: str) -> int:
        return self.officers.get(officer, {}).get("priority", 999)

    def sender_officer(self, sender: str | None) -> str | None:
        if not sender:
            return None
        if sender in self.senders:
            return self.senders[sender]
        # "נועה - עבודה - Google" -> try the first word(s)
        head = re.split(r"\s+-\s+|\s{2,}", sender)[0]
        m = self.lookup_phrase(head, prefer="officer")
        if m and m.kind == "officer":
            return m.name
        for word in head.split():
            m = self.lookup(word, prefer="officer")
            if m and m.kind == "officer" and m.via == "exact":
                return m.name
        return None

    def lookup(self, token: str, prefer: str | None = None, fuzzy: bool = True) -> Match | None:
        """Resolve one Hebrew/English token to a canonical name."""
        key = norm_token(token)
        if not key:
            return None
        hit = self._pick(self._alias.get(key), prefer)
        if hit:
            return Match(hit[0], hit[1], 1.0, "exact")
        # strip up to two Hebrew prefix letters: "לרון", "ורון", "ולרון"
        for n in (1, 2):
            if len(key) > n + 1 and all(ch in PREFIXES for ch in key[:n]):
                hit = self._pick(self._alias.get(key[n:]), prefer)
                if hit:
                    return Match(hit[0], hit[1], 1.0, "prefix")
        if fuzzy and len(key) >= 4:
            cands = {cand for alias, cands in self._alias.items()
                     if len(alias) >= 3 and _one_edit(key, alias) for cand in cands}
            if len(cands) == 1:
                name, kind = cands.pop()
                return Match(name, kind, 0.7, "fuzzy")
        return None

    def lookup_phrase(self, phrase: str, prefer: str | None = None) -> Match | None:
        """Multi-word aliases such as 'בן דוד' or 'צוות ניקיון'."""
        key = norm_token(phrase)
        hit = self._pick(self._alias.get(key), prefer)
        if hit:
            return Match(hit[0], hit[1], 1.0, "exact")
        for n in (1, 2):
            if len(key) > n + 1 and all(ch in PREFIXES for ch in key[:n]):
                hit = self._pick(self._alias.get(key[n:]), prefer)
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
                    if len(a) >= 4 and re.fullmatch(r"[\u0590-\u05FF]+", a) and _one_edit(v, a):
                        return label
        return None


def norm_token(text: str) -> str:
    t = text.strip().lower()
    t = t.replace("с", "c").replace("С", "c")     # Cyrillic es typed instead of Latin c
    t = re.sub(r"[\"'`׳״.,:;!?()\[\]*]+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _one_edit(a: str, b: str) -> bool:
    """True when a and b differ by exactly one substitution / insertion / deletion."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
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
