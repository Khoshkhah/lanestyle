# lanestyle

**Standalone** lane-level maps from a [duckOSM](../duckOSM) **GMNS** db. No dependency on mapstyle (or
any renderer beyond folium) — a self-contained lane-level companion to the road-level maps.

lanestyle reads `gmns_<mode>.lane` (the drive-side offset centerline + width), buffers each lane into a
**surface polygon** coloured by use (auto / bus / bike), and draws it on an interactive **WebGL** map
(deck.gl + maplibre) with a **base-layer selector** (OSM · osm-carto / Carto light / Carto dark /
satellite), **click-to-inspect** each lane, **street names** and **one-way arrows**. An optional
**lane route** (from duckOSM's `route-lanes`) is drawn on top. A `folium` backend is also available
(`backend="folium"`).

```python
from lanestyle import render_lane_map, render_lane_debug

DB = "../duckOSM/data/db/sodermalm_pbf_gmns.duckdb"   # a duckOSM GMNS db (duckosm gmns)
render_lane_map(DB, "lanes.html")                     # lanes by use + base-layer selector

# a route (produced by duckOSM):  duckosm route-lanes DB <from> <to> -o route.geojson
render_lane_debug(DB, "lanes_debug.html", route_geojson="route.geojson")
```

`render_lane_debug` adds: hover **and** click each lane for its `use` / lane # / `edge_id` / width,
per-use toggles, the base-layer selector, street-name labels and one-way arrows.

## Install / run

Deps: `geopandas`, `duckdb`, `folium` (no mapstyle). The default **WebGL** backend loads deck.gl +
maplibre from a CDN (self-contained HTML, needs internet at view time for the base tiles). From a
checkout:

```bash
pip install -e .
python render_lanes.py ../duckOSM/data/db/sodermalm_pbf_gmns.duckdb lanes_debug.html --debug
```

Each render also drops a **`serve.py`** next to the HTML (auto-hops off a busy port; prints the URL and
a remote port-forwarding hint):

```bash
python serve.py            #  ->  http://localhost:8080/  (redirects to the map)
```

## Scale

The default **WebGL** backend (deck.gl) renders a whole city smoothly in a compact page — Tartu's
~23k lanes → ~16 MB, Södermalm's ~3k → ~2.4 MB. (The `folium` backend renders every lane as a Leaflet
vector feature, fine at neighbourhood scale but heavy for a whole city — Tartu is ~60 MB there.)

## Fidelity

Lane **polygons** are geometrically real (offset centerline buffered by width) but **width is the
3.25 m default** where OSM lacks `width:lanes`, so ribbons are uniform. Names/arrows come from the GMNS
`link` table (one-way = a link with no reverse pair). This is a lane-level *map*, not a survey-grade
HD map.
