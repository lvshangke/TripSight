from tripcore.lodging import rank_lodgings, suggest_stay_area
from tripcore.models import Lodging
from tripcore.scheduler import schedule

from .conftest import make_place, make_trip


def test_no_places_no_suggestion():
    assert suggest_stay_area(make_trip([])) is None


def test_suggestion_within_bounding_box(beijing):
    t = schedule(beijing)
    s = suggest_stay_area(t)
    lats = [p.lat for p in t.places]
    lons = [p.lon for p in t.places]
    assert min(lats) <= s.lat <= max(lats)
    assert min(lons) <= s.lon <= max(lons)
    assert s.place_count > 0


def test_ranking_prefers_closer_lodging():
    places = [make_place("a", lat=39.90, lon=116.40), make_place("b", lat=39.91, lon=116.41)]
    near = Lodging(id="near", name="近", lat=39.905, lon=116.405, price_min=500, price_max=600)
    far = Lodging(id="far", name="远", lat=40.20, lon=116.80, price_min=100, price_max=200)
    t = make_trip(places, num_days=2, lodgings=[far, near])
    ranked = rank_lodgings(t)
    assert [r.lodging.id for r in ranked] == ["near", "far"]


def test_ranking_empty_without_lodgings(beijing):
    beijing.lodgings = []
    assert rank_lodgings(beijing) == []
