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
| NAVTEX / navigational warnings | Repository inbox (issues labelled `navtex`) | Source link in the message, if any | OSM at the first point, VesselFinder for named survey ships |
| Airspace NOTAMs (restricted / danger areas, firing, exercises, GNSS, drones) | FAA NOTAM Management Service (NMS-API) | FAA NOTAM Search | OSM at the centre, GPSJam for GNSS NOTAMs |
| Anything on Cyprus, or any point clicked on the island | Department of Lands and Surveys (DLS), live | DLS parcel / topographic / marine map at that spot | DLS cadastral portal, Company registry (DRCOR), CyLaw, CYTA Yellow Pages |

Click any marker, hexagon or table row to get its **Open in …** buttons. The **Open in source app on click** chip makes a click jump straight to the origin app instead.

## Live data

A scheduled GitHub Actions job (`.github/workflows/live.yml`) runs `collector/collect.py` about every 10 minutes and redeploys the site with a fresh `data/live.json`. Every source is optional: without its secret it is simply skipped and shown as "not configured" under Data provenance.

| Layer | Source | Secret(s) | Refresh / cost control |
|---|---|---|---|
| Aircraft | airplanes.live (fallback adsb.lol, adsb.fi) | none | every run, 4 requests |
| Flight routes, operator | Flightradar24 API, FlightAware AeroAPI fallback | `FR24_API_TOKEN`, `FLIGHTAWARE_API_KEY` | military/state first, ≤15 + ≤5 callsigns per run, cached 6 h |
| GNSS interference | Wingbits `/v1/gps/jam` (fallback: ADS-B NACp, rolling 6 h) | `WINGBITS_API_KEY` | every 30 min |
| Vessels | aisstream.io live AIS: the map box plus the Crete–Cyprus cable corridor (33.3–36.2 N, 23.5–32.0 E) | `AISSTREAM_API_KEY` | 90 s listen per run; `AIS_CORRIDOR=0` drops the corridor box |
| Vessels near port | Data Docked vessels-by-area (terrestrial AIS, one 50 km circle off Limassol) | `DATADOCKED_API_KEY` | **1 call per week**, positions shown for 24 h (`DATADOCKED_EVERY_MIN`, `DATADOCKED_KEEP_HOURS`; more circles via `DATADOCKED_AREAS`) |
| Vessel details | Datalastic `vessel_info`, then Data Docked particulars as fallback | `DATALASTIC_API_KEY`, `DATADOCKED_API_KEY` | only incomplete ships; Datalastic ≤15 per run, Data Docked **1 per week**; cached 30 days |
| Headlines + news events | RSS (Cyprus Mail, in-cyprus, BBC, Al Jazeera) + GDELT DOC 2.0, placed on the map by place name | none (optional `NEWSAPI_KEY`) | every run |
| Thermal hotspots | NASA FIRMS (VIIRS SNPP/NOAA-20/NOAA-21 + MODIS, 24 h) | `FIRMS_MAP_KEY` | every run, 4 requests |
| Internet outages | Cloudflare Radar outage annotations, 14 days | `CLOUDFLARE_API_TOKEN` | hourly |
| Natural hazards | GDACS (earthquakes, floods, wildfires, cyclones, volcanoes, droughts), last 30 days, per country: Cyprus, Türkiye, Syria, Lebanon, Israel, Palestine, Jordan, Egypt | none | hourly, about 8 requests |
| Humanitarian context | HDX HAPI: INFORM national risk, IOM DTM displacement, IPC food insecurity, OCHA FTS appeal funding | `HAPI_APP_IDENTIFIER` | every 12 h, 10 requests |
| NAVTEX warnings | Your own issues labelled `navtex` (or `navtex/*.txt` files), parsed for number, validity, coordinates and area / route / positions | none (the workflow reads the issues with its own token) | every run, and immediately when you open, edit, label or close a `navtex` issue |
| Airspace NOTAMs | FAA NMS-API `/nmsapi/v1/notams` for LCCC, LCLK, LCPH, LCRA, LLLL, OLBB, OSTT, OJAC, LTAA, LTAI, HECC, LGGG, LGIR plus three radius searches | `NMS_CLIENT_ID`, `NMS_CLIENT_SECRET` (+ variable `NMS_ENV`) | every 30 min (`NMS_EVERY_MIN`), about 17 requests; the access token is fetched each time and never stored |

Caps can be changed in the workflow (`FR24_MAX_PER_RUN`, `FLIGHTAWARE_MAX_PER_RUN`, `DATALASTIC_MAX_PER_RUN`, `DATADOCKED_MAX_PER_RUN`). Infrastructure, places, cell and Wi-Fi layers stay a static snapshot. The page checks for new data every minute and reloads itself, keeping your map view (if a panel is open it shows **New data · click to refresh** instead).

**Licensing:** the site and `data/live.json` are public. Paid feeds (Flightradar24, FlightAware, Datalastic, Data Docked, Wingbits) have terms on redistribution and attribution; check your plan allows public display before enabling them. GDACS asks for attribution only. HDX HAPI datasets keep their own licences and are credited on the page. The FAA NMS-API is available on request and its onboarding terms were not public when this was written: read the terms you receive before turning it on for this public site. NOTAMs are operational notices, not a navigation source.

**ACLED is not used on this public site.** Its licence does not allow ACLED data (including the ACLED-derived HDX HAPI `conflict-events` endpoint) to be published or made available through a dashboard. The collector never calls ACLED, ignores ACLED credentials if they are set, and the workflow refuses to deploy if `live.json` or `state.json` ever contains conflict data.

### One-time setup
1. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. **Settings → Secrets and variables → Actions → New repository secret** for each key you have (names above). Get `HAPI_APP_IDENTIFIER` free from the Utility section of https://hapi.humdata.org/docs. Do not add ACLED secrets here.
3. Optional: **Issues → Labels → New label** `navtex` for the NAVTEX inbox, and the FAA NMS secrets `NMS_CLIENT_ID` / `NMS_CLIENT_SECRET` plus a repository **variable** `NMS_ENV` (see Airspace NOTAMs below).
4. **Actions → Live data → Run workflow** for the first run; the "Collect live data" log lists every source as `OK` or `--` with the reason.

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

## NAVTEX inbox

There is no open API for the Irakleio, Antalya or Cyprus NAVTEX stations, but the warning text is public. To put one on the map:

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
