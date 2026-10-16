import pytest
from datetime import date
from pydantic import ValidationError

from tripcore.models import DateMode, Trip, TripMeta

from .conftest import make_place, make_trip


def test_exact_dates_derive_num_days():
    m = TripMeta(date_mode=DateMode.EXACT, start_date=date(2026, 10, 12), end_date=date(2026, 10, 15))
    assert m.num_days == 4


def test_exact_requires_dates():
    with pytest.raises(ValidationError):
        TripMeta(date_mode=DateMode.EXACT)


def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        TripMeta(date_mode=DateMode.EXACT, start_date=date(2026, 10, 12), end_date=date(2026, 10, 10))


def test_duplicate_place_ids_rejected():
    with pytest.raises(ValidationError):
        make_trip([make_place("a"), make_place("a")])


def test_invalid_weekday_rejected():
    with pytest.raises(ValidationError):
        make_place("a", closed_weekdays=[7])


def test_invalid_latitude_rejected():
    with pytest.raises(ValidationError):
        make_place("a", lat=123)


def test_day_date_none_when_date_unknown():
    t = make_trip([make_place("a")])
    assert t.day_date(0) is None


def test_day_date_exact(beijing):
    assert beijing.day_date(0).isoformat() == "2026-10-12"
    assert beijing.day_date(2).isoformat() == "2026-10-14"
