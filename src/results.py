"""Structured result of a daily run, so callers (CLI, future web server) can render
the briefing without re-running the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RunResult:
    date: str
    text: str
    html: str = ""
    regime: str = ""
    regime_note: str = ""
    ranked: list = field(default_factory=list)
    vetoed: list = field(default_factory=list)
    others: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    holdings: list = field(default_factory=list)
    rotation_plan: dict = field(default_factory=dict)
    discovery: dict = field(default_factory=dict)
    report_path: Optional[Path] = None
    skipped: bool = False
