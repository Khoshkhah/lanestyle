# From OSM to a lane-level map — the full pipeline

Every step to reproduce the lanestyle lane-level visualization, starting from raw OpenStreetMap and
ending at the interactive lane map drawn with roadstyle (exact lane widths, bridges and tunnels, lane
connectivity, street names, one-way arrows, base maps, and an optional lane route).

```
   .osm.pbf                          duckOSM                              lanestyle
 ┌──────────┐   build   ┌────────────────────────┐   render   ┌──────────────────────────┐
 │ raw OSM  │ ────────► │ routable network        │ ────────► │ roadstyle lane map       │
 │ extract  │           │  → GMNS lanes+movements │           │  lanes · names · arrows  │
 └──────────┘           └────────────────────────┘           │  click → connectivity    │
                                                              └──────────────────────────┘
   step 1                  steps 2–3 (duckOSM)                   steps 4–5 (lanestyle)
```

Two sibling repos do the work: **[duckOSM](https://github.com/Khoshkhah/duckOSM)** turns OSM into a routable network and a
GMNS db (with per-lane geometry); **lanestyle** (this repo) renders it with
roadstyle. It needs the GMNS db file, plus the duckOSM db it was made from for bridge / tunnel /
layer levels.

---

## Prerequisites

- **duckOSM** installed: `pip install duckosm` (0.1.0 or later; to work on duckOSM itself, check it out and `pip install -e .` in `../duckOSM`).
- **lanestyle** installed: `pip install lanestyle` (0.2.1 or later; or `pip install -e .` in this repo) — deps `roadstyle>=0.11`, `geopandas`, `duckdb`.
- Both together: `pip install lanestyle "duckosm[viz]"`.
- An OSM extract (`.osm.pbf`) for your area (e.g. from Geofabrik), or an existing duckOSM db.

Paths below assume a development workspace with `duckOSM/` and `lanestyle/` as siblings; with the packages from PyPI, use your own paths.

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

Read the GMNS db into a lane table and draw it with roadstyle. The GMNS `link` carries each road's
bridge / tunnel / layer. `--source-db` (the duckOSM db the GMNS file was made from, the *same* build)
is only for the area outline, or for GMNS files made before duckOSM wrote the levels.

```bash
cd ../lanestyle
python render_lanes.py ../duckOSM/data/db/tartu_gmns.duckdb tartu_lanes.html
```

Or from Python (a route from step 3 goes in as a roadstyle overlay):

```python
import geopandas as gpd, roadstyle as rs, lanestyle as ls
lanes, turns = ls.from_gmns("../duckOSM/data/db/tartu_gmns.duckdb")
route = gpd.read_file("route.geojson")
ls.render_lanes(lanes, turns=turns, overlays=[rs.Overlay(route, label="route")]).save("tartu_lanes.html")
```

## Step 5 — View it

`render_lanes.py` drops a `serve.py` next to the HTML (auto-picks a free port, redirects `/` to the
map); from Python, `ls.write_serve("tartu_lanes.html")` does the same:

```bash
python serve.py            #  ->  http://localhost:8080/   (open the printed URL)
```

Working **remotely**? Forward the printed port (VS Code Ports panel, or
`ssh -L PORT:localhost:PORT <host>`), or download the HTML and open it locally: it is
self-contained (only the base tiles come from the internet).

---

## What you see

| Element | What it is |
|---|---|
| **Lanes** | each lane one line, exactly its width in metres from zoom 16 on (the class width below), coloured by road class (`mono` palette) |
| **Lane use** | bus / bike lanes painted over the palette (a *Colour by* entry; the legend lists only uses present) |
| **Levels** | tunnels drawn under the street, bridges over it, in the order of the OSM `layer` tag (roadstyle) |
| **Click a lane** | it turns **red** with its popup (lane id, number, turn, use, width, link id); the lanes its GMNS movements lead into turn **green**, **U-turns** **purple** |
| **Base maps, filter box, names, arrows** | roadstyle's, unchanged |

## Fidelity — read this

- Lane **geometry** is real (duckOSM's drive-side offset centre line), but **width is a 3.25 m default**
  wherever OSM lacks `width:lanes`, so lanes look uniform.
- Lane **connectivity structure** is real (turns honour restrictions), but lane-to-lane **turn
  assignment** is permissive where `turn:lanes` is untagged (all inbound lanes → all outbound lanes).
- This is a lane-level **map**, not a survey-grade HD map — a base layer / prior to refine, not a
  finished cm-accurate map.

## Scale

Tartu's ~24k lanes make a 7.6 MB page, Södermalm's ~5k 2.3 MB, Monaco's ~3.5k 2.1 MB.
