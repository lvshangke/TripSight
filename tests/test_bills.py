"""微信/支付宝账单：合成样本（结构仿照真实导出，内容全是编的），本机解析、筛旅行期间、分类、汇总；返回里不含商户名。"""

import csv
from datetime import datetime

import pytest

pytest.importorskip("mcp")
openpyxl = pytest.importorskip("openpyxl")

from tripcore import bills as bl  # noqa: E402
from tripcore import mcp_server as s  # noqa: E402

WX_HEAD = ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态", "交易单号", "商户单号", "备注"]
AL_HEAD = ["交易时间", "交易分类", "交易对方", "对方账号", "商品说明", "收/支", "金额", "收/付款方式", "交易状态", "交易订单号", "商家订单号", "备注", ""]


def _wx(path):
    wb = openpyxl.Workbook(); ws = wb.active
    for line in ["微信支付账单明细", "微信昵称：[某人]", "起始时间：[2026-11-06 00:00:00]", "共5笔记录"] + [""] * 12 + ["----------------------微信支付账单明细列表--------------------"]:
        ws.append([line])
    ws.append(WX_HEAD)
    ws.append([datetime(2026, 11, 7, 12, 30, 0), "商户消费", "故宫博物院文创店", "门票", "支出", 60, "零钱", "支付成功", "WX1", "m1", "/"])
    ws.append([datetime(2026, 11, 7, 18, 5, 0), "商户消费", "某某面馆", "牛肉面", "支出", 38.5, "零钱", "支付成功", "WX2", "m2", "/"])
    ws.append([datetime(2026, 11, 8, 9, 0, 0), "群收款", "朋友A", "AA", "支出", 100, "零钱", "支付成功", "WX3", "m3", "/"])
    ws.append([datetime(2026, 11, 8, 9, 5, 0), "转账", "朋友B", "转账", "收入", 20, "零钱", "已存入零钱", "WX4", "m4", "/"])
    ws.append([datetime(2026, 10, 1, 9, 0, 0), "商户消费", "旅行之外的店", "x", "支出", 999, "零钱", "支付成功", "WX5", "m5", "/"])
    wb.save(path)


def _ali(path):
    with open(path, "w", encoding="gb18030", newline="") as f:
        w = csv.writer(f)
        for line in ["----------", "导出信息：", "支付宝账户：x", "共6笔记录"] + [""] * 18:
            w.writerow([line])
        w.writerow(AL_HEAD)
        w.writerow(["2026-11-07 10:00:00", "交通出行", "滴滴出行", "x", "打车", "支出", "25.60", "余额", "交易成功", "A1", "b1", "", ""])
        w.writerow(["2026-11-07 15:00:00", "文化休闲", "天坛公园", "x", "联票", "支出", "34", "余额", "交易成功", "A2", "b2", "", ""])
        w.writerow(["2026-11-08 20:00:00", "餐饮美食", "烤鸭店", "x", "晚餐", "支出", "300", "余额", "交易成功", "A3", "b3", "", ""])
        w.writerow(["2026-11-08 21:00:00", "退款", "烤鸭店", "x", "退款", "不计收支", "20", "余额", "退款成功", "A4", "b4", "", ""])
        w.writerow(["2026-11-08 22:00:00", "日用百货", "某超市", "x", "x", "支出", "50", "余额", "交易关闭", "A5", "b5", "", ""])
        w.writerow(["2026-11-08 23:00:00", "其他", "余额宝", "x", "转入", "不计收支", "500", "余额", "交易成功", "A6", "b6", "", ""])


def _trip():
    s.new_trip(num_days=3, mode="transit", city="北京")
    s.set_dates("2026-11-06", "2026-11-08")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=120)
    s.schedule_days()


def test_parse_wechat_and_alipay(tmp_path):
    _wx(tmp_path / "a.xlsx"); _ali(tmp_path / "b.csv")
    w, ws = bl.parse(bl.read_rows(tmp_path / "a.xlsx"))
    assert {t.source for t in w} == {"wechat"} and ws["transfer"] == 1 and ws["spend"] == 3
    assert [t.category for t in w if not t.transfer][:2] == ["其他", "餐饮"] or "餐饮" in [t.category for t in w]
    a, st = bl.parse(bl.read_rows(tmp_path / "b.csv"))
    cats = {t.merchant: t.category for t in a}
    assert cats["滴滴出行"] == "交通" and cats["天坛公园"] == "门票" and st["refund"] == 1 and st["skipped"] >= 2
    assert sum(t.amount for t in a) == pytest.approx(25.6 + 34 + 300 - 20)               # 关闭和余额宝转入不算，退款冲抵


def test_not_a_bill_is_refused(tmp_path):
    (tmp_path / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(bl.BillError, match="不是微信/支付宝"):
        bl.parse(bl.read_rows(tmp_path / "x.csv"))
    assert bl.sniff(tmp_path / "x.csv") is None


def test_import_and_summary_through_tools(tmp_path):
    _trip(); _wx(tmp_path / "a.xlsx"); _ali(tmp_path / "b.csv")
    out = s.import_bills(str(tmp_path))
    assert "新记" in out and "期间之外 1 笔" in out and "故宫博物院" not in out and "滴滴" not in out
    again = s.import_bills(str(tmp_path))
    assert "新记 0 笔" in again and "重复" in again                                      # 重复导入不重复记
    summ = s.spending_summary()
    assert "餐饮" in summ and "交通" in summ and "滴滴" not in summ and "故宫博物院" not in summ
    assert "个人转账" in summ and "合计" in summ
    ledger = bl.load(s._ledger_path())
    assert all("order" not in x and "card" not in x for x in ledger) and any(x["place_id"] for x in ledger)   # 商户带景点名的自动挂上


def test_needs_trip_dates(tmp_path):
    s.new_trip(num_days=2, mode="transit", city="北京")
    _wx(tmp_path / "a.xlsx")
    with pytest.raises(Exception, match="具体日期"):
        s.import_bills(str(tmp_path / "a.xlsx"))

