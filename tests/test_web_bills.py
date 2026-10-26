"""工作台的花费页后端：导入、看明细、改类别并记住商户、排除、挂景点。"""

import pytest

pytest.importorskip("openpyxl")

from tests.test_web import call, server  # noqa: F401
from tests.test_bills import _ali, _trip, _wx
from tripcore import mcp_server as s


def test_import_edit_remember(server, tmp_path):
    _trip(); _wx(tmp_path / "a.xlsx"); _ali(tmp_path / "b.csv")
    code, r = call(server, "/tok/api/bills_import", {"path": str(tmp_path)})
    assert code == 200 and "新记" in r["message"]
    st = call(server, "/tok/api/bills_state")[1]
    assert st["has_dates"] and st["summary"]["count"] >= 5 and "餐饮" in st["categories"]
    row = next(x for x in st["rows"] if x["merchant"] == "某某面馆")
    code, _ = call(server, "/tok/api/bills_edit", {"id": row["id"], "category": "购物", "remember": True})
    assert code == 200
    st2 = call(server, "/tok/api/bills_state")[1]
    assert next(x for x in st2["rows"] if x["id"] == row["id"])["category"] == "购物" and st2["rules"] == 1
    # 以后再导入同一商户，沿用记住的类别（先清空账本再导入）
    s._ledger_path().unlink()
    call(server, "/tok/api/bills_import", {"path": str(tmp_path)})
    assert next(x for x in call(server, "/tok/api/bills_state")[1]["rows"] if x["merchant"] == "某某面馆")["category"] == "购物"
    # 排除、挂景点、非法类别
    assert call(server, "/tok/api/bills_edit", {"id": row["id"], "excluded": True})[0] == 200
    assert call(server, "/tok/api/bills_edit", {"id": row["id"], "category": "乱写"})[0] == 400
    assert call(server, "/tok/api/bills_edit", {"id": "nope", "excluded": True})[0] == 400
    assert call(server, "/tok/api/bills_edit", {"id": row["id"], "place_id": "zzz"})[0] == 400


def test_watch_and_scan_routes(server, tmp_path):
    _trip()
    w = tmp_path / "w"; w.mkdir(); _wx(w / "a.xlsx")
    assert call(server, "/tok/api/bills_watch", {"folders": [str(w)]})[0] == 200
    st = call(server, "/tok/api/bills_state")[1]
    assert st["watch"] == [str(w)] and len(st["shortcut"]) >= 4
    code, r = call(server, "/tok/api/bills_scan", {})
    assert code == 200 and "新记" in r["message"]
    assert call(server, "/tok/api/bills_watch", {"folders": ["/no/such/dir"]})[0] == 400
