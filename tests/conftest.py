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


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """所有测试都用临时目录保存行程/偏好，绝不碰真实的 ~/.tripcore。"""
    monkeypatch.setenv("TRIPCORE_FILE", str(tmp_path / "trip.json"))
    monkeypatch.setenv("TRIPCORE_NO_AUTO_WEATHER", "1")                              # 测试里不在后台自动查天气
    monkeypatch.setenv("NANOBOT_CONFIG", str(tmp_path / "no-nanobot.json"))        # 不读真实的 nanobot 配置（里面可能有真 key）
    monkeypatch.delenv("AMAP_KEY", raising=False)                                   # 短片等默认会用高德，测试里不能带真 key 联网


@pytest.fixture(autouse=True)
def _no_network_weather(monkeypatch):
    """测试里默认不启用 Open-Meteo（不联网）；需要的测试自己替换。"""
    from tripcore import mcp_server
    monkeypatch.setattr(mcp_server, "_openmeteo", lambda: None)
