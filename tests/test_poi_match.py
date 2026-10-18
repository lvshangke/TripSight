from tripcore import mcp_server as s
from tripcore.amap import PlaceHit
from tripcore.mapview import day_marker_links, marker_link


class CityScoped:
    """模拟高德：限定城市时只返回该城市的点；不限城市才能搜到别的市的点；周边搜按距离。"""

    def __init__(self, hits_by_city, around_hits=None):
        self.hits_by_city, self.around_hits = hits_by_city, around_hits or []
        self.calls = []

    def search_places(self, query, city=None, limit=5):
        self.calls.append(("text", city))
        return [h for h in self.hits_by_city.get(city, [])]

    def search_around(self, lat, lon, radius_m=800, types="050000", keywords="", limit=20):
        self.calls.append(("around", types, keywords))
        return self.around_hits


def _hit(name, lat, lon, pid):
    return PlaceHit(name=name, lat=lat, lon=lon, amap_id=pid)


def test_match_finds_poi_in_other_city_without_city_limit():
    c = CityScoped({None: [_hit("华山风景名胜区", 34.48, 110.08, "B1")], "西安": []})
    assert s._match_poi(c, "华山风景名胜区", 34.49, 110.09, "西安", 3.0) == "B1"
    assert ("text", "西安") in c.calls and ("text", None) in c.calls


def test_match_tolerates_name_suffix_differences():
    c = CityScoped({"西安": [_hit("华山风景区", 34.48, 110.08, "B2")]})
    assert s._match_poi(c, "华山风景名胜区", 34.48, 110.08, "西安", 3.0) == "B2"


def test_match_falls_back_to_around_search_and_strips_branch_brackets():
    c = CityScoped({}, around_hits=[_hit("雅斯特国际酒店", 34.55, 110.08, "H1")])
    assert s._match_poi(c, "雅斯特国际酒店(华阴华山景区玉泉院店)", 34.551, 110.081, "西安", 1.0) == "H1"
    assert any(x[0] == "around" and x[1] == "" for x in c.calls)      # 周边搜不限类别


def test_match_prefers_nearest_and_rejects_far_or_wrong_names():
    c = CityScoped({"西安": [_hit("钟楼", 34.30, 108.90, "FAR"), _hit("钟楼", 34.2610, 108.9420, "NEAR")]})
    assert s._match_poi(c, "钟楼", 34.2610, 108.9421, "西安", 3.0) == "NEAR"
    c2 = CityScoped({"西安": [_hit("大雁塔", 34.22, 108.96, "X")]})
    assert s._match_poi(c2, "钟楼", 34.2610, 108.9421, "西安", 3.0) is None


def test_marker_link_is_https_and_gcj():
    u = marker_link("钟楼", 34.2610, 108.9421)
    assert u.startswith("https://uri.amap.com/marker?") and "coordinate=gaode" in u and "%E9%92%9F%E6%A5%BC" in u
    assert "amapuri" not in u


def test_day_marker_links_cover_hotel_and_stops():
    s.new_trip(num_days=1, city="北京")
    s.add_place("故宫", 39.9163, 116.3972)
    s.add_place("天坛", 39.8822, 116.4066)
    s.add_lodging("酒店A", 39.9100, 116.4000, choose=True)
    s.schedule_days()
    links = day_marker_links(s._load(), 0)
    assert [x["label"] for x in links][0] == "出发酒店" and links[-1]["label"] == "返回酒店"
    assert {x["name"] for x in links} >= {"故宫", "天坛", "酒店A"} and all(x["url"].startswith("https://") for x in links)
    assert day_marker_links(s._load(), 5) == []
