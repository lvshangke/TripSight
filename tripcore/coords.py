"""坐标系转换：WGS84（GPS / OpenStreetMap）↔ GCJ-02（高德、腾讯等国内地图）。

为什么需要：两种坐标在中国境内相差几百米，混用会让景点“偏”到隔壁街。
tripcore 内部统一存 WGS84；调用高德前转成 GCJ-02，拿到高德的结果后再转回 WGS84。
中国境外两种坐标相同，函数原样返回。
"""

from __future__ import annotations

import math

_A = 6378245.0                  # 克拉索夫斯基椭球长半轴
_EE = 0.00669342162296594323    # 偏心率平方


def out_of_china(lat: float, lon: float) -> bool:
    return not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    if out_of_china(lat, lon):
        return lat, lon
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = math.sin(rad)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrt_magic * math.cos(rad) * math.pi)
    return lat + dlat, lon + dlon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """GCJ-02 没有解析逆变换，用迭代逼近（误差 < 1 米）。"""
    if out_of_china(lat, lon):
        return lat, lon
    guess_lat, guess_lon = lat, lon
    for _ in range(8):
        g_lat, g_lon = wgs84_to_gcj02(guess_lat, guess_lon)
        guess_lat -= g_lat - lat
        guess_lon -= g_lon - lon
    return guess_lat, guess_lon
