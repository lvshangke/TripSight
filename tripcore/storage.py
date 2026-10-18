"""保存与读取：把一次旅行存成一个 JSON 文件。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Trip


def save_trip(trip: Trip, path: str | Path) -> None:
    """保存。先写临时文件再改名，避免写到一半出错把原文件弄坏。"""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(trip.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def load_trip(path: str | Path) -> Trip:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Trip.model_validate(data)
