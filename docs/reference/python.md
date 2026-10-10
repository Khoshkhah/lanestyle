# Python API

<p class="lead">One call makes the page; the rest is what it is built from.</p>

## `lane_page(area, gmns, source_db, connectors=False, **kw)`

The lanes of `gmns` on the roads of the level `area`, as roadstyle's level editor draws them: a
roadstyle `WebMap` (`.save(path)`, `.html`).

| argument | what |
|---|---|
| `area` | the level area folder (`duckosm levels DB` makes `DB.levels`) |
| `gmns` | duckOSM's GMNS file (`duckosm gmns DB -o GMNS`) |
| `source_db` | the duckOSM database both were made from (the OSM tags of the sidewalks) |
| `connectors` | also the lane connectors through junctions, unseen (route highlights) |
| `**kw` | to roadstyle's `render_edges`. By default the page is blank (`basemap="blank"`, no Roads box): `basemap=`, `filter_control=True`, `tunnel_control=True`, `name=` … |

## `lanestyle.editor.lane_items(roads, gmns=None, source_db=None, connectors=None)`

The editor's hook (`roadstyle-levels edit AREA --items lanestyle.editor:lane_items`; the files from
`LANESTYLE_GMNS` / `LANESTYLE_SOURCE_DB` there): it sets each road's width and line from its lanes and
returns `(overlays, render_edges keywords)` with the items. `lane_page` calls it.

## Reading GMNS

- `from_gmns(gmns_db, mode="driving", source_db=None, modes=None)` → `(lanes, turns)`: one row per lane
  (`lane_id`, `link_id`, `lane_num`, `use`, `width_m`, `turn`, the link's tags, `geometry` to the nodes,
  `cut_geometry` where SUMO's junction begins) and one per turn (`from_lane`, `to_lane`, `type`).
  `modes=("driving", "walking", "cycling")` reads several; cycling needs `source_db` (where bikes are pushed).
- `read_crossings(gmns_db)`: the crossings and the lanes they cross. `read_boundary(db)`,
  `boundary_from_geojson(path)`: an area's outline.
- `lane_settings()`: the settings in effect ([Settings](../guides/settings.md)).

Ids: `link_id` is duckOSM's BIGINT edge id; keep it `Int64`. On the page a lane's ids are text.
