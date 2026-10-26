"""旅行消费：读微信/支付宝导出的账单文件，只在本机解析，筛出这次行程期间的消费，分类并汇总。

- 支持：微信账单（.xlsx 或 .csv）、支付宝账单（.csv，常见编码 GBK；也可以是 .xlsx / .numbers）。.numbers 需要 pip install numbers-parser，
  .xlsx 需要 openpyxl。表头位置和列名自动识别（找第一列叫“交易时间”的那一行），所以导出模板稍有变化也能读。
- 隐私：账单内容不交给模型；对外（给助手的返回）只有笔数和汇总数字，没有商户名。账本里只存日期、时间、金额、类别、商户简称、来源，
  不存卡号、支付方式、交易单号（只存单号的哈希，用来去重）。
- 不计入消费的：收入、不计收支、已关闭/失败的交易、个人转账和群收款（单独列出，用户可以改）。退款按负数冲抵。
- 类别：门票、餐饮、交通、住宿、购物、其他。支付宝用它自带的“交易分类”，微信（没有分类）按商户名关键词判断，判断不了归“其他”，用户可以改。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

CATEGORIES = ["门票", "餐饮", "交通", "住宿", "购物", "其他"]
TRANSFER = "转账"            # 个人转账/群收款：不计入消费，单独列出
SUFFIXES = {".csv", ".xlsx", ".numbers", ".txt"}      # .txt 是 iPhone 快捷指令追加的 Apple Pay 记录

_ALIPAY_MAP = {
    "餐饮美食": "餐饮", "交通出行": "交通", "酒店旅游": "住宿", "旅游出行": "住宿", "文化休闲": "门票",
    "日用百货": "购物", "服饰装扮": "购物", "数码电器": "购物", "美容美发": "购物", "母婴亲子": "购物", "家居家装": "购物",
}
_KEYWORDS = [
    ("住宿", ("酒店", "民宿", "宾馆", "旅馆", "客栈", "住宿", "公寓", "青旅")),
    ("门票", ("景区", "门票", "索道", "博物馆", "公园", "古城", "古镇", "寺", "景点", "旅游区", "观光", "展览", "乐园")),
    ("交通", ("滴滴", "出租", "地铁", "公交", "铁路", "12306", "航空", "机场", "停车", "加油", "高速", "打车", "单车", "哈啰", "高铁", "客运")),
    ("餐饮", ("餐", "饭", "面馆", "面", "茶", "咖啡", "奶茶", "小吃", "烧烤", "火锅", "酒家", "食", "饮", "包子", "粥", "麦当劳", "肯德基", "瑞幸", "星巴克")),
]


class BillError(Exception):
    pass


@dataclass
class Txn:
    when: datetime
    amount: float            # 支出为正，退款为负
    merchant: str
    item: str
    source: str              # wechat | alipay
    category: str
    key: str                 # 单号哈希，去重用
    transfer: bool = False


# ---------------- 读文件 ----------------

def read_rows(path: Path) -> list[list[Any]]:
    suf = path.suffix.lower()
    if suf == ".csv":
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "gb18030"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise BillError("读不了这个文件的编码。")
        return [list(r) for r in csv.reader(io.StringIO(text))]
    if suf == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            raise BillError("读 .xlsx 要先安装 openpyxl（pip install openpyxl）。")
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if suf == ".numbers":
        try:
            from numbers_parser import Document
        except ImportError:
            raise BillError("读 .numbers 要先安装 numbers-parser（pip install numbers-parser），或者在“数字”里导出成 CSV/Excel。")
        doc = Document(str(path))
        best: list[list[Any]] = []
        for sh in doc.sheets:
            for t in sh.tables:
                rows = [list(r) for r in t.rows(values_only=True)]
                if any(r and str(r[0]).strip() == "交易时间" for r in rows) and len(rows) > len(best):
                    best = rows
        return best
    raise BillError(f"不支持的文件类型：{suf}")


def sniff(path: Path) -> Optional[str]:
    """不读全文，只看表头判断是不是微信/支付宝账单（.txt 则看是不是 Apple Pay 记录）；不是返回 None。"""
    if path.suffix.lower() == ".txt":
        try:
            return "applepay" if parse_applepay(path.read_text(encoding="utf-8", errors="ignore")) else None
        except OSError:
            return None
    try:
        rows = read_rows(path)
    except Exception:
        return None
    return _source(_header(rows)[1]) if _header(rows)[0] is not None else None


def _header(rows: list[list[Any]]) -> tuple[Optional[int], list[str]]:
    for i, r in enumerate(rows):
        if r and str(r[0]).strip() == "交易时间":
            return i, [str(c).strip() if c is not None else "" for c in r]
    return None, []


def _source(head: list[str]) -> Optional[str]:
    if "交易分类" in head and "交易对方" in head:
        return "alipay"
    if "交易类型" in head and "交易对方" in head:
        return "wechat"
    return None


def _when(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    try:
        return datetime.strptime(str(v).strip()[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _amount(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace("¥", "").replace(",", "").strip())
    except ValueError:
        return None


def _guess(text: str) -> str:
    for cat, words in _KEYWORDS:
        if any(w in text for w in words):
            return cat
    return "其他"


def parse(rows: list[list[Any]]) -> tuple[list[Txn], dict[str, int]]:
    hi, head = _header(rows)
    if hi is None:
        raise BillError("没有找到账单表头（应有“交易时间”这一列），这可能不是微信/支付宝的账单。")
    src = _source(head)
    if src is None:
        raise BillError("认不出这是微信还是支付宝的账单（缺少“交易类型”或“交易分类”列）。")
    col = {n: i for i, n in enumerate(head) if n}
    g = lambda r, n: (r[col[n]] if n in col and col[n] < len(r) else None)
    amt_col = "金额(元)" if "金额(元)" in col else "金额"
    stat = {"rows": 0, "spend": 0, "refund": 0, "skipped": 0, "transfer": 0}
    out: list[Txn] = []
    for r in rows[hi + 1:]:
        if not r or r[0] is None or str(r[0]).strip() == "":
            continue
        when = _when(g(r, "交易时间"))
        amount = _amount(g(r, amt_col))
        if when is None or amount is None:
            continue
        stat["rows"] += 1
        direction = str(g(r, "收/支") or "").strip()
        status = str(g(r, "当前状态" if src == "wechat" else "交易状态") or "")
        merchant = str(g(r, "交易对方") or "").strip()
        item = str(g(r, "商品" if src == "wechat" else "商品说明") or "").strip()
        order = str(g(r, "交易单号" if src == "wechat" else "交易订单号") or "") + str(when)
        key = hashlib.sha1((src + order).encode()).hexdigest()[:16]
        if any(w in status for w in ("关闭", "失败")):
            stat["skipped"] += 1
            continue
        if src == "alipay":
            kind = str(g(r, "交易分类") or "")
            if kind == "退款":
                out.append(Txn(when, -abs(amount), merchant, item, src, "其他", key))
                stat["refund"] += 1
                continue
            if direction != "支出":
                stat["skipped"] += 1
                continue
            cat = _ALIPAY_MAP.get(kind) or _guess(merchant + item)
            out.append(Txn(when, amount, merchant, item, src, cat, key))
            stat["spend"] += 1
        else:
            kind = str(g(r, "交易类型") or "")
            if direction != "支出":
                stat["skipped"] += 1
                continue
            personal = kind in ("转账", "群收款", "微信红包", "红包") or "转账" in kind
            if personal:
                out.append(Txn(when, amount, merchant, item, src, TRANSFER, key, transfer=True))
                stat["transfer"] += 1
            else:
                out.append(Txn(when, amount, merchant, item, src, _guess(merchant + item), key))
                stat["spend"] += 1
    return out, stat


# ---------------- 账本（本机 JSON） ----------------

def load(path: Path) -> list[dict[str, Any]]:
    try:
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def save(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def _short(s: str, n: int = 14) -> str:
    return s if len(s) <= n else s[:n] + "…"


def add_to_ledger(ledger: list[dict[str, Any]], txns: Iterable[Txn], start: date, end: date, place_names: dict[str, str],
                  rules: Optional[dict[str, str]] = None) -> dict[str, int]:
    """把行程日期范围内的交易放进账本（已有的不重复）。place_names = {景点id: 名字}，商户或商品里带景点名就自动挂上。"""
    have = {x["id"] for x in ledger}
    added = outside = dup = 0
    for t in txns:
        if not (start <= t.when.date() <= end):
            outside += 1
            continue
        if t.key in have:
            dup += 1
            continue
        pid = next((i for i, n in place_names.items() if n and (n in t.merchant or n in t.item)), None)
        ledger.append({"id": t.key, "date": t.when.date().isoformat(), "time": t.when.strftime("%H:%M"), "amount": round(t.amount, 2),
                       "category": (rules or {}).get(_short(t.merchant), t.category) if not t.transfer else t.category, "merchant": _short(t.merchant), "source": t.source, "place_id": pid, "excluded": t.transfer})
        have.add(t.key)
        added += 1
    ledger.sort(key=lambda x: (x["date"], x["time"]))
    return {"added": added, "outside": outside, "duplicate": dup}


def summarize(ledger: list[dict[str, Any]], categories: Optional[list[str]] = None) -> dict[str, Any]:
    """只返回汇总数字（不含商户名）：总额、按类别、按天、被排除（转账等）的笔数和金额。"""
    use = [x for x in ledger if not x.get("excluded") and (categories is None or x["category"] in categories)]
    by_cat: dict[str, float] = {}
    by_day: dict[str, float] = {}
    for x in use:
        by_cat[x["category"]] = round(by_cat.get(x["category"], 0) + x["amount"], 2)
        by_day[x["date"]] = round(by_day.get(x["date"], 0) + x["amount"], 2)
    ex = [x for x in ledger if x.get("excluded")]
    return {"total": round(sum(x["amount"] for x in use), 2), "count": len(use), "by_category": by_cat, "by_day": dict(sorted(by_day.items())),
            "excluded_count": len(ex), "excluded_total": round(sum(x["amount"] for x in ex), 2)}


def load_rules(path: Path) -> dict[str, str]:
    try:
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return {k: v for k, v in d.items() if v in CATEGORIES} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def edit(ledger: list[dict[str, Any]], rid: str, *, category: Optional[str] = None, place_id: Optional[str] = ..., excluded: Optional[bool] = None) -> dict[str, Any]:
    row = next((x for x in ledger if x["id"] == rid), None)
    if row is None:
        raise BillError("找不到这笔消费。")
    if category is not None:
        if category not in CATEGORIES + [TRANSFER]:
            raise BillError("类别只能是：" + "、".join(CATEGORIES))
        row["category"] = category
    if place_id is not ...:
        row["place_id"] = place_id or None
    if excluded is not None:
        row["excluded"] = bool(excluded)
    return row


# ---------------- Apple Pay（iPhone 快捷指令追加的文本） ----------------

def parse_applepay(text: str) -> list[Txn]:
    """每行一笔：`2026-11-07 12:30|60.00|商户名`（分隔符可以是 | 逗号 或制表符；日期可以带秒；# 开头是注释）。认不出的行跳过。
    快捷指令的“交易”自动化只对 Apple Pay / 钱包里的卡触发，微信和支付宝的付款不在里面。"""
    out: list[Txn] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.replace("\t", "|").replace("，", ",").replace(",", "|").split("|")]
        if len(parts) < 3:
            continue
        when = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                when = datetime.strptime(parts[0], fmt)
                break
            except ValueError:
                continue
        amount = _amount(parts[1])
        if when is None or amount is None or amount <= 0:
            continue
        merchant = parts[2]
        key = hashlib.sha1(("applepay" + line).encode()).hexdigest()[:16]
        out.append(Txn(when, amount, merchant, "", "applepay", _guess(merchant), key))
    return out


# ---------------- 自动盯文件夹 ----------------

SHORTCUT_STEPS = [
    "打开“快捷指令” → 底部“自动化” → 右上角 + → 选“交易”（据我所知它在你用 Apple Pay 付款时触发）。",
    "选要记的卡片，选“立即运行”，下一步“新建空白自动化”。",
    "添加操作“文本”，内容依次点变量：当前日期（格式 yyyy-MM-dd HH:mm）、竖线 |、金额、竖线 |、商家。",
    "再添加操作“添加到文本文件”：选 iCloud 云盘里的 TripSight账单 文件夹下的 applepay.txt，勾选“换行”。",
    "完成。Mac 上只要盯着这个文件夹，下一次扫描就会自动记进账本。微信和支付宝的付款这个方法抓不到，它们要靠导出账单。",
]


def icloud_folder() -> Path:
    return Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "TripSight账单"
