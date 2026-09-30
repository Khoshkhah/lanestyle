# lanestyle

Lane-level maps on [roadstyle](https://github.com/Khoshkhah/roadstyle): every lane is one roadstyle
line on its own geometry, drawn **exactly its width in metres** from zoom 16 on. roadstyle brings
the rest: draw order from the OSM `layer` tag, bridges, tunnels, base maps, the filter box, popups,
arrows and its `rs*` JavaScript API. lanestyle is to lanes what mapstyle is to the full base map.

Click a lane: it turns **red**, the lanes it leads into **green**, U-turns **purple**. Bus and bike
lanes are painted over the palette (the *Lane use* colouring).

**New here?** [`docs/pipeline.md`](docs/pipeline.md) walks the full pipeline, from a raw `.osm.pbf`
through duckOSM to this map.

```python
import lanestyle as ls

# the reader: a duckOSM GMNS db (+ the duckOSM db it came from, for bridges / tunnels / layers)
lanes, turns = ls.from_gmns("data/monaco_gmns.duckdb", source_db="data/monaco.duckdb")
# the engine: any lane table works, not only GMNS
ls.render_lanes(lanes, turns=turns, palette="mono").save("lanes.html")
```

## Input: a lane table, the roadstyle way

`lanes` is a GeoDataFrame, one row per lane, each line in the direction of travel:

| Column | Needed? | Meaning |
|---|---|---|
| `lane_id`, `geometry`, `highway` | yes | unique id, the lane's centre line, road class |
| `width_m` | no, 3.25 | lane width in metres |
| `use` | no, `auto` | `auto`, `bus` or `bike` |
| `bridge`, `tunnel`, `layer` | no | the lane's level, read as roadstyle reads them |
| `name` | no | street-name label (`from_gmns` sets it on lane 1 only) |
| `link_id`, `lane_num`, `turn` | no | shown in the popup |

`turns` (optional) has `from_lane`, `to_lane` and an optional `type` (`uturn` is purple). Other
`render_lanes` keywords go to `roadstyle.render_edges`, for example a route as an overlay:
`overlays=[rs.Overlay(route_gdf)]`.

## Settings

roadstyle's own settings apply (`roadstyle.json`, or `settings=`). lanestyle's defaults are in
[`src/lanestyle/data/lanestyle.json`](src/lanestyle/data/lanestyle.json): lane colours, click
colours, `default_width_m`, `casing_m`, `width_m_zoom`. Override them the roadstyle way, stating
only what changes: a `lanestyle.json` in the current folder, or a `"lanes"` key in `settings=`:

```python
ls.render_lanes(lanes, turns=turns, settings={"lanes": {"colors": {"bus": "#d35400"}}})
```

## Install / run

Needs roadstyle 0.10 (metre widths; until it is released, the `metre-width` branch of roadstyle),
plus geopandas and duckdb.

```bash
pip install -e .
python render_lanes.py data/monaco_gmns.duckdb lanes.html --source-db data/monaco.duckdb
python serve.py 8080           # written next to the map; prints the URL
```

## Fidelity

Lanes are duckOSM's drive-side offset centre lines. Their **width is 3.25 m** wherever OSM lacks
`width:lanes`, which today is every lane. Lane-to-lane turns come from GMNS `movement`: where
`turn:lanes` is untagged, every lane of a road leads into every lane of the next. A lane-level
*map*, not a survey-grade HD map.
