"""路线型景点（如 citywalk）：一个景点带一串有序途经点。

排程里它仍是“一项”；但进入它的路段终点是第一个途经点，离开它的路段起点是最后一个途经点。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Place


@dataclass(frozen=True)
class Endpoint:
    """用来算路段的端点：id 是景点的 id，坐标可能是路线的起点或终点。"""
    id: str
    name: str
    lat: float
    lon: float


def entry(p: Place) -> Endpoint:
    if p.waypoints:
        w = p.waypoints[0]
        return Endpoint(p.id, w.name, w.lat, w.lon)
    return Endpoint(p.id, p.name, p.lat, p.lon)


def exit_(p: Place) -> Endpoint:
    if p.waypoints:
        w = p.waypoints[-1]
        return Endpoint(p.id, w.name, w.lat, w.lon)
    return Endpoint(p.id, p.name, p.lat, p.lon)
