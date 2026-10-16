from tripcore.scheduler import schedule
from tripcore.storage import load_trip, save_trip


def test_roundtrip(tmp_path, beijing):
    t = schedule(beijing)
    path = tmp_path / "trip.json"
    save_trip(t, path)
    again = load_trip(path)
    assert again == t
    assert not (tmp_path / "trip.json.tmp").exists()


def test_history_survives_roundtrip(tmp_path, beijing):
    t = schedule(schedule(beijing))
    path = tmp_path / "trip.json"
    save_trip(t, path)
    again = load_trip(path)
    assert len(again.history) == 2
