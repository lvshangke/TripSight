import pytest

from tripcore import links, mcp_server as s, web


def test_build_keyword_adds_city_and_suffix_once():
    assert links.build_keyword("兵马俑", "西安") == "西安 兵马俑 攻略"
    assert links.build_keyword("西安 兵马俑 攻略", "西安") == "西安 兵马俑 攻略"
    assert links.build_keyword("回民街", "西安", links.FOOD) == "西安 回民街 美食"
    assert links.build_keyword("兵马俑") == "兵马俑 攻略"


def test_search_links_encode_keyword_and_filter_by_kind():
    guide = {x["id"]: x for x in links.search_links("兵马俑", "西安", "guide")}
    assert "xiaohongshu" in guide and "mafengwo" in guide and "dianping" not in guide
    assert guide["xiaohongshu"]["url"].startswith("https://www.xiaohongshu.com/search_result?keyword=")
    assert "%E5%85%B5%E9%A9%AC%E4%BF%91" in guide["xiaohongshu"]["url"] and " " not in guide["xiaohongshu"]["url"]
    food = {x["id"] for x in links.search_links("回民街", "西安", "food")}
    assert "dianping" in food and "mafengwo" not in food


def test_special_characters_cannot_break_out_of_url():
    url = links.search_links("a&b=c#d?e/f", None, "guide", ["baidu"])[0]["url"]
    assert url.count("?") == 1 and "#" not in url and "&" not in url.split("wd=")[1]


def test_sites_filter_ignores_unknown_and_empty_keyword_rejected():
    assert [x["id"] for x in links.search_links("x", None, "guide", ["baidu", "nope"])] == ["baidu"]
    with pytest.raises(ValueError):
        links.search_links("  ")


def test_tool_uses_trip_city_and_validates_kind():
    s.new_trip(city="西安")
    out = s.search_links("兵马俑")
    assert out["links"] and out["links"][0]["keyword"].startswith("西安 兵马俑")
    with pytest.raises(Exception):
        s.search_links("x", kind="bogus")


def test_snapshot_exposes_https_templates():
    s.new_trip(city="西安")
    snap = web.snapshot()
    assert snap["city"] == "西安"
    assert all(x["tpl"].startswith("https://") for x in snap["link_sites"])
    assert any("{q}" in x["tpl"] for x in snap["link_sites"])


def test_hotel_links_use_entry_page_and_search_with_suffix():
    res = {x["id"]: x for x in links.search_links("西安城墙附近", "西安", "hotel")}
    assert {"xiaohongshu", "dianping", "ctrip", "ctrip_search"} <= set(res)
    assert res["ctrip"]["url"] == "https://hotels.ctrip.com/"           # 固定入口，不带关键词
    assert "mafengwo" not in res
    from urllib.parse import unquote
    assert unquote(res["ctrip_search"]["url"]).endswith("酒店 携程")      # 经百度搜“… 携程”
    assert links.build_keyword("西安城墙附近", "西安", "hotel") == "西安城墙附近 酒店"   # 关键词里已有城市就不重复补
    assert links.build_keyword("钟楼附近", "西安", "hotel") == "西安 钟楼附近 酒店"


def test_tool_accepts_hotel_kind():
    s.new_trip(city="西安")
    assert s.search_links("钟楼附近", kind="hotel")["links"]
