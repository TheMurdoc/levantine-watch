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

Click any marker, hexagon or table row to get its **Open in …** buttons. The **Open in source app on click** chip makes a click jump straight to the origin app instead.

## Live data

A scheduled GitHub Actions job (`.github/workflows/live.yml`) runs `collector/collect.py` about every 10 minutes and redeploys the site with a fresh `data/live.json`. Every source is optional: without its secret it is simply skipped and shown as "not configured" under Data provenance.

| Layer | Source | Secret(s) | Refresh / cost control |
|---|---|---|---|
| Aircraft | airplanes.live (fallback adsb.lol, adsb.fi) | none | every run, 4 requests |
| Flight routes, operator | Flightradar24 API, FlightAware AeroAPI fallback | `FR24_API_TOKEN`, `FLIGHTAWARE_API_KEY` | military/state first, ≤15 + ≤5 callsigns per run, cached 6 h |
| GNSS interference | Wingbits `/v1/gps/jam` (fallback: ADS-B NACp, rolling 6 h) | `WINGBITS_API_KEY` | every 30 min |
| Vessels | aisstream.io live AIS | `AISSTREAM_API_KEY` | 90 s listen per run |
| Vessels near port | Data Docked vessels-by-area (terrestrial AIS, one 50 km circle off Limassol) | `DATADOCKED_API_KEY` | **1 call per week**, positions shown for 24 h (`DATADOCKED_EVERY_MIN`, `DATADOCKED_KEEP_HOURS`; more circles via `DATADOCKED_AREAS`) |
| Vessel details | Datalastic `vessel_info`, then Data Docked particulars as fallback | `DATALASTIC_API_KEY`, `DATADOCKED_API_KEY` | only incomplete ships; Datalastic ≤15 per run, Data Docked **1 per week**; cached 30 days |
| Headlines + news events | RSS (Cyprus Mail, in-cyprus, BBC, Al Jazeera) + GDELT DOC 2.0, placed on the map by place name | none (optional `NEWSAPI_KEY`) | every run |
| Thermal hotspots | NASA FIRMS (VIIRS SNPP/NOAA-20/NOAA-21 + MODIS, 24 h) | `FIRMS_MAP_KEY` | every run, 4 requests |
| Internet outages | Cloudflare Radar outage annotations, 14 days | `CLOUDFLARE_API_TOKEN` | hourly |
| Conflict events | ACLED, last 30 days | `ACLED_EMAIL`, `ACLED_PASSWORD` | every 6 h |

Caps can be changed in the workflow (`FR24_MAX_PER_RUN`, `FLIGHTAWARE_MAX_PER_RUN`, `DATALASTIC_MAX_PER_RUN`, `DATADOCKED_MAX_PER_RUN`). Infrastructure, places, cell and Wi-Fi layers stay a static snapshot. The page checks for new data every minute and reloads itself, keeping your map view (if a panel is open it shows **New data · click to refresh** instead).

**Licensing:** the site and `data/live.json` are public. Paid feeds (Flightradar24, FlightAware, Datalastic, Data Docked, Wingbits) and ACLED have terms on redistribution and attribution; check your plan allows public display before enabling them.

### One-time setup
1. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. **Settings → Secrets and variables → Actions → New repository secret** for each key you have (names above).
3. **Actions → Live data → Run workflow** for the first run; the "Collect live data" log lists every source as `OK` or `--` with the reason.

Notes: scheduled runs can start late and GitHub pauses schedules after 60 days without repository activity (re-enable in the Actions tab). The ADS-B APIs are free for non-commercial use and rate-limited. Run locally with `pip install -r collector/requirements.txt && python collector/collect.py --out data`, then serve the folder (`python -m http.server`).

## Aircraft and vessel symbols

- **Aircraft**: the icon comes from the ICAO type code (wide-body, narrow-body, regional, turboprop, business jet, light, helicopter, fighter, military transport, tanker, AEW/ISR, drone). Known military/state callsigns and serials switch the icon to the military colour. The icon is rotated to the aircraft's track and sized by class.
- **Vessels**: side-profile icons grouped and coloured using MarineTraffic/VesselFinder ship-type groups (Cargo, Tanker, Passenger, High-speed, Tugs & special craft, Fishing, Pleasure, Navigation aids, Unspecified). Naval types (frigate/destroyer, corvette, patrol, submarine, carrier/amphibious) are in *Tugs & special craft*, the same group MarineTraffic uses for military ops. Icons are sized by hull length.
- The **Symbol key** card on the page lists every class and how many are in the snapshot.

## Map controls

- Drag to pan, scroll or pinch to zoom, `[` `]` to rotate, `0` to reset
- **◐** (or `O`) cycles border outline styles: Tactical glow, Crisp lines, High contrast, Minimal
- **OSM** opens the current map view in OpenStreetMap

## Caveats

Live layers are collected every ~10 minutes and can be minutes old; the other layers are a 28 Sep 2026 snapshot. GNSS degradation is consistent with jamming or spoofing but does not prove either. Places are commercial listings, not verified infrastructure. Cross-check everything before treating it as ground truth.

## Run locally

`index.html` works on its own (it falls back to the embedded 28 Sep snapshot when `data/live.json` is missing). For live data locally, run the collector as above and serve the folder.

---
Built by [@TheMurdoc](https://github.com/TheMurdoc).
