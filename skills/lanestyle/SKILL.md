---
name: lanestyle
description: Draw lane-level road maps with the lanestyle Python library - every lane as its own line at its real width in metres, with painted lane lines, bus and bike lanes, turn labels and a click that shows which lanes a lane leads into - from a lane GeoDataFrame or a duckOSM GMNS database, as one offline HTML page built on roadstyle. Use when a map must show individual lanes, lane-to-lane turns or connectivity, or when visualising GMNS / duckOSM lane data.
---

# lanestyle

Turns a table of lanes into one self-contained HTML map (roadstyle underneath: MapLibre, data
inlined, works offline, `window.rs*` JavaScript API). Each lane is one line, exactly `width_m`
metres wide from zoom 16 on. Docs: https://khoshkhah.github.io/lanestyle/ (Python API:
`/reference/python/`, settings: `/reference/settings/`, the lane table: `/guides/lane-table/`).
roadstyle's own skill covers everything a lanestyle page inherits (base maps, overlays, JS API):
https://github.com/Khoshkhah/roadstyle/blob/main/skills/roadstyle/SKILL.md.

## Install

`pip install lanestyle` (brings roadstyle ≥ 0.11, geopandas, shapely 2, duckdb, pandas).
Check: `python -c "import lanestyle, roadstyle; print(roadstyle.__version__)"`.

## Where lanes come from

- **A duckOSM GMNS database** (the normal path). From a `.osm.pbf`:
  `duckosm build --pbf area.osm.pbf -o area.duckdb -m driving`, then
  `duckosm gmns area.duckdb -m driving -o area_gmns.duckdb`. Then
  `lanes, turns = ls.from_gmns("area_gmns.duckdb")`: one file; the links carry bridge / tunnel / `layer`. Optional
  `source_db="area.duckdb"` (the duckOSM database it was made from, same build: `link_id` = its
  `edge_id`) adds `osm_id` and the levels of older GMNS files; `ls.read_boundary(source_db)` is the
  area outline.
- **Cars and pedestrians in one map**: `duckosm gmns area.duckdb -m driving -m walking -o area_gmns.duckdb`, then
  `ls.from_gmns("area_gmns.duckdb", modes=("driving", "walking"), source_db="area.duckdb")` (later modes add only the links the earlier ones lack).
  The table then has `modes` (colour by who may use a link), `footway` (`sidewalk` / `crossing` / `link`), `along_link_id`, `along_kind`, `along_links` (the roads a
  footpath runs along) and `lanes.attrs["crossings"]` (the zebras); `render_lanes` draws sidewalks, the gap between a footpath and its road, and zebra stripes from them.
- **The bundled sample**, no duckOSM needed: `docs/data/monaco_lanes.parquet` and
  `monaco_turns.parquet` in the repo (`gpd.read_parquet` / `pd.read_parquet`).
- **Any lane table you build.** `lanes` is a GeoDataFrame, one row per lane, each LineString in
  the direction of travel (EPSG:4326). Required: `lane_id` (string), `geometry`, `highway` (OSM
  class). Optional, each switching a feature on: `width_m` (where null: 2 m for `walk`, 1.5 m for a `bike` lane beyond the link's motor lanes, else 3.25), `use` (`auto` |
  `bus` | `bike` | `walk`), `bridge` / `tunnel` / `layer`, `name` (set it on one lane per road, or every
  lane gets a label), `link_id` + `lane_num` (the lane lines: which lanes share a road; lane 1 is
  the LEFTMOST lane, right-hand traffic), `reverse_link_id` + `from_node_id` + `to_node_id` (centre
  lines, junction cuts), `connector` + `from_lane` + `to_lane` (connector curves through
  junctions, drawn without arrows or lines). Anything else shows in the popup.
- **`turns`** (optional DataFrame): `from_lane`, `to_lane` (both `lane_id`s), `type` (`thru`,
  `left`, `right`, `uturn`, `diverge`, `merge`). Without it a click only selects: no red / green
  colouring, no turn labels, no `turns_in` / `turns_out`.

## The one call

```python
import lanestyle as ls

lanes, turns = ls.from_gmns("monaco_gmns.duckdb")
m = ls.render_lanes(
    lanes, turns=turns,
    palette="mono",                                    # default: neutral roads, lane colours stand out
    boundary=ls.read_boundary("monaco.duckdb"),        # dashed outline; or ls.boundary_from_geojson(path)
    basemap="voyager",                                 # any roadstyle base map; CARTO ones need CARTO_API_KEY
    settings={"lanes": {"colors": {"bus": "#d35400"}}},   # lanestyle's own settings under "lanes"
)
m.save("monaco.html")                                  # roadstyle WebMap: .save(path), .html
ls.write_serve("monaco.html")                          # optional: serve.py next to it (no caching)
```

Every other keyword goes straight to `roadstyle.render_edges`: `overlays=[rs.Overlay(route_gdf)]`
for a route on top, `name=`, `view_3d=`, `include=` / `exclude=` road classes, `tiles=True`
(roadstyle silently ignores an unknown keyword, so check spelling).

What the page shows: lanes at true width from zoom 16 (class widths below); dashed dividers
between lanes of one direction, a solid centre line between directions, grey edges, cut at
junctions; bus and bike lanes painted over the palette with rows in the Roads box; the street name
once per road; a turn label per lane from zoom 18 (`left + thru`, `right`, `U-turn`, `fork`,
`merge`, `end`); click a lane: red, the lanes it leads into green, U-turns purple, popup with
`lane_type`, `turns_in` / `turns_out`, width, level and ids.

### Settings (not keywords)

`settings={"lanes": {...}}`, or a `lanestyle.json` in the current folder; state only what changes.
Defaults in `src/lanestyle/data/lanestyle.json`:

| key | default | meaning |
|---|---|---|
| `colors.bus`, `colors.bike`, `colors.clicked`, `colors.turns_into`, `colors.uturn` | blue, blue, red, green, purple | lane and click colours |
| `lines.divider` / `lines.centre` / `lines.edge` | `{color, width_m, dash_m}` | `dash_m: null` = solid; `"lines": false` = none |
| `junction_trim_m` | 1 | lines stop this far short of the other roads' surface |
| `type_label_zoom` | `null` | a zoom number draws each lane's turns (`left + thru`) along it from that zoom; off by default: the turns are in the popup (`lane_type`) |
| `default_width_m`, `width_m_by_use`, `width_m_zoom`, `casing_m` | 3.25, `{walk: 2.0, bike: 1.5}`, 16, 0 | lane width where null (`width_m_by_use`: footpath, on-road bike lane); true widths from this zoom; casing inside each lane |
| `fillet_m` | 0 (off) | pave gaps narrower than 2× this between lane surfaces |
| `frame_gap_m`, `frame_reach_m`, `frame_casing` | 2, 8, false | a footpath matched to a road is one frame with it: the gap (up to `frame_reach_m`) is filled in a tint of its colour and no outline is drawn between them; `frame_gap_m` 0 turns frames off |
| `connectors_clickable` | false | connectors can be clicked / hovered like lanes (off: the click goes to the lane under one) |
| `tunnel_body` | `#f6f4ee` | opaque land-coloured base under the faded fill of tunnel lanes (hides lane-end rings); `""` = off |
| `crossing_max_m`, `crossing_min_on` | 10, 0.2 | a `footway=crossing` link longer than this and under this share on a road, or matched along a road, is drawn as a footway |
| `colors.sidewalk`, `colors.crossing` | terracotta, cream | a mapped sidewalk and a crosswalk |

roadstyle's own settings go in the same dict (`settings={"config": {...}}`).

## Check the result

Look before reporting done. `pip install playwright && playwright install chromium`, then
`import roadstyle as rs; rs.snapshot(m, "lanes.png", zoom=19)` and view the PNG (zoom ≥ 17 to
see lanes at width, ≥ 18 for the labels). Or open the page with Playwright and call the JS below.

## JavaScript API (in the saved page)

All of roadstyle's `rs*` calls work; lane columns are the feature properties.

```js
const ids = rsQuery(p => p.use === "bus");                      // roadstyle feature ids
rsColor(ids, "#ff8800"); rsFocus(ids);
rsSelect(rsQuery(p => p.lane_id === "8121729169906061189_2")[0]);   // a click: red + green + popup
document.addEventListener("rs:select", e => console.log(e.detail.properties.lane_type));
```

lanestyle adds its own layers to `window.map`: `lane-lines-<level>-<type>` (one per level and
line type, source `lane-lines`), `lane-type-labels`, and `lane-fillets-<level>` when fillets are
on. List them with `map.getStyle().layers.map(l => l.id)`.

## Traps

- **Feature ids are not lane ids.** `rsSelect` / `rsColor` / `rsFocus` take roadstyle's feature
  ids (indexes into its source): get them with `rsQuery(p => p.lane_id === "...")`.
- **`link_id` is a 64-bit hash.** Keep `link_id`, `reverse_link_id`, node ids as `Int64`, never
  float64 (a float rounds them and the lane lines can no longer pair a road with its reverse).
  Compare them as strings in JavaScript.
- **Lane 1 is the leftmost lane** (right-hand traffic). Left-hand areas are not handled yet.
- **`source_db`, if used, must be the same duckOSM build** the GMNS file came from, or no lane gets a level. A GMNS file made before duckOSM 2bfef81 has no levels in `link`, so it needs it.
- **Widths are mostly the 3.25 m default**: OSM rarely tags `width:lanes`. Lane-to-lane turns
  follow `turn:lanes` where tagged and osm2gmns's defaults elsewhere. A lane-level map, not an
  HD map.
- **No `turns`, no colours**: without the turns table the click only selects, and no turn labels.
- **CARTO base maps are watermarked without a key** (`voyager`, `positron`, `dark_matter`): set
  `CARTO_API_KEY`, or `basemap="esri_street"` / `"osm"` / `"blank"`.
- **Styling is settings, not keywords**: a colour passed as a keyword is ignored.
- **A tunnel is a look, not a different rule**: levels (`layer`) separate lanes (layer -1 over -2, never connected to each other); do not add tunnel-only geometry rules.
- **Fix data in duckOSM, not in the table**: a lane with no way out, a wrong lane count or a missing footpath match is a duckOSM problem; lanestyle only draws.
- **Street View**: `render_lanes(lanes, turns, street_view=True)` (roadstyle's page) or `street_view_key=KEY` (the map's toggle). A key is written into the page: never commit it.
- **Lanes have no casing** on purpose; neighbours merge into one surface and the lane lines
  separate them. Don't add `casing_m` to get dividers; style `lines` instead.
