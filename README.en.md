<div align="center">

# 🧭 TripSight

**Let the AI understand where you want to go — let code make sure the plan holds up.**

An open-source travel-itinerary agent. The LLM only understands intent and proposes changes; scheduling, opening-hours checks, routes, versioning and undo are done by deterministic code — facts come only from map services, tools or you.

[中文](README.md) · [Setup](docs/SETUP.md) (Chinese) · [Design notes](DESIGN.md) (Chinese)

![License](https://img.shields.io/badge/license-Apache--2.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![Tests](https://img.shields.io/badge/tests-362%20passing-brightgreen)
![MCP tools](https://img.shields.io/badge/MCP%20tools-51-8A2BE2)

<img src="docs/images/workbench-list.png" alt="TripSight workbench itinerary list (sample data)" width="360">

<sub>Itinerary list of the local web workbench in edit mode (sample data). The workbench also has a map and a chat panel, not shown here.</sub>

</div>

---

## ✨ What is TripSight

Trip planning goes wrong in two ways: **the model confidently makes things up** (a sight that is long closed, two places two hours apart called "nearby"), and **fixing one thing breaks everything else**.

TripSight separates the two concerns:

- The **LLM** (via chat) does what it is good at — understanding "I want to see the Terracotta Army and keep it relaxed" — and proposes changes.
- **tripcore** (deterministic code, exposed as 51 MCP tools) decides which sight goes on which day, checks arrival against opening hours, fetches real routes, versions every change and undoes on request.
- **You** confirm every change.

> ⚠️ Early-stage project. The Amap, Google Maps and nanobot integrations are mainly tested against fake services (362 automated tests); real-service testing is still limited. Prices, hours and weather are reference values — verify with official sources before you travel. The assistant never books or pays.

## 💡 Why TripSight

- **Facts are never invented.** Coordinates, hours, routes and weather come only from map services and tools; when something cannot be determined the tool says "unverified" instead of guessing.
- **Opening hours take part in scheduling**, not just in after-the-fact warnings: closed days and impossible time slots are avoided, and places that cannot fit are listed with the reason.
- **Every step is confirmable and undoable.** Changes are proposals applied only after you reply with a confirmation code; confirmed items are locked so re-planning never shuffles them; `undo` works repeatedly.
- **Not tied to one model or platform.** It is an MCP server, so any MCP-capable chat agent can use it; the repo ships setup for [nanobot](https://github.com/HKUDS/nanobot).
- **Your data stays on your machine.** Trips are local JSON files, the workbench listens on `127.0.0.1` only, keys live in your own config, and `tripcore doctor` only prints "configured / not configured".

## 🧩 Capabilities

| Area | What it does |
|---|---|
| **Planning** | Automatic day assignment and in-day ordering (geography + capacity + opening hours), pace levels, locking confirmed items, day-trip detection |
| **Checks** | Closed days, arriving after closing, past last entry, stay running past closing, overloaded days, long legs, missing reservations, budget, lodging too far, weather vs outdoor sights |
| **Maps & routes** | Amap / Google Maps / OpenStreetMap; real transit/walk/drive times, transfers, intercity-leg hints, airport/station transfers (late-night legs switch to taxi) |
| **Lodging & food** | Per-night / per-segment stay-area suggestions (multi-city aware), hotel candidates ranked by commute, restaurants near a stop, a named restaurant placed on the nearest day, "no lunch planned" reminders |
| **Guides → trip** | Paste a travel note or guide → every quote verified against the original text → coordinates verified on the map → you pick → added; walking routes (e.g. a city walk) can be one item |
| **Transport & weather** | Record arrival/departure flights or trains and derive first/last-day playable time; read-only flight/train/hotel reference prices; Open-Meteo and Amap weather |
| **Take it with you** | WeChat-friendly text, mobile HTML map, Amap app personal map, GPX, local web workbench |
| **Memory** | Remembers preferences you state explicitly (dislikes walking, budget cap, food) and applies them to new trips; post-trip review of actual costs and notes |
| **Engineering** | Multiple trips, version history and undo, `tripcore doctor`, Apache-2.0, 362 automated tests |

## 🔍 Feature details

1. **Scheduling.** `schedule_days` clusters places by geography, improves the assignment with cross-day moves and swaps, and orders each day (exact search up to 7 stops, nearest-neighbour + 2-opt beyond). With known dates, opening hours are part of the cost: closed days are skipped, orders that miss closing time are penalised, and places that can never fit are reported with a reason. Locked items never move; the same input always gives the same result.
2. **Opening-hours checks.** One timeline computes the expected arrival and departure of every stop and compares it with opening hours (closed, arrives after closing, past last entry, stay beyond closing, too early, day running late). The parser is conservative: it understands forms like "Tue–Sun 09:00-17:00", "Mar–Oct" or "closed Mondays from Nov 15", and says "cannot be determined" instead of guessing.
3. **Proposals, confirmation, undo.** The assistant cannot edit the trip directly. It creates a proposal (move, remove, set status, lock, set duration) and you see "before → after" plus a 4-digit code to confirm. Every change goes into version history; applying checks the revision so nothing is overwritten.
4. **Real routes and preferences.** With an Amap key, `refine_routes` upgrades estimates to real routes (time, transfers, walking distance, fares). Preferences (max transfers, prefer subway, max walking, taxi OK) change which option is chosen; `compare_transport` compares modes and `set_leg_mode` pins one leg. Legs over ~80 km are flagged as intercity. Overseas trips can use Google Maps; without keys OpenStreetMap is the fallback.
5. **Stay areas.** `suggest_lodging` works per night: it uses the last stop of one day and the first stop of the next, merges neighbouring nights into one stay, and splits into several stays when places lie in different cities. One-day excursions (e.g. a mountain 100 km away) are detected so the hotel stays in the main area. Each segment gives a centre, radius and a "search near X" hint for the assistant.
6. **Food.** `suggest_food` searches restaurants near a stop (rating, per-person price, hours, distance); nothing is added until you choose. `find_food` places a restaurant you name on the nearest day. The workbench shows "lunch not planned" per day with a one-click "find lunch" button.
7. **Guides → candidates.** The model reads and lists; code verifies. Each candidate's quote must appear verbatim in the pasted text and contain the place name, otherwise it is rejected. Only after you pick are coordinates looked up, and only unambiguous, non-duplicate matches are added. Prices and hours in a guide are treated as unverified hints. *Input today is pasted text; there is no Xiaohongshu scraper in this repo.*
8. **Transport, weather, prices.** `set_connection` derives when the first day can start and when the last day must leave. `get_weather` covers days with confirmed dates and warns about rain or heat for outdoor sights. Flight/train/hotel reference prices use the flyai and RollingGo command-line tools through read-only skills — no booking, no payment.
9. **Take it with you.** `export_text` makes plain text for phones and chat apps (including WeChat via nanobot's `weixin` channel) with an outbound check that rejects keys and local paths; `export_map` makes a mobile-friendly HTML map; `create_amap_map` hands each day's loop to Amap's official service for a link that opens in the Amap app; `export_gpx` exports daily tracks.
10. **Web workbench.** `python -m tripcore web --open`: itinerary list, map and chat in three resizable columns. View mode shows details and problems; edit mode lets you move stops, edit stay times, add places (chosen from map search results, never typed coordinates), pick dates, switch or create trips, and preview every change before confirming. Listens on 127.0.0.1 with a one-time token, Host/Origin checks and revision checks.
11. **Preferences and review.** Preferences you explicitly state are kept across trips; after the trip you can record actual costs and notes, and `show_review` compares plan vs reality.
12. **Final checklist.** `final_check` lists everything still open: plan issues, nights without lodging, unbooked transport, stale weather, unverified data, estimated routes, days without meals. Read-only.

## 🚀 Quick start

Python 3.10 or newer is required.

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m tripcore doctor      # read-only self-check (never prints key values)
python -m tripcore demo        # full demo on the sample data
python -m tripcore web --open  # local web workbench
python -m pytest -q            # run the tests
```

To use it through chat, follow [docs/SETUP.md](docs/SETUP.md) (Chinese) to connect nanobot. Keep Amap / Google keys in your own local configuration; never commit them.

**Docker (optional, not yet verified in a real environment):** the `Dockerfile` runs the CLI and the MCP server. The workbench deliberately listens on 127.0.0.1 only, so it is not in the image.

```bash
docker build -t tripsight .
docker run --rm tripsight python -m tripcore demo
docker run -i --rm -v "$PWD/data:/data" -e AMAP_KEY tripsight   # MCP over stdio
```

## 🏗️ Architecture

```
chat agent (LLM, e.g. nanobot) ──proposes──▶ tripcore MCP server ──▶ trip.json (versioned, undoable)
   understands intent only                    schedules · checks · versions · routes
                                              facts only from tools or the user
web workbench (127.0.0.1) ─────────────────────────────▲
```

`tripcore/` is the core library and MCP server; `skills/` holds the agent's instructions; `nanobot/config.example.json` is the integration sample (no secrets); `scripts/install_skills.py` installs the skills into nanobot. nanobot itself is not vendored: you install it yourself, so upgrading it never conflicts with this repo.

## 🔐 Safety

The assistant never books, pays or installs anything. The workbench is local-only with a one-time token and revision checks. Keys are read from environment variables or your local nanobot config and are never printed. Prices, hours and weather carry their source and date.

## 📄 License

Apache License 2.0 — see [LICENSE](LICENSE).
