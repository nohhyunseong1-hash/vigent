from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
RULEBOOK_DIR = BASE_DIR / "data" / "rulebooks"


def load_rulebook(filename: str) -> list[dict]:
    with (RULEBOOK_DIR / filename).open("r", encoding="utf-8") as file:
        return json.load(file)
