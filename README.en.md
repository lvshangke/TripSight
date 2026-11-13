<div align="center">

<h1>🧭 TripSight</h1>

<p><b>TripSight — your end-to-end personal travel assistant: it gets the itinerary right before you leave, keeps it checkable on the road, turns your photo album into a real, shareable trip handbook when you are back, and records your footprints on a map.</b></p>

<p>
<a href="README.md">中文</a> ·
<a href="docs/SETUP.md">Setup (Chinese)</a>
</p>

<p>
<img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License">
<img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python">
<img src="https://img.shields.io/badge/tests-600%2B%20passing-brightgreen" alt="Tests">
<img src="https://img.shields.io/badge/MCP%20tools-92-8A2BE2" alt="MCP tools">
</p>

<p>
<a href="docs/images/poster.jpg">
<img src="docs/images/poster.jpg" alt="TripSight: plan, restore, record and share" width=100%>
</a>
</p>

<p>
Plug it into your own chat assistant (MCP) and <b>cover the whole trip in one line</b>:<br>
<b>plan</b> (local events, real routes, opening hours, weather, intercity transport, booking reminders) → <b>check on the road</b> (navigation, calendar, mobile map) →<br>
<b>rebuild the route you actually took from your album</b> (names, districts, day titles) → <b>handbook · cards · route animation · travel film</b> → <b>footprints and spending</b>.
</p>

<p>
<b>Open source · data stays on your machine · every step checkable and undoable · no booking, no payment</b>
</p>

</div>

## ✨ What is TripSight

TripSight is an **end-to-end travel assistant**. It is not a "one-click guide generator" but a toolbox you plug into your own chat assistant: it remembers your preferences and helps you get every step right — before, during and after the trip.

| Stage | You want to… | What the agent + tools in TripSight do |
|---|---|---|
| **Before · Plan** | build a reliable itinerary | Stops can come from anywhere (model suggestions, someone else's guide, places you want to go) and are scheduled together; opening hours, closed days, over-packed days, weather, intercity transport, hotels and meals are all checked; changes are proposals you confirm, and `undo` works repeatedly |
| **On the road · Check** | know how to get there, whether it will rain | Real routes for every leg (transit / subway / walk / taxi), per-day weather (fetched in the background once the workbench is open); view it as an .ics calendar, mobile map, WeChat text or GPX |
| **After · Restore** | turn an album into the route you walked | Rebuild stay points from a photo folder or a Mac Photos album; with "auto mode" on, the assistant names stops, tags city/district, titles each day and fills in photos, then stops at the preview for you to confirm or polish |
| **Record & share** | keep it, post it | 8 share themes, web handbook, travel cards, PDF with clickable navigation links, per-day route animation, Obsidian notes; an optional "travel film" in the restore export: clips grouped by stop using capture time and location, cut into a film with intro/outro, day title cards and route animations, plus an optional Jianying draft |
| **Long term** | where I went, what I spent | Footprint summary (trips, cities, approximate km) and footprint map; WeChat/Alipay bill import for spending stats; remembers preferences you state and applies them next time |

**The agent's role** (and the design principle of the whole project):

- **The LLM only understands intent:** it hears "move Guanqian Street to the last day" or "turn my January photos from the old phone into a trip", picks the tool and explains it to you. It never invents coordinates, opening hours or prices.
- **Deterministic code does the work:** day splitting, rule checks, routes and weather, photo clustering and exports are done by MCP tools (92 in total); facts come only from tools or you, and anything unknown is marked "to verify".
- **You keep the final say:** changes are proposals first; the assistant **never books, pays or installs anything**; trips are local JSON, the web workbench listens on `127.0.0.1` only, and API keys live only in your own config.
- **Not tied to one model or agent:** any MCP-capable chat agent works ([nanobot](https://github.com/HKUDS/nanobot), WorkBuddy, Claude Code… see "Quick start" below).

## 🎬 See how it works

In TripSight **the chat assistant (agent) is the operator and the web workbench is its work surface; say "open TripSight" in chat to bring up the visual workbench**. The agent only works out what you want and which tool to call; scheduling, checking, routing, weather and exports are done by deterministic MCP tools, and every step appears in the "Assistant" card on the left — checkable and undoable. Below are **demo replays** of three complete flows (full videos in [`docs/videos/`](docs/videos/)):

<b>① Plan a trip: say where you want to go → the assistant schedules, verifies and connects the routes</b>

https://github.com/user-attachments/assets/021abf3b-b4cb-4fc6-a244-77fc53fa2a7d

<sub>What the agent does: splits one sentence into "look up coordinates → add stops → split into 3 days → check"; when Guanqian Street would be reached too early it <b>makes a proposal</b> and only applies it after you reply "confirm"; finds restaurants and records the hotel (recorded, never booked); turns all 11 legs into real Amap routes in one go; fetches weather <b>automatically</b> once the workbench is open; finally exports the share page, PDF and calendar.</sub>

<b>② Restore a trip: rebuild a past journey from an old phone's album</b>

https://github.com/user-attachments/assets/7486875f-0bb5-41d0-9327-a809e9749ecf

<sub>What the agent does: with "auto mode" on, it runs <b>rebuild stay points → look up place names → tag city/district → title each day → fill in photos</b> in a row and stops at the preview for you; the video ends on the <b>footprint page</b>, zooming from clustered pins across Asia down to a city and a street, opening a pin to see the local photo thumbnails, and finally ticking "real routes" so same-day stops are joined along real roads; slow steps run in the background so tool timeouts do not interrupt them; afterwards you can keep editing and export a handbook, cards, PDF and route animation.</sub>

<b>③ Restore → the optional "Travel film" in the export step</b>

https://github.com/user-attachments/assets/53ba3a18-4a96-441a-88b8-791d1fa1167f

<sub>Videos are a restore source just like photos: videos with a location are clustered into stay points together with photos (video-only stops use a video frame as thumbnail). In the export step, if the album/folder contains videos, an optional "Travel film" block appears: first see how clips are grouped by stop, then generate in one click. What the agent does: reads only each clip's capture time, location and duration and assigns it to a stop; builds an intro (trip name, dates, days / places / km), one title card per day (your titles), animated route cards, place-name captions and cross-dissolves, keeps each clip's original sound with normalised loudness, and matches the layout and colours to the handbook style you picked; route cards can be drawn on the real Amap map along Amap driving paths; a Jianying draft can be generated too. You can also do it from chat: with "auto mode" on, say "make the travel film too" and after restoring, naming, tagging districts and titling days, the assistant groups the clips and generates the film itself.</sub>

<sub>Demo notes: harness is nanobot; model is qwen3.7-max. Basemap © Amap.</sub>

### Two uses, one principle

| | Plan (before the trip) | Restore (after the trip) |
|---|---|---|
| You say | "3 days in Suzhou, I want the Humble Administrator's Garden, Lion Grove…" | "Turn my January Hainan photos into a trip" |
| The agent understands | stops, dates, pace, preferences, what to change | which album/folder, which dates, auto mode or not |
| Tools do, deterministically | day split and ordering, hours / closure / too-rushed checks, real routes, weather, versions and undo | stay-point clustering by time and place, place names, photos, handbook / cards / PDF / route animation |
| You keep control | proposals need confirmation; repeatable `undo`; never books or pays | preview before export; photos can be referenced, not copied; AI text only describes what is visible, and is labelled |

## 🖼️ At a glance

**Left: the plan workbench** (itinerary on the left, real map in the middle, chat assistant on the right; one tab per day, with weather, opening hours, real routes and "what the assistant did" on one page). **Right: the restore edit page** (album → stay points → edit → export; click a pin on the map to see that place's photo thumbnails, and the list on the left jumps to the stop).

<p>
<a href="docs/images/workbench.png"><img src="docs/images/workbench.png" width="49%" alt="Plan workbench: 3 days in Suzhou with real routes, weather and the chat assistant"></a>&ensp;
<a href="docs/images/workbench-restore.png"><img src="docs/images/workbench-restore.png" width="49%" alt="Restore edit page for the Taizhou trip, click a pin for thumbnails"></a>
</p>

**More small features**:

<p align="center"><img src="docs/images/demo.gif" width="23%" alt="Drag and check">&emsp;<img src="docs/images/feat-closed.gif" width="23%" alt="Closures and opening hours">&emsp;<img src="docs/images/feat-route.gif" width="23%" alt="Real routes"></p>
<p align="center"><img src="docs/images/feat-weather.gif" width="23%" alt="Weather">&emsp;<img src="docs/images/feat-links.gif" width="23%" alt="Click-through navigation">&emsp;<img src="docs/images/feat-tools.gif" width="23%" alt="Tools"></p>
<p align="center"><img src="docs/images/feat-export.gif" width="23%" alt="One-click export">&emsp;<img src="docs/images/feat-edit.gif" width="23%" alt="Edit handbook and cards in place">&emsp;<img src="docs/images/feat-footprint.gif" width="23%" alt="Footprint map: click a pin for thumbnails"></p>

<sub>Screens use a demo 3-day Suzhou trip (real weather forecast) and the author's old-phone Hainan album (scenery only); basemap © Amap. Screenshots are generated from demo replays.</sub>

**Sharing and export**:

<p align="center">
<a href="docs/images/export-all.jpg"><img src="docs/images/export-all.jpg" alt="Share and export: share page, phone map page, calendar; footprint map, card, calendar import, Obsidian note" width="100%"></a>
</p>

## 🔁 How a plan comes together

1. **Say where you want to go:** destination, dates, group size and pace in chat; or click "New trip" on the web page and fill in the form.
2. **Collect places:** once the dates are set, your personal agent **automatically looks up** local **events** and weather for those days (concerts, sports, lantern festivals, exhibitions, food markets, with source URLs) and lists them for you to pick; only chosen ones are added, scheduled on the day they happen. You can also name places directly, ask the assistant to **recommend**, paste **someone else's guide or travel note** to be checked item by item, or add **anywhere you want to go**. All sources are scheduled together.
3. **Automatic day split:** places are assigned to days and ordered by location and opening hours.
4. **Check and refine:** real Amap routes, checks for too rushed / closed / no reservation, pick a hotel, find restaurants, weather is fetched automatically.
5. **Adjust anytime:** drag, chat or change durations; everything is re-checked after each change, and one click undoes it.
6. **Connect the whole route and take it with you:** fill in all real routes and generate a dedicated Amap App map (one loop per day), a mobile map page, WeChat-ready text or a GPX track.

## 🧩 Capabilities

| Area | What it does |
|---|---|
| **Planning** | Automatic day assignment and in-day ordering (geography + capacity + opening hours), pace (relaxed / moderate / packed), locking confirmed items, day-trip detection |
| **Checks** | Closed days, arriving after closing, past last entry, staying past closing, too rushed, long legs, missing reservations, over budget, hotel too far, weather unsuitable for outdoor sights |
| **Maps & routes** | Amap / Google Maps / OpenStreetMap; real route times, transfers and walking distance, intercity-leg hints, airport/station transfers (late-night legs switch to taxi) |
| **Lodging & food** | Where to stay per night / segment (split automatically across cities), hotel candidates ranked by commute, restaurants along the way, a named restaurant placed on the nearest day, reminders for days missing meals |
| **Local events for your dates** | Once dates are set, your personal agent follows the skill to search local concerts, sports (e.g. figure skating), lantern festivals, exhibitions and food festivals and lists them for you (the search is the agent's own ability; TripSight itself does not go online for events). When one is added, code requires a source URL, a date and a time slot; it becomes a date-locked stop scheduled only on that day and checked for timing. Never books tickets |
| **Guides → trip** | Paste a travel note or guide → each quote verified verbatim against the original → places looked up on Amap on submit (matched / ambiguous / not found) with jump links → you pick, then they are added; "Day N" markers are detected so you can compare with, or follow, the guide's day plan; each stop keeps an expandable excerpt of the guide; a walking route (e.g. a city walk) can be one item |
| **Transport & weather** | Record arrival/departure flights or trains and derive playable time on the first and last day; read-only flight / train / hotel reference prices; Amap and Open-Meteo forecasts (once the workbench is open, days within range are fetched in the background; weather shows on each day, the share page, handbook and calendar) |
| **Take it with you** | All generated locally, no login needed:<br>· Mobile map page: a single HTML/PDF file with a route map and stop list per day, works offline<br>· Amap App map: each day's route as a loop, opened day by day for navigation in the Amap app<br>· Calendar (.ics): import into your phone calendar, with times and weather per day<br>· GPX track: import into sports or other map apps |
| **After the trip: photo restore & handbook** | Rebuild the trip from a photo folder or a Mac Photos album (cluster into stay points by time and place, merge and rename, use a GPX/KML track to place photos without location); spans multiple years or just a date range; in **auto mode** (one switch in the workbench) the assistant imports, names, tags cities and fills in photos, then stops at the preview for you to export, while the left panel follows its actions and slow steps run in the background; up to 6 photos per stop, can be referenced instead of copied; produces a web handbook, one travel card per day, a **long-page PDF with clickable links** (tap "navigate" on your phone), Obsidian notes, a per-day zoomed route map and a per-day route animation GIF, optionally on an Amap basemap with line styles per transport mode and thumbnail pins; AI-assisted descriptions of photo content; **handbook and cards are editable**: stop names, notes, one line per day, cover subtitle, afterword; delete photos, change the cover, reorder; each card can get its own title, photo, line and style (tool `edit_handbook`) |
| **Spending** | Import WeChat / Alipay bills (parsed locally, never sent to the model), including from iCloud Drive; log Apple Pay via an iPhone Shortcut; stats by category, editable categories remembered per merchant, optionally added to the handbook afterword |
| **Video & footprints** | Clips assigned to stops by capture time and location and cut into a travel film in trip order, with an optional Jianying draft; footprint summary (trips, cities, approximate km) and a **zoomable footprint map** whose pins are local photo thumbnails, click to view; tick "real routes" to go online and join same-day stops along real roads |
| **Long-term memory** | Remembers preferences you state (dislike walking, no spicy food, hotel budget) and applies them to new trips; after the trip, record actual costs and ratings and get preference suggestions |
| **Engineering** | Multiple trips, version history and undo, `tripcore doctor` self-check, Apache-2.0, 600+ automated tests |

## 🔎 Data sources and verification

> - ✅ **Tested with a real key:** Amap (routes, opening hours, coordinate checks, weather).
> - 🌤️ **Weather:** in mainland China Amap weather is used first (about 4 days ahead); dates Amap doesn't cover and trips abroad use [Open-Meteo](https://open-meteo.com/) (free, no key, up to about 16 days). Every forecast is labelled with its source and query date.
> - 💰 **Prices (read-only):** flight, train and hotel reference prices come from the [Fliggy FlyAI](https://github.com/alibaba-flyai/flyai-skill) and [RollingGo](https://clawhub.ai/rollinggo-ai/skills/rollinggo-search-hotel-skill) command-line tools via skills; query only, each price labelled with source and date.
> - Prices, opening hours and weather are reference values; check official information before you go.
> The assistant **never** books tickets or hotels and never pays.

## 🏗️ Architecture and capability split

**92 MCP tools · 10 skills · 600+ automated tests**, covering plan, on the road, restore, record and footprints. The LLM only understands and proposes, tools do the work deterministically, and skills say when to use which tools and what must never be invented.

| Stage | Tools | Skills | Highlights |
|---|---|---|---|
| **Before · Plan** | 47 | `trip-planner` `trip-routes` `trip-hours-weather` `trip-food` `trip-events` `trip-sources` `flyai-search` | trip basics, stops and lodging, scheduling and checks, routes and transport, food, guides and import (`schedule_days` `check_plan` `refine_routes` `submit_candidates`…) |
| **After · Restore** | 17 | `trip-restore` | photo restore, naming, districts, day titles, handbook (`import_photo_trip` `autoname_stops` `tag_regions` `export_handbook`…) |
| **Record & share** | 13 | `trip-export` | mobile map, WeChat text, Amap App map, calendar, GPX, share images, travel film |
| **Long term** | 15 | `trip-review` | footprints, bills and spending, review, travelogue (12); preference memory (3) |

**Project layout**

```
tripcore/                core library and MCP server
├─ mcp_server.py         entry point for the 92 tools
├─ scheduler.py · validator.py · changes.py   day scheduling / rule checks / versions and undo
├─ amap.py · routemap.py · weather.py         Amap routes and maps, weather
├─ phototrip.py · photoslib.py · stays.py     photo clustering into stay points, Mac Photos reader
├─ handbook.py · share.py · video.py          handbook and cards, sharing, travel film
└─ web.py · webpage.py   web workbench (single-file page, listens on 127.0.0.1 only)
skills/                  manuals for the agent
nanobot/                 example integration config (no secrets)
scripts/                 install_skills.py · merge_nanobot_config.py
tests/                   automated tests
docs/                    setup, WorkBuddy integration, tool list
```

- nanobot is not in this repo; install it yourself. The repo only provides the skills, example config and scripts needed to connect, so upgrading nanobot never conflicts with this project.
- Data is local JSON (`trip.json`, versioned and undoable); API keys live only in your own config.

## 🔐 Safety

- The assistant **never books, pays or installs anything**; price lookups use read-only commands only.
- The web workbench listens locally only, with a one-time token; every write is checked against the revision.
- API keys are read only from environment variables or your local nanobot config; `tripcore doctor` only reports "configured / not configured"; exported text is rejected if it contains a key or a local path.
- Prices, opening hours and weather carry their source and date; when unsure, it says so instead of making things up.

## 🚀 Quick start

Requires Python 3.10+.

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
./setup.sh                  # create .venv, install, connect nanobot, install skills, self-check
source .venv/bin/activate
tripcore demo               # full demo on sample data, no keys or model needed
tripcore web --open         # web workbench only
```

Connect a chat agent: [nanobot](docs/SETUP.md) · [WorkBuddy](docs/WORKBUDDY.md) · [Claude Code and other MCP agents](docs/SETUP.md#其他-mcp-agent) (guides in Chinese). Then just say where you want to go; to see the map or export, say **"open the workbench"**.

## 📚 More docs

- [docs/SETUP.md](docs/SETUP.md): install; connect nanobot and other MCP agents; WeChat; Google Maps
- [docs/WORKBUDDY.md](docs/WORKBUDDY.md): connect WorkBuddy
- [docs/TOOLS.md](docs/TOOLS.md): the full list of 92 tools

## 📄 License

Apache License 2.0 — see [LICENSE](LICENSE).
