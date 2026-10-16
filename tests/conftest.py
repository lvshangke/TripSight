"""测试公共准备：提供几个方便构造数据的小函数。"""

import sys
from pathlib import Path

import pytest

# 让测试能找到项目根目录下的 tripcore 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tripcore.models import Lodging, Place, Trip, TripMeta  # noqa: E402
from tripcore.storage import load_trip  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "beijing.json"


def make_place(pid: str, lat: float = 39.9, lon: float = 116.4, **kw) -> Place:
    return Place(id=pid, name=kw.pop("name", pid), lat=lat, lon=lon, **kw)


def make_trip(places, num_days=2, lodgings=None, **meta_kw) -> Trip:
    return Trip(meta=TripMeta(num_days=num_days, **meta_kw), places=places, lodgings=lodgings or [])


@pytest.fixture
def beijing() -> Trip:
    return load_trip(EXAMPLE)
