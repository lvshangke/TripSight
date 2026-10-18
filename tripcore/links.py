"""“看攻略 / 看点评”的跳转链接：只拼出各平台的搜索网址，由用户自己在浏览器里打开、用自己的账号登录。

不抓取、不读取这些平台的内容，不经手任何账号信息；网址里只有关键词（城市 + 景点名）。
各平台的网址格式写在下面的表里，平台改版时只需改这里；格式来自公开资料和常见用法，未用真实账号逐一验证。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

GUIDE, FOOD = "guide", "food"


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    kinds: tuple[str, ...]      # 适合查什么：guide 攻略/游记，food 美食/点评
    template: str               # {q} 会被替换成 URL 编码后的关键词


SITES: tuple[Site, ...] = (
    Site("xiaohongshu", "小红书", (GUIDE, FOOD), "https://www.xiaohongshu.com/search_result?keyword={q}"),
    Site("dianping", "大众点评", (FOOD,), "https://www.dianping.com/ai-search?keyword={q}"),
    Site("mafengwo", "马蜂窝", (GUIDE,), "https://www.mafengwo.cn/search/q.php?q={q}"),
    Site("baidu", "百度", (GUIDE, FOOD), "https://www.baidu.com/s?wd={q}"),
    Site("google", "Google", (GUIDE, FOOD), "https://www.google.com/search?q={q}"),
)
_BY_ID = {s.id: s for s in SITES}


def build_keyword(keyword: str, city: Optional[str] = None, kind: str = GUIDE) -> str:
    """关键词里没有城市就补上城市；攻略类补“攻略”，美食类补“美食”（已经包含就不重复补）。"""
    kw = keyword.strip()
    if city and city not in kw:
        kw = f"{city} {kw}"
    suffix = {GUIDE: "攻略", FOOD: "美食"}.get(kind, "")
    if suffix and suffix not in kw and "推荐" not in kw:
        kw = f"{kw} {suffix}"
    return kw


def search_links(keyword: str, city: Optional[str] = None, kind: str = GUIDE,
                 sites: Optional[list[str]] = None) -> list[dict[str, str]]:
    """返回 [{id, name, url, keyword}]。sites 为空则给适合这类查询的全部平台；不认识的平台名直接忽略。"""
    kw = build_keyword(keyword, city, kind)
    if not keyword.strip():
        raise ValueError("关键词不能为空")
    chosen = [_BY_ID[s] for s in (sites or []) if s in _BY_ID] or [s for s in SITES if kind in s.kinds]
    return [{"id": s.id, "name": s.name, "keyword": kw, "url": s.template.replace("{q}", quote(kw, safe=""))}
            for s in chosen]


def templates() -> list[dict[str, object]]:
    """给网页用：页面自己用关键词拼网址（模板只有这一份）。"""
    return [{"id": s.id, "name": s.name, "kinds": list(s.kinds), "tpl": s.template} for s in SITES]
