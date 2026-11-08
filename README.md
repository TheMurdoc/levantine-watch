# Levantine Watch

Near-live open-source intelligence dashboard for Cyprus, the Levant and the Eastern Mediterranean.

**Live:** https://themurdoc.github.io/levantine-watch/

## What's on the map

| Layer | Snapshot source | Opens in (origin app) | Cross-check links |
|---|---|---|---|
| Aircraft | Flightradar24 | Flightradar24 (live flight) | ADS-B Exchange, airplanes.live, adsb.fi, FlightAware, RadarBox, Planespotters |
| Vessels | Global Fishing Watch AIS + Datalastic IDs | VesselFinder, MarineTraffic, MyShipTracking | BalticShipping, MarineTraffic area map, GFW |
| GNSS interference | Wingbits NACp per H3 hex | GPSJam (same day and area) | FR24 GPS-jamming map |
| Military / energy / industrial / water / waste | OpenStreetMap | Exact OSM element (node/way) | OSM features-at-point, Google satellite, Bing aerial, Wikimapia |
| Cell towers / masts | OpenStreetMap | Exact OSM element | OpenCellID, CellMapper (Cyta, Epic, PrimeTel) |
| Cell coverage bins | OpenCellID (MCC 280) | OpenCellID | CellMapper per operator |
| Wi-Fi access points | WiGLE (names withheld) | WiGLE map | OSM, Google satellite |
| Places | TomTom / Mapbox Search | OpenStreetMap | Google Maps, Apple Maps |
| Natural hazards (live) | GDACS | GDACS event report | EMSC, USGS, NASA FIRMS (wildfires), Copernicus EMS |
| NAVTEX / navigational warnings | SeaLagom warning feed (Cyprus, Antalya, Izmir and Hellenic coastal stations, NAVAREA III) and the repository inbox (issues labelled `navtex`) | The SeaLagom message page, or the source link in a pasted message | OSM at the first point, VesselFinder / MarineTraffic for named survey and cable ships |
| Airspace NOTAMs (restricted / danger areas, firing, exercises, GNSS, drones) | FAA NOTAM Management Service (NMS-API) | FAA NOTAM Search | OSM at the centre, GPSJam for GNSS NOTAMs |
| Anything on Cyprus, or any point clicked on the island | Department of Lands and Surveys (DLS), live | DLS parcel / topographic / marine map at that spot | DLS cadastral portal, Company registry (DRCOR), CyLaw, CYTA Yellow Pages |

Click any marker, hexagon or table row to get its **Open in …** buttons. The **Open in source app on click** chip makes a click jump straight to the origin app instead.

## Live data

A scheduled GitHub Actions job (`.github/workflows/live.yml`) runs `collector/collect.py` about every 10 minutes and redeploys the site with a fresh `data/live.json`. Every source is optional: without its secret it is simply skipped and shown as "not configured" under Data provenance.

| Layer | Source | Secret(s) | Refresh / cost control |
|---|---|---|---|
| Aircraft | airplanes.live (fallback adsb.lol, adsb.fi), 29–37.3 N, 23–40.2 E: Crete, Rhodes and the Turkish south-west coast to the Levant | none | every run, 5 requests |
| Aircraft (optional) | AirNav Radar On Demand API `POST /flights/live` over the same box | `AIRNAV_API_TOKEN` | only with `AIRNAV_MODE=area`, or automatically when every ADS-B aggregator fails; every 30 min |
| Flight routes, operator | Flightradar24 API, then AirNav Radar, then FlightAware AeroAPI | `FR24_API_TOKEN`, `AIRNAV_API_TOKEN`, `FLIGHTAWARE_API_KEY` | military/state first, ≤15 + ≤20 + ≤5 callsigns per run, cached 6 h; AirNav at most every 30 min and 48 requests a day |
| GNSS interference | Wingbits `/v1/gps/jam` (fallback: ADS-B NACp, rolling 6 h), H3 hexagons over the same wide box; each Wingbits hexagon also carries the UTC day's aggregate (`/v1/gps/jam?date=`, every 3 h: day NACp, aircraft-hours, GPS-lost aircraft-hours located by MLAT, ADS-B-only NACp) and the ADS-B aggregator NACp for the same area as a cross-check. Wingbits' customer API has no spoofing endpoint | `WINGBITS_API_KEY` | every 30 min |
| Vessels | aisstream.io live AIS: the map box plus the Crete–Cyprus cable corridor (33.3–36.2 N, 23.5–32.0 E) | `AISSTREAM_API_KEY` | 90 s listen per run; `AIS_CORRIDOR=0` drops the corridor box |
| Vessels near port | Data Docked vessels-by-area (terrestrial AIS, one 50 km circle off Limassol) | `DATADOCKED_API_KEY` | **1 call per week**, positions shown for 24 h (`DATADOCKED_EVERY_MIN`, `DATADOCKED_KEEP_HOURS`; more circles via `DATADOCKED_AREAS`) |
| Vessel details | Datalastic `vessel_info`, then Data Docked particulars as fallback | `DATALASTIC_API_KEY`, `DATADOCKED_API_KEY` | only incomplete ships; Datalastic ≤15 per run, Data Docked **1 per week**; cached 30 days |
| Headlines + news events | RSS (Cyprus Mail, in-cyprus, BBC, Al Jazeera) + GDELT DOC 2.0, placed on the map by place name | none (optional `NEWSAPI_KEY`) | every run |
| Thermal hotspots | NASA FIRMS (VIIRS SNPP/NOAA-20/NOAA-21 + MODIS, 24 h) | `FIRMS_MAP_KEY` | every run, 4 requests |
| Internet outages | Cloudflare Radar outage annotations, 14 days | `CLOUDFLARE_API_TOKEN` | hourly |
| Natural hazards | GDACS (earthquakes, floods, wildfires, cyclones, volcanoes, droughts), last 30 days, per country: Cyprus, Türkiye, Syria, Lebanon, Israel, Palestine, Jordan, Egypt | none | hourly, about 8 requests |
| Humanitarian context | HDX HAPI: INFORM national risk, IOM DTM displacement, IPC food insecurity, OCHA FTS appeal funding | `HAPI_APP_IDENTIFIER` | every 12 h, 10 requests |
| NAVTEX warnings (station feeds) | SeaLagom open JSON feeds of the warnings in force for Irakleio NAVTEX (Crete), Antalya NAVTEX, Izmir NAVTEX, Cyprus (JRCC Larnaca), the Hellenic NAVWARN service and NAVAREA III. Irakleio is only published this way. Number, validity, coordinates and shape are parsed here with the same parser as the inbox; warnings outside 29–37.3 N, 23–40.2 E are dropped | none | every hour (`SEALAGOM_FEED_EVERY_MIN`), one request per station; change the list with `SEALAGOM_FEEDS` |
| NAVTEX warnings (API) | SeaLagom `GET /api/v2/messages/`: every other warning in force whose SeaLagom position falls in the box, text only | `SEALAGOM_API_TOKEN` | every 2 h (`SEALAGOM_EVERY_MIN`), up to 4 calls per pull (`SEALAGOM_MAX_PAGES`); a free developer key allows about 100 calls a day |
| NAVTEX warnings (inbox) | Your own issues labelled `navtex` (or `navtex/*.txt` files), parsed for number, validity, coordinates and area / route / positions | none (the workflow reads the issues with its own token) | every run, and immediately when you open, edit, label or close a `navtex` issue |
| Airspace NOTAMs | FAA NMS-API `/nmsapi/v1/notams` for LCCC, LCLK, LCPH, LCRA, LLLL, OLBB, OSTT, OJAC, LTAA, LTAI, HECC, LGGG, LGIR plus three radius searches | `NMS_CLIENT_ID`, `NMS_CLIENT_SECRET` (+ variable `NMS_ENV`) | every 30 min (`NMS_EVERY_MIN`), about 17 requests; the access token is fetched each time and never stored |

Caps can be changed in the workflow (`FR24_MAX_PER_RUN`, `AIRNAV_MAX_PER_RUN`, `AIRNAV_MAX_PER_DAY`, `FLIGHTAWARE_MAX_PER_RUN`, `DATALASTIC_MAX_PER_RUN`, `DATADOCKED_MAX_PER_RUN`). The **ALL** button on the map (key W) shows the whole collector area from Crete to the Levant; **GSI** (key G) flies to the cable corridor and **RST** back to the Levant view. Infrastructure, places, cell and Wi-Fi layers stay a static snapshot. The page checks for new data every minute and reloads itself, keeping your map view (if a panel is open it shows **New data · click to refresh** instead).

**Licensing:** the site and `data/live.json` are public. Paid feeds (Flightradar24, AirNav Radar, FlightAware, Datalastic, Data Docked, Wingbits) have terms on redistribution and attribution; check your plan allows public display before enabling them. SeaLagom relays public broadcast text; the page links every warning back to its SeaLagom page and names the issuing station. Read the SeaLagom API terms for your plan before enabling it on a public site. GDACS asks for attribution only. HDX HAPI datasets keep their own licences and are credited on the page. The FAA NMS-API is available on request and its onboarding terms were not public when this was written: read the terms you receive before turning it on for this public site. NOTAMs are operational notices, not a navigation source.

**ACLED is not used on this public site.** Its licence does not allow ACLED data (including the ACLED-derived HDX HAPI `conflict-events` endpoint) to be published or made available through a dashboard. The collector never calls ACLED, ignores ACLED credentials if they are set, and the workflow refuses to deploy if `live.json` or `state.json` ever contains conflict data.

### One-time setup
1. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. **Settings → Secrets and variables → Actions → New repository secret** for each key you have (names above). Get `HAPI_APP_IDENTIFIER` free from the Utility section of https://hapi.humdata.org/docs, and `SEALAGOM_API_TOKEN` from your SeaLagom account (API → tokens), and `AIRNAV_API_TOKEN` from the AirNav Radar API dashboard (see AirNav Radar below). Do not add ACLED secrets here.
3. Optional: **Issues → Labels → New label** `navtex` for the NAVTEX inbox, and the FAA NMS secrets `NMS_CLIENT_ID` / `NMS_CLIENT_SECRET` plus a repository **variable** `NMS_ENV` (see Airspace NOTAMs below).
4. **Actions → Live data → Run workflow** for the first run; the "Collect live data" log lists every source as `OK` or `--` with the reason.

### Adding or rotating a secret without pasting it anywhere

A repository secret is encrypted by GitHub when you save it and is only ever decrypted inside the Actions runner. Nothing in this repository, in `data/`, in the page or in the Actions log contains it (the collector prints source names and counts, never credentials).

- **Browser:** Settings → Secrets and variables → Actions → *New repository secret* (or the pencil next to an existing name to replace its value). Paste the value straight from the provider's page into the GitHub form. The names the collector expects are in the table above; a wrong name is simply "not configured".
- **Terminal, from a file:** with the GitHub CLI installed and logged in (`gh auth login`), `gh secret set WINGBITS_API_KEY < wingbits.key` reads the value from a file, so it never appears in your shell history or on screen. `gh secret set NMS_CLIENT_SECRET` with no redirect prompts for it invisibly.
- **FAA NMS:** the `-u <CLIENT_ID>:<CLIENT_SECRET>` pair from the FAA's curl examples is HTTP basic authentication, which the collector sends from the two secrets (`collector/nms.py` posts `grant_type=client_credentials` with `auth=(NMS_CLIENT_ID, NMS_CLIENT_SECRET)`). The bearer token it receives lives about 30 minutes, is used for that run's requests and is never written to `state.json`.
- Keep local copies in a `.env` file that is listed in `.gitignore` (this repository ignores `.env` and `*.env`). Never paste a key into a chat, an issue or a commit message; if one has been, rotate it at the provider and replace the secret.

Notes: scheduled runs can start late and GitHub pauses schedules after 60 days without repository activity (re-enable in the Actions tab). The ADS-B APIs are free for non-commercial use and rate-limited. Run locally with `pip install -r collector/requirements.txt && python collector/collect.py --out data`, then serve the folder (`python -m http.server`).

## Cyprus registries

Select anything located on Cyprus (a site, place, cell tower, GNSS hexagon, hazard, news event) or click any point on the island, and the panel adds a **Cyprus registries · DLS live** section:

- **Land registry facts from the Department of Lands and Surveys**, queried live from your browser: district, municipality or community, quarter, postcode, sheet / plan / block / parcel number and area, planning zone, development plan, state land and coast protection zone. Vessels near Cyprus get the marine equivalent instead: port area, named submarine cables and pipelines within 2 km.
- **DLS map here**: a cadastral, topographic or marine map image of that exact spot rendered by DLS.
- **Company registry (DRCOR)** and **CYTA Yellow Pages**: these sites have no search links, so the button copies the selected name and opens the search form for you to paste it.
- **CyLaw**: court judgments and legislation search for the selected name, vessel or community.

The **DLS** map button (or `D`) cycles DLS overlays drawn over Cyprus for the current view: administrative boundaries, topographic (roads, power lines, airfields, Natura 2000), marine & energy (cables, pipelines, ports, power and desalination plants), and planning zones & postcodes.

Nothing from these registries is stored in this repository or in `data/`; the browser asks DLS directly. DLS data © Department of Lands and Surveys, Republic of Cyprus. Source list via the [OSINT map by Cyber Detective](https://cybdetective.com/osintmap/).

## Cable corridor (GSI) view

The map now reaches west to Crete so the Great Sea Interconnector (Crete–Cyprus cable) survey area fits. The **GSI** map button (or `G`) frames the corridor: every mapped cable or survey warning, widened to take in western Cyprus. AIS listens to that corridor as well, so survey and support ships show up there. The survey ships the collector watches for are in `WATCH_VESSELS` in `collector/navtex.py`; only *Abeille Marengo* (MMSI 228505700, IMO 9388613, AIS name "VB ABEILLE MARENGO") has been checked against public vessel registers, so verify the others before relying on them.

## AirNav Radar (flight routes, optional aircraft source)

AirNav Radar, formerly RadarBox, sells the On Demand API at https://www.airnavradar.com/api. A business account comes with a free token in the API dashboard, and every answer is charged in credits and reports its own `cost`. The collector calls one endpoint, `POST https://api.airnavradar.com/v2/flights/live`, with `Authorization: Bearer <token>`.

- **Routes (default, `AIRNAV_MODE=routes`).** Callsigns that Flightradar24 did not resolve, or all of them when there is no FR24 token, are looked up in one request of up to 20 callsigns. Departure and arrival airports, operator and flight number go into the same 6 h route cache as FR24 and FlightAware, and the aircraft panel says which service supplied the route.
- **Area (`AIRNAV_MODE=routes,area`).** One request for every live flight in 29–37.3 N, 23–40.2 E. Aircraft that the free ADS-B aggregators did not report are added to the map with the source "AirNav Radar". This mode also switches itself on for a run in which airplanes.live, adsb.lol and adsb.fi all fail.
- **Spend control.** At most one AirNav request every 30 min per mode (`AIRNAV_EVERY_MIN`) and 48 a day in total (`AIRNAV_MAX_PER_DAY`, reset at 00:00 UTC). The provenance line shows the credits each call cost, so you can size the plan before turning area mode on.

Add the token as the repository secret `AIRNAV_API_TOKEN`, the same way as the other secrets. Without it the provenance list shows "AirNav Radar: not configured" and nothing is called. The API terms decide whether AirNav data may be shown on a public page: check your plan before enabling it.

## Warning feed (SeaLagom)

[SeaLagom](https://www.sealagom.com) collects NAVAREA and coastal / NAVTEX broadcasts worldwide and offers them through open per-station feeds and an API.

**Station feeds, no key.** Every hour the collector reads SeaLagom's JSON feed of the warnings in force for each station around the map: Irakleio NAVTEX on Crete (`coastal/82`), Antalya (`coastal/33`), Izmir (`coastal/32`), Cyprus (`coastal/128`), the Hellenic NAVWARN service (`coastal/86`) and NAVAREA III (`navarea/3`). Irakleio's messages are not in SeaLagom's API index, so the feed is the only route to them, and Irakleio is the station that broadcasts the Crete side of the GSI corridor (for example `IRAKLEIO NAVWARN 1411/26`, the *Abeille Marengo* cable route, and `1404/26`, the *Kobi Ruegg* survey). Other stations can be added with `SEALAGOM_FEEDS`, for example `coastal/84` for Limnos or `coastal/186` for the Suez Canal Authority. The same Irakleio broadcast pasted into the inbox is recognised by its NAVTEX transmitter letter and number and shown once.

**API, with `SEALAGOM_API_TOKEN`.** The collector also asks every two hours for the warnings in force whose position falls inside the map box, from Crete to the Levant (`bbox=23,29,40.2,37.3`, overridable with `SEALAGOM_BBOX`). Only the warning text is used: SeaLagom's own parsed positions and analysis are paid features, and the dashboard's parser reads the coordinates, validity, vessel names, MMSI / IMO numbers and shape from the text exactly as it does for pasted messages. Turkish broadcasts (Antalya, Izmir: `K`/`D` for north/east) and the English translations SeaLagom provides are both understood; a warning whose text cannot be parsed is still listed, without a shape.

What this adds for the GSI cable corridor: the Cyprus (JRCC Larnaca), Antalya and Hellenic stations are the ones that announce survey and cable-laying areas there, so the *Abeille Marengo* GSI survey polygon, the Cyprus–Lebanon cable route and similar notices appear on the map within two hours of broadcast, with a link to the SeaLagom page and, when the ship is in the AIS feed, a ring around it.

Numbers are prefixed with the station (`IRAKLEIO NAVWARN 1411/26`, `ANTALYA NAVTEX 1111/26`, `HELLENIC NAVWARN 1343/26`) because stations reuse the same sequence; Cyprus warnings keep the plain `NAVWARN 345/26` form, so a warning you also paste into the inbox is recognised as the same one. Warnings whose validity starts within 14 days (`NAVTEX_UPCOMING_DAYS`) are kept and marked *upcoming*. The free developer key allows about 100 calls a day; one pull is one to four calls, so the default cadence uses under half of it. 401 / 403 / 429 answers are reported under Data provenance and the last good pull stays on the map.

## NAVTEX inbox

There is no open API for the Irakleio, Antalya or Cyprus NAVTEX stations, but the warning text is public. SeaLagom (above) relays it; the inbox is for anything it misses or for a message you receive first. To put one on the map:

1. Open an issue in this repository with the label `navtex` and paste the full message (header, number, times, coordinates) as the body. Several messages can go in one issue.
2. The workflow runs straight away and the warning appears as an area, route or set of positions, with its validity, station and any named vessel.
3. **Close the issue** to withdraw the warning. A pasted `CANCEL NAVWARN 1411/26` message also removes that number.

Details:

- Only issues **you** open are read (the repository owner, or the logins in `NAVTEX_ALLOWED_AUTHORS`). Issues from anyone else are ignored and do not start a run.
- The workflow reads the issues in a separate step and hands the collector a file (`NAVTEX_INBOX_FILE`), so the collector never holds a GitHub token.
- Coordinates in degrees–decimal-minutes (`34-40.5N 032-20.0E`) and degrees–minutes–seconds (`344030N 0322000E`) are both understood. Wording decides the drawing: AREA / BOUNDED BY → polygon, LINE / ALONG / ROUTE / CABLE → line, numbered POSITIONS or BUOYS → separate points.
- A warning with no validity time is dropped 30 days after its date-time group, or after the issue was opened if it has none (`NAVTEX_MAX_DAYS`).
- `.txt` files in a `navtex/` folder are read too. Keep notes there as `.md`, because every `.txt` file is parsed as a warning.
- Warnings are published in `data/live.json` like every other layer. Paste only messages that are already public.

## Airspace NOTAMs (FAA NMS)

The FAA NOTAM Management Service API (NMS-API) returns NOTAMs worldwide, including the Nicosia FIR (LCCC) and its neighbours. The collector keeps restricted / danger areas, firing, exercises, drone activity, GNSS outages and airspace changes (ICAO Q-code subjects R, W, G, A; change with `NMS_SUBJECTS`) that are active now or start within 7 days. NMS returns no area geometry, so areas are read from the coordinates written in the NOTAM text (polygons, and "600M RADIUS OF PSN …" circles); otherwise the Q-line centre and radius are drawn. NOTAMs covering the whole FIR (radius 150 NM or more) are listed but not drawn, and cancellation NOTAMs (NOTAMC) are dropped. The **Airspace NOTAMs** card has filter chips per category and shows each NOTAM's active hours (item D).

Setup:

1. Request access from the FAA (NMS-API onboarding). You receive a client ID and secret, first for the **staging** environment.
2. Add the repository secrets `NMS_CLIENT_ID` and `NMS_CLIENT_SECRET`, and a repository **variable** `NMS_ENV` set to `staging` (or `fit`). Without the variable the collector uses `prod`.
3. Once production access is granted, change `NMS_ENV` to `prod`. Staging is the FAA test system: on 7 Nov 2026 it returned current Nicosia FIR NOTAMs, but it is not guaranteed to match production, and the page says which environment the data came from.

Optional settings: `NMS_LOCATIONS` (comma list of FIR / aerodrome codes), `NMS_GEO` (`lat,lon,radius;…` with the radius in NM, or `off`), `NMS_SUBJECTS` (Q-code subject letters, `*` for all), `NMS_FORMAT` (`AIXM`, the default, or `GEOJSON`), `NMS_EVERY_MIN` (default 30).

**How fresh the NOTAMs are when you open the page.** The page is static: it cannot call the NMS-API itself, because the client secret would then be visible to every visitor and the API does not allow browser (CORS) requests. Instead the collector fetches a token and the NOTAMs on GitHub's runner every `NMS_EVERY_MIN` minutes (the job itself runs every ~10 minutes), and the page downloads the latest `data/live.json` every time it is opened and checks for a newer one every minute while it stays open. So on launch the NOTAM layer is at most about 30 to 40 minutes behind the FAA, and it keeps updating without a reload. The **NOTAMs** chip in the layer bar toggles the layer; the *Airspace NOTAMs* card shows the count, the FAA environment the data came from and filter chips per category. To refresh more often, lower `NMS_EVERY_MIN` in `.github/workflows/live.yml` (each refresh is about 17 requests; check your FAA quota first).

Checked against a real staging answer (a 100 NM search off Paphos, 115 NOTAMs): the collector asks for AIXM, which comes back as a list of AIXM 5.1 messages, and the search radius is in NM. A trimmed copy is the test fixture `collector/tests/nms_aixm_lccc_sample.json`. Still unverified: the GeoJSON layout, paging of very long answers, and the production token URL (assumed to be `https://api-nms.aim.faa.gov/v1/auth/token`, matching the staging pattern). Check the **FAA NMS NOTAMs** line under Data provenance (or the "Collect live data" log): it reports how many NOTAMs were kept per category, which locations returned nothing and any errors.

## Aircraft and vessel symbols

- **Aircraft**: the icon comes from the ICAO type code (wide-body, narrow-body, regional, turboprop, business jet, light, helicopter, fighter, military transport, tanker, AEW/ISR, drone). Known military/state callsigns and serials switch the icon to the military colour. The icon is rotated to the aircraft's track and sized by class.
- **Vessels**: side-profile icons grouped and coloured using MarineTraffic/VesselFinder ship-type groups (Cargo, Tanker, Passenger, High-speed, Tugs & special craft, Fishing, Pleasure, Navigation aids, Unspecified). Naval types (frigate/destroyer, corvette, patrol, submarine, carrier/amphibious) are in *Tugs & special craft*, the same group MarineTraffic uses for military ops. Icons are sized by hull length.
- The **Symbol key** card on the page lists every class and how many are in the snapshot.

## Map controls

- Drag to pan, scroll or pinch to zoom, `[` `]` to rotate, `0` to reset
- **◐** (or `O`) cycles border outline styles: Tactical glow, Crisp lines, High contrast, Minimal
- **OSM** opens the current map view in OpenStreetMap
- **DLS** (or `D`) cycles Cyprus overlays from the Department of Lands and Surveys
- **GSI** (or `G`) frames the Crete–Cyprus cable corridor
- Zoom goes to 24x so DLS boundaries and plans can be read

## Caveats

Live layers are collected every ~10 minutes and can be minutes old; the other layers are a 28 Sep 2026 snapshot. GNSS degradation is consistent with jamming or spoofing but does not prove either. Places are commercial listings, not verified infrastructure. NAVTEX and NOTAM shapes are parsed from free text and can be incomplete; the full message is always in the panel. Cross-check everything before treating it as ground truth.

## Run locally

`index.html` works on its own (it falls back to the embedded 28 Sep snapshot when `data/live.json` is missing). For live data locally, run the collector as above and serve the folder.

---
Built by [@TheMurdoc](https://github.com/TheMurdoc).
