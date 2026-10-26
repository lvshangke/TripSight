"""朋友圈九宫格：挑图张数、覆盖不同景点、方图无元数据、文案只用用户的话、不覆盖已有导出。"""

import pytest

pytest.importorskip("mcp")
pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from tripcore import mcp_server as s  # noqa: E402
from tripcore import moments as mo  # noqa: E402


def _trip_with_photos(per_place):
    s.new_trip(num_days=1, mode="walk", city="北京")
    s.set_dates("2026-11-07", "2026-11-07")
    names = ["故宫", "天坛", "景山", "北海"]
    for i, n in enumerate(names[: len(per_place)]):
        s.add_place(n, 39.9 + i * 0.01, 116.39 + i * 0.01, duration_min=60)
    s.schedule_days()
    items = s._ph.load(s._photo_index())
    t = s._load()
    ids = [it.place_id for it in t.plan.days[0].items]
    for pid, k in zip(ids, per_place):
        for j in range(k):
            f = s._photo_dir() / f"{pid}_{j}.jpg"
            f.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (400, 300), (30 * j + 20, 90, 160)).save(f)
            items.append({"id": f"{pid}{j}", "file": f.name, "place_id": pid, "day": None, "caption": ""})
    s._ph.save(s._photo_index(), items)
    return ids


def test_pick_sizes_and_coverage():
    ids = _trip_with_photos([3, 3, 3, 3])
    t = s._load(); ph = s._ph.load(s._photo_index())
    got = mo.pick(t, ph)
    assert len(got) == 9 and {x["place_id"] for x in got} == set(ids)               # 12 张里挑 9，每个景点都有
    four = mo.pick(t, ph, count=4)
    assert len(four) == 4 and len({x["place_id"] for x in four}) == min(4, len(ids))     # 能排进行程的景点都有照片
    assert len(mo.pick(t, ph[:5])) == 4                                             # 只有 5 张：取不超过 5 的最大排法 4


def test_export_makes_square_clean_jpegs_and_caption_only_uses_user_words(tmp_path):
    ids = _trip_with_photos([2, 2])
    s.save_stop_story(ids[0], impression="AI 写的描写，不该进文案")
    out = s.export_moments()
    root = next(p for p in s.trip_path().with_name("exports").iterdir() if "朋友圈" in p.name)
    assert (root / "1.jpg").exists() and (root / "文案.txt").exists() and (root / "发布前检查.txt").exists()
    with Image.open(root / "1.jpg") as im:
        assert im.size == (1080, 1080) and not im.getexif()
    cap = (root / "文案.txt").read_text(encoding="utf-8")
    assert "路线：" in cap and "AI 写的描写" not in cap and "人脸" in out
    # 用户自己的话（web 路径写入 by=user）才会进文案
    import json
    st = json.loads(s._stories_path().read_text(encoding="utf-8")); st[ids[0]]["by"] = "user"
    s._stories_path().write_text(json.dumps(st), encoding="utf-8")
    s.export_moments()
    caps = [(p / "文案.txt").read_text(encoding="utf-8") for p in s.trip_path().with_name("exports").iterdir() if "朋友圈" in p.name]
    assert len(caps) == 2 and any("AI 写的描写" in c for c in caps)                    # 第二次是新文件夹，没覆盖第一次


def test_no_photos_refused():
    s.new_trip(num_days=1, mode="walk", city="北京"); s.set_dates("2026-11-07", "2026-11-07")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=60); s.schedule_days()
    with pytest.raises(Exception, match="还没有挂照片"):
        s.export_moments()
