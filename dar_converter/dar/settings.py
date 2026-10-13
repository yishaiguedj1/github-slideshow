"""Load settings (config/settings.yaml) and resolve data paths."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

PKG_ROOT = Path(__file__).resolve().parent.parent          # dar_converter/
DEFAULT_SETTINGS = PKG_ROOT / "config" / "settings.yaml"


def hhmm(value: str) -> int:
    h, m = str(value).split(":")
    return int(h) * 60 + int(m)


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Settings:
    raw: dict[str, Any]
    base_dir: Path

    # ---- convenience accessors -------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def data_dir(self) -> Path:
        env = os.environ.get("DAR_DATA_DIR")
        if env:
            return Path(env)
        return (self.base_dir / self.get("paths.data_dir", "../data")).resolve()

    def path(self, key: str) -> Path:
        return self.data_dir / self.get(f"paths.{key}")

    def day_bounds(self, day: date) -> tuple[int, int]:
        start = hhmm(self.get("day.start", "07:00"))
        holidays = {str(h) for h in self.get("day.holidays", []) or []}
        end_key = "day.holiday_end" if day.isoformat() in holidays else "day.end"
        return start, hhmm(self.get(end_key, "19:00"))

    def is_holiday(self, day: date) -> bool:
        return day.isoformat() in {str(h) for h in self.get("day.holidays", []) or []}

    def is_workday(self, day: date) -> bool:
        return day.weekday() in set(self.get("day.workdays", [6, 0, 1, 2, 3]))

    def with_overrides(self, overrides: dict) -> "Settings":
        return Settings(_deep_merge(self.raw, overrides), self.base_dir)


def load_settings(path: str | Path | None = None, overrides: dict | None = None) -> Settings:
    """Relative paths in the file are resolved from the folder above config/."""
    p = Path(path).resolve() if path else DEFAULT_SETTINGS
    with open(p, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    s = Settings(raw, p.parent.parent)
    return s.with_overrides(overrides) if overrides else s
