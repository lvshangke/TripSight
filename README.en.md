# TripSight (tripcore) — a reliable travel-itinerary agent

[中文](README.md) · License: [Apache-2.0](LICENSE)

The LLM only **understands what you want and proposes changes**. Deterministic code **schedules, validates, versions and undoes**. Facts such as places, opening hours and routes come only from map services, tools or you — never from the model's imagination.

![Workbench itinerary list (sample data)](docs/images/workbench-list.png)

*The itinerary list of the local web workbench in edit mode (sample data): edit the stay time of each stop, move stops up or down, see the commute between stops, and see problems such as "reservation needed" right under the stop. The workbench also has a map and a chat panel, not shown here.*

## What it does

- Assigns the places you want to visit to days by geography **and opening hours**, and orders each day's visits.
- Estimates commute times, or looks up real routes once an Amap (高德) or Google Maps key is configured.
- Validates the plan: overloaded days, closed attractions, arriving after closing time, missing reservations, long legs, weather that does not suit outdoor sights.
- Every change is first a *proposal*, applied only after confirmation, and can be undone. Confirmed items are locked, so automatic re-planning never shuffles them.
- A local web workbench: switch or create trips, drag to reorder, add places, edit stay times, map and chat panel.
- Exposed as an MCP server (51 tools) so a chat agent ([nanobot](https://github.com/HKUDS/nanobot)) can add places, pick hotels and look up train/flight prices (read-only: it never books or pays).

## Quick start

Python 3.10 or newer is required.

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m tripcore doctor      # read-only self-check: deps, skills, nanobot, keys (never prints key values)
python -m tripcore demo        # full demo on the sample data
python -m tripcore web --open  # open the local web workbench
python -m pytest -q            # run the tests
```

To use it through chat, follow [docs/SETUP.md](docs/SETUP.md) (written in Chinese) to connect nanobot. Keep Amap / Google keys in your own local configuration only; never commit them.

## Architecture

```
chat agent (LLM)  ──proposes──▶  tripcore MCP server  ──▶  trip.json (versioned, undoable)
   understands intent            schedules · validates · versions
                                 facts only from tools or the user
web workbench (127.0.0.1)  ───────────────▲
```

- `tripcore/scheduler.py` — assigns places to days and orders each day (geography, capacity, opening hours; locked items are never moved).
- `tripcore/validator.py` — returns a list of problems; `tripcore/hours.py` parses opening-hours text conservatively and answers "unknown" instead of guessing.
- `tripcore/proposals.py`, `state.py` — proposals (move, remove, set status, lock, set duration), revision checks, history and undo.
- `tripcore/amap.py`, `gmaps.py`, `geocode.py` — Amap, Google Maps and OpenStreetMap providers.
- `tripcore/web.py`, `webpage.py` — the workbench: stdlib HTTP server bound to 127.0.0.1, one-time token URL, Host/Origin checks, revision check on every write.
- `skills/` — instructions for the chat agent; `scripts/install_skills.py` installs them into nanobot.
- `DESIGN.md` — design principles, algorithms and known limitations.

## Safety principles

- The workbench listens on `127.0.0.1` only. The agent cannot book, pay or install anything.
- API keys are read from environment variables or your local nanobot config. `tripcore doctor` only reports "configured / not configured".
- Opening hours, prices and weather are shown with their source and date; if something cannot be determined, the tool says so instead of inventing a value.

## Status and limitations

- Early-stage project. The Amap, Google and nanobot integrations have been tested against fake services in the test suite (349 tests); real-service testing is still limited.
- Travel-time estimates without a map key are straight-line estimates, not real routes.
- The scheduler is a heuristic: results are deterministic but not guaranteed optimal.
- Most documentation is currently in Chinese; the Chinese [README](README.md) has the detailed reference.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
