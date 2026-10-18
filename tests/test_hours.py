from datetime import date

import pytest

from tripcore.hours import hours_window

BEILIN = "1月至7月,9月至12月 周一至周日 09:00-18:30；8月 周一至周日 08:30-19:00 最晚进入17:30"
BINGMAYONG = "09/25-09/30 08:00–19:30开放 最晚售票17:30；10/01-10/07 07:30–20:00开放 最晚售票18:00"
WALL = "2.15日-2.23日:8:00-23:00，23点停售；2.24日-3.4日:8:00-22:00，22点停售"


def test_month_list_and_season_pick():
    w = hours_window(BEILIN, date(2026, 10, 30))
    assert w.ranges == ((540, 1110),) and w.last_entry == 17 * 60 + 30        # 全文只有一种“最晚进入”，按它算
    assert hours_window(BEILIN, date(2026, 8, 3)).ranges == ((510, 1140),)


def test_slash_dates_and_en_dash():
    w = hours_window(BINGMAYONG, date(2026, 10, 3))
    assert w.ranges == ((450, 1200),) and w.last_entry == 18 * 60              # 取该季节自己那段的最晚售票
    assert hours_window(BINGMAYONG, date(2026, 9, 27)).last_entry == 17 * 60 + 30


def test_season_not_covered_is_unknown_not_guessed():
    assert hours_window(BINGMAYONG, date(2026, 10, 30)) is None               # 文字里没有这一天的信息：不猜
    assert hours_window(WALL, date(2026, 10, 30)) is None
    assert hours_window(WALL, date(2026, 3, 1)).ranges == ((480, 1320),)


@pytest.mark.parametrize("text", ["", "待核实", "全年开放，具体以景区公告为准", "周一至周五 上午开放", "10月1日起 08:00-17:00；11月15日起 09:00-16:00，12月1日起 闭园"])
def test_unparseable_is_none(text):
    assert hours_window(text, date(2026, 10, 30)) is None


def test_all_day_closed_split_and_overnight():
    assert hours_window("周一至周日 00:00-24:00", date(2026, 10, 30)).all_day is True
    assert hours_window("周一 闭馆；周二至周日 09:00-17:00", date(2026, 10, 26)).closed is True       # 周一
    assert hours_window("周一 闭馆；周二至周日 09:00-17:00", date(2026, 10, 27)).ranges == ((540, 1020),)
    assert hours_window("周一至周日 09:00-12:00、14:00-18:00", date(2026, 10, 30)).ranges == ((540, 720), (840, 1080))
    assert hours_window("周一至周日 18:00-02:00", date(2026, 10, 30)).ranges == ((1080, 26 * 60),)          # 跨夜


def test_last_entry_forms():
    assert hours_window("周一至周日 08:30-17:40", date(2026, 11, 3)).last_entry is None
    assert hours_window("4月1日至11月14日 08:30-19:00 (18:00停止检票)", date(2026, 10, 3)).last_entry == 18 * 60
