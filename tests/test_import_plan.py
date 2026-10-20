"""游记 → 候选 → 行程：分天识别、原文段落、预查地图、对照与照搬。"""

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402
from tripcore.amap import PlaceHit  # noqa: E402
from tripcore.candidates import day_markers, day_of, validate_items  # noqa: E402

TRAVEL = """西安三日游攻略
Day1
兵马俑：秦始皇陵的陪葬坑，建议请讲解，门票120元。看完回市区。
钟楼：市中心地标，傍晚灯光很美。
第二天
大雁塔：慈恩寺内的唐代佛塔，晚上有音乐喷泉。
陕西历史博物馆：馆藏丰富，周一闭馆，要提前预约。
第3天
华清宫：骊山脚下的皇家温泉行宫。
"""

POS = {"兵马俑": (34.3848, 109.2785), "钟楼": (34.2610, 108.9430), "大雁塔": (34.2190, 108.9640),
       "陕西历史博物馆": (34.2250, 108.9540), "华清宫": (34.3628, 109.2133)}


class Amap:
    def search_places(self, query, city=None, limit=5):
        if query == "钟楼":                                     # 两个同名且相距很远 → 有歧义
            return [PlaceHit(name="钟楼", lat=34.26, lon=108.94), PlaceHit(name="钟楼", lat=34.60, lon=109.40)]
        if query in POS:
            return [PlaceHit(name=query, lat=POS[query][0], lon=POS[query][1], address="西安")]
        return []


def _items():
    return [
        {"name": "兵马俑", "kind": "attraction", "quote": "兵马俑：秦始皇陵的陪葬坑",
         "passage": "兵马俑：秦始皇陵的陪葬坑，建议请讲解，门票120元。", "clues": ["门票120元"]},
        {"name": "钟楼", "kind": "attraction", "quote": "钟楼：市中心地标"},
        {"name": "大雁塔", "kind": "attraction", "quote": "大雁塔：慈恩寺内的唐代佛塔"},
        {"name": "陕西历史博物馆", "kind": "attraction", "quote": "陕西历史博物馆：馆藏丰富"},
        {"name": "华清宫", "kind": "attraction", "quote": "华清宫：骊山脚下的皇家温泉行宫"},
    ]


def test_day_markers_and_assignment():
    nt = "".join(TRAVEL.split())
    assert [n for _, n in day_markers(nt)] == [1, 2, 3]
    assert day_markers("第十二天去玩") and day_markers("第十二天去玩")[0][1] == 12
    assert day_markers("D3逛街Day4休息")[0][1] == 3 and [n for _, n in day_markers("D3逛街Day4休息")] == [3, 4]
    assert day_markers("RAID5阵列, 3D5") == []                      # 字母夹数字不算分天
    ok, _ = validate_items(TRAVEL, _items())
    assert {e["name"]: e["day"] for e in ok} == {"兵马俑": 1, "钟楼": 1, "大雁塔": 2, "陕西历史博物馆": 2, "华清宫": 3}
    assert day_of([(5, 1)], 2) is None                              # 第一个标记之前不属于任何一天


def test_passage_must_be_verbatim_and_is_capped():
    bad = [{"name": "钟楼", "kind": "attraction", "quote": "钟楼：市中心地标", "passage": "钟楼：模型自己编的一大段介绍"}]
    ok, rej = validate_items(TRAVEL, bad)
    assert not ok and "passage" in rej[0]["reason"]
    no_name = [{"name": "钟楼", "kind": "attraction", "quote": "钟楼：市中心地标", "passage": "市中心地标，傍晚灯光很美。"}]
    assert validate_items(TRAVEL, no_name)[0] == []                 # passage 里必须有地名
    long_text = "钟楼：" + "很好看" * 200
    ok, _ = validate_items(long_text, [{"name": "钟楼", "kind": "attraction", "quote": "钟楼：很好看", "passage": long_text}])
    assert ok[0]["passage"].endswith("…") and len(ok[0]["passage"]) <= 301
    ok, _ = validate_items(TRAVEL, [{"name": "钟楼", "kind": "attraction", "quote": "钟楼：市中心地标"}])
    assert ok[0]["passage"] == "钟楼：市中心地标"                  # 没给 passage 就用那句原话


def _trip():
    s.new_trip(start_date="2026-10-30", end_date="2026-11-01", city="西安", name="西安")


def test_submit_prechecks_map_and_gives_links(monkeypatch):
    _trip()
    monkeypatch.setattr(s, "_amap", lambda: Amap())
    out = s.submit_candidates(TRAVEL, _items(), source="三日游")
    by = {c["name"]: c for c in out["added"]}
    assert by["兵马俑"]["match"]["status"] == "matched" and by["兵马俑"]["match"]["link"].startswith("https://")
    assert by["钟楼"]["match"]["status"] == "ambiguous" and by["钟楼"]["match"]["options"]
    assert by["大雁塔"]["day"] == 2 and by["兵马俑"]["day"] == 1
    assert out["source_days"] == [1, 2, 3] and "compare_with_source" in out["note"]
    assert any("xiaohongshu" in u for u in by["兵马俑"]["links"].values())
    assert s.list_candidates()[0]["match"]["status"] in ("matched", "ambiguous")        # 预查结果存下来了


def test_submit_without_map_key_is_unchecked(monkeypatch):
    _trip()
    monkeypatch.setattr(s, "_amap", lambda: None)
    out = s.submit_candidates(TRAVEL, _items()[:1], source="三日游")
    assert out["added"][0]["match"]["status"] == "unchecked"


def test_precheck_budget(monkeypatch):
    _trip()
    monkeypatch.setattr(s, "_amap", lambda: Amap())
    monkeypatch.setattr(s, "MAX_PRECHECK", 2)
    out = s.submit_candidates(TRAVEL, _items(), source="三日游")
    st = [c["match"]["status"] for c in out["added"]]
    assert st.count("unchecked") == 3 and len(st) == 5


def _adopted(monkeypatch):
    _trip()
    monkeypatch.setattr(s, "_amap", lambda: Amap())
    s.submit_candidates(TRAVEL, _items(), source="三日游")
    ids = [c["id"] for c in s.list_candidates() if c["name"] != "钟楼"]
    s.adopt_candidates(ids)


def test_adopt_keeps_intro_source_and_day(monkeypatch):
    _adopted(monkeypatch)
    t = s._load()
    p = next(p for p in t.places if p.name == "兵马俑")
    assert p.intro.startswith("兵马俑：秦始皇陵的陪葬坑") and "他人说法" in p.intro_source
    assert p.source_name == "三日游" and p.source_day == 1
    assert next(p for p in t.places if p.name == "华清宫").source_day == 3
    assert p.ticket_price == 0                                      # 游记里的 120 元不当事实


def test_compare_reports_split_days_without_changing_trip(monkeypatch):
    _adopted(monkeypatch)
    s.schedule_days()
    rev = s._load().revision
    res = s.compare_with_source("三日游")
    assert [g["source_day"] for g in res["groups"]] == [1, 2, 3]
    assert s._load().revision == rev                                 # 只读
    day2 = res["groups"][1]
    assert {p["name"] for p in day2["places"]} == {"大雁塔", "陕西历史博物馆"}


def test_follow_places_and_locks_by_source_day(monkeypatch):
    _adopted(monkeypatch)
    s.schedule_days()
    out = s.follow_source_days("三日游")
    t = s._load()
    where = {t.place(it.place_id).name: (d.index, it.locked) for d in t.plan.days for it in d.items}
    assert where["兵马俑"] == (0, True) and where["大雁塔"] == (1, True) and where["陕西历史博物馆"] == (1, True) and where["华清宫"] == (2, True)
    assert len(out["report"]["placed"]) == 4
    s.undo()
    assert not any(it.locked for d in s._load().plan.days for it in d.items)       # 一个版本，可撤销


def test_follow_reports_closed_day_conflict_and_unmapped(monkeypatch):
    _adopted(monkeypatch)
    pid = next(p.id for p in s._load().places if p.name == "陕西历史博物馆")
    s.update_place(pid, closed_weekdays=[5])                         # 10-31 是周六 → 第二天闭馆
    out = s.follow_source_days("三日游", {"1": 1, "2": 2, "3": 5})
    rep = out["report"]
    assert any("陕西历史博物馆" in c and "闭馆" in c for c in rep["conflicts"])
    assert rep["unmapped_days"] and rep["unmapped_days"][0]["source_day"] == 3
    t = s._load()
    assert "华清宫" not in {t.place(it.place_id).name for d in t.plan.days for it in d.items if it.locked}


def test_follow_does_not_move_user_locked_items(monkeypatch):
    _adopted(monkeypatch)
    s.schedule_days()
    pid = next(p.id for p in s._load().places if p.name == "兵马俑")
    r = s.propose_change("兵马俑放第 3 天", [{"kind": "move", "place_id": pid, "to_day": 2}])
    s.apply_proposal(r["proposal_id"], r["confirm_code"])
    out = s.follow_source_days("三日游")
    assert any("兵马俑" in x and "锁定" in x for x in out["report"]["skipped"])
    t = s._load()
    assert any(it.place_id == pid for it in t.plan.days[2].items)


def test_follow_without_source_days_errors():
    _trip()
    with pytest.raises(s.ToolError, match="没有找到"):
        s.follow_source_days("不存在")
    with pytest.raises(s.ToolError, match="没有带分天"):
        s.compare_with_source()


def test_workbench_snapshot_exposes_intro_as_quoted_text(monkeypatch):
    from tripcore import web
    from tripcore.webpage import page_html
    _adopted(monkeypatch)
    s.schedule_days()
    snap = web.snapshot()
    pid = next(p.id for p in s._load().places if p.name == "兵马俑")
    x = snap["intros"][pid]
    assert x["text"].startswith("兵马俑：秦始皇陵的陪葬坑") and "他人说法" in x["source"] and x["day"] == 1
    assert "introHtml" in page_html() and "游记里怎么说" in page_html()
