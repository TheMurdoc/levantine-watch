# Levantine Watch

Open-source intelligence snapshot of Cyprus, the Levant and the Eastern Mediterranean, as a single-file dashboard.

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

## Map controls

- Drag to pan, scroll or pinch to zoom, `[` `]` to rotate, `0` to reset
- **◐** (or `O`) cycles border outline styles: Tactical glow, Crisp lines, High contrast, Minimal
- **OSM** opens the current map view in OpenStreetMap

## Caveats

This is a static snapshot (28 Sep 2026), not a live feed. GNSS degradation is consistent with jamming or spoofing but does not prove either. Places are commercial listings, not verified infrastructure. Cross-check everything before treating it as ground truth.

## Run locally

It's one HTML file with no build step: open `index.html` in a browser, or run `python3 -m http.server` and go to http://localhost:8000.

---
Built by [@TheMurdoc](https://github.com/TheMurdoc).
