# From OSM to a lane-level map — the full pipeline

Every step to reproduce the lanestyle lane-level visualization, starting from raw OpenStreetMap and
ending at the interactive WebGL map (with lane connectivity, street names, one-way arrows, a base-layer
selector, and an optional lane route).

```
   .osm.pbf                          duckOSM                              lanestyle
 ┌──────────┐   build   ┌────────────────────────┐   render   ┌──────────────────────────┐
 │ raw OSM  │ ────────► │ routable network        │ ────────► │ WebGL lane map           │
 │ extract  │           │  → GMNS lanes+movements │           │  lanes · names · arrows  │
 └──────────┘           └────────────────────────┘           │  click → connectivity    │
                                                              └──────────────────────────┘
   step 1                  steps 2–3 (duckOSM)                   steps 4–5 (lanestyle)
```

Two sibling repos do the work: **[duckOSM](../../duckOSM)** turns OSM into a routable network and a
GMNS db (with per-lane geometry); **lanestyle** (this repo) renders it. lanestyle is standalone — it
only needs the GMNS db file.

---

## Prerequisites

- **duckOSM** checked out and installed (its own env): `pip install -e .` in `../duckOSM`.
- **lanestyle** installed (this repo): `pip install -e .` — deps `geopandas`, `duckdb`, `folium`.
- An OSM extract (`.osm.pbf`) for your area (e.g. from Geofabrik), or an existing duckOSM db.

Paths below assume the standard workspace layout (`duckOSM/` and `lanestyle/` as siblings).

---

## Step 1 — Build the routable network (duckOSM)

Parse the PBF into a DuckDB routing network (nodes + directed edges; `edge_id` is a stable content
hash). duckOSM builds an area deliberately (island / city / county) — see its docs for the config.

```bash
cd ../duckOSM
duckosm build --pbf tartu.osm.pbf --output data/db/tartu.duckdb
# (or a per-area config build; the result has driving / walking / cycling schemas + raw OSM)
```

Produces `tartu.duckdb` with a `driving` schema (`edges`, `nodes`, `edge_graph`, …). This is the road
network; lanes don't exist yet.

## Step 2 — Export GMNS: per-lane geometry + movements (duckOSM)

Turn the routing network into a **GMNS** db. This is the key step for lanestyle: it produces
`gmns_<mode>.lane` (each lane as a **drive-side offset centerline + width**, coloured later by use) and
`gmns_<mode>.movement` (the legal turns — which drives lane connectivity).

```bash
duckosm gmns data/db/tartu.duckdb -o data/db/tartu_gmns.duckdb
# GMNS[driving]: … lanes, … movements  -> gmns_driving
```

`tartu_gmns.duckdb` now has `gmns_driving.lane`, `.link`, `.movement`, `.node`. **This is the only file
lanestyle needs.** (`link_id` == the routing `edge_id`, so everything stays keyed consistently.)

## Step 3 — (optional) a lane-level route (duckOSM)

If you want a routed lane path drawn on the map, plan one with duckOSM's lane router (which builds a
lane→lane graph from `movement` + `lane`) and write it as GeoJSON:

```bash
duckosm route-lanes data/db/tartu_gmns.duckdb <fromLane> <toLane> -o route.geojson
# lane ids look like "<edge_id>_<lane_num>"; an edge_id alone resolves to its lane 1
```

Skip this step if you just want the lane map without a route.

## Step 4 — Render the lane-level map (lanestyle)

Render the GMNS db to an interactive **WebGL** map (deck.gl + maplibre). Use `--debug` for the full
inspectable viewer (click-to-inspect, connectivity highlight, names, arrows, base selector).

```bash
cd ../lanestyle
python render_lanes.py ../duckOSM/data/db/tartu_gmns.duckdb tartu_lanes.html --debug
# with a route:
python render_lanes.py ../duckOSM/data/db/tartu_gmns.duckdb tartu_lanes.html route.geojson --debug
```

Or from Python:

```python
from lanestyle import render_lane_debug
render_lane_debug("../duckOSM/data/db/tartu_gmns.duckdb", "tartu_lanes.html",
                  route_geojson="route.geojson")     # WebGL by default; backend="folium" also works
```

## Step 5 — View it

Each render drops a `serve.py` next to the HTML (auto-picks a free port, redirects `/` to the map):

```bash
python serve.py            #  ->  http://localhost:8080/   (open the printed URL)
```

Working **remotely**? Either forward the exact printed port (VS Code Ports panel, or
`ssh -L PORT:localhost:PORT <host>`), or just **download the HTML** and open it locally — it's
self-contained (only the base tiles come from the internet).

---

## What you see (the debug viewer)

| Element | What it is |
|---|---|
| **Lane surfaces** (grey / orange / blue) | each lane = a polygon of its width, coloured by use (auto / bus / bike) |
| **Base-layer selector** | osm-carto / Carto light / Carto dark / satellite |
| **Toggles** | per-use lanes · street names · one-way arrows · route |
| **Hover a lane** | its `use` / lane # / `edge_id` / width |
| **Click a lane** | it turns **red**; **all its outgoing lanes turn cyan** (legal turns + lane-changes; **U-turns excluded**); panel shows the outgoing count |
| **Street names / one-way arrows** | from the GMNS `link` table (one-way = a link with no reverse pair) |
| **Route** (yellow) | the `route-lanes` path from step 3 |

## Fidelity — read this

- Lane **geometry** is real (offset centerline buffered by width), but **width is a 3.25 m default**
  wherever OSM lacks `width:lanes`, so lanes look uniform.
- Lane **connectivity structure** is real (turns honour restrictions), but lane-to-lane **turn
  assignment** is permissive where `turn:lanes` is untagged (all inbound lanes → all outbound lanes).
- This is a lane-level **map**, not a survey-grade HD map — a base layer / prior to refine, not a
  finished cm-accurate map.

## Scale

The default WebGL backend renders a whole city in a compact page — **Tartu ~23k lanes → ~18 MB**,
Södermalm ~3k → ~2.4 MB. The `folium` backend is crisp at neighbourhood scale but heavy for a whole
city (Tartu ~60 MB there).
