# lanestyle

**Lane-level** base map + lane-route visualization. The workspace lineage is
[`roadstyle`](../roadstyle) (styles road *lines*) → [`mapstyle`](../mapstyle) (a whole base map) →
**`lanestyle`** (the *lanes* themselves).

lanestyle reads a [duckOSM](../duckOSM) **GMNS** db's per-lane geometry (`gmns_<mode>.lane` — the
drive-side offset centerline + width), buffers each lane into a **surface polygon**, colours it by use
(auto / bus / bike), and hands the layers to `mapstyle.render_basemap` — so the lane map is a natural
lane-resolution companion to mapstyle's road map. An optional **lane route** (from duckOSM's
`route-lanes`) is drawn on top.

It reuses mapstyle as-is; the only mapstyle change is a **backward-compatible** one (its polygon styler
now honours a solid `Layer.color` override — unset on every existing layer, so those render identically).

```python
from lanestyle import render_lane_map

DB = "../duckOSM/data/db/sodermalm_pbf_gmns.duckdb"   # a duckOSM GMNS db (duckosm gmns)
render_lane_map(DB, "lanes.html")                     # lanes coloured by use, on a CARTO base

# overlay a lane-level route (produced by duckOSM):
#   duckosm route-lanes DB <fromLane> <toLane> -o route.geojson
render_lane_map(DB, "lanes.html", route_geojson="route.geojson")
```

## How it fits the stack

```
duckOSM  gmns_<mode>.lane  (offset lane centerlines + width)   duckOSM  route-lanes -> route.geojson
                    │                                                        │
                    ▼                                                        ▼
         lanestyle.lane_layers  ──► mapstyle.render_basemap ◄──  lanestyle.route_layer
                                          │
                                          ▼
                                   lane-level map (HTML)
```

## Install / run

Deps: `mapstyle`, `geopandas`, `duckdb`. From a checkout:

```bash
pip install -e .          # (mapstyle installed from ../mapstyle)
python render_lanes.py ../duckOSM/data/db/sodermalm_pbf_gmns.duckdb lanes.html
python render_lanes.py ../duckOSM/data/db/sodermalm_pbf_gmns.duckdb lanes_debug.html --debug
```

Each render also drops a **`serve.py`** next to the HTML (mirrors mapstyle's local-server output) —
handy to avoid `file://` quirks:

```bash
python serve.py 8080      #  ->  http://localhost:8080/lanes.html
```

## Fidelity

Lane **polygons** are geometrically real (offset centerline buffered by width) but **width is the 3.25 m
default** where OSM lacks `width:lanes`, so ribbons are uniform. The route overlay is exactly what
duckOSM's `route-lanes` returns (its permissive-turn caveat carries over). This is a lane-level *map*,
not a survey-grade HD map.

## Backends

`render_lane_map(..., backend="folium")` (default) is reliable at city scale; `backend="lonboard"`
(WebGL) scales further but currently has a polygon-fill display quirk to revisit.
