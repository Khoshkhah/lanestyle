# Python API

<p class="lead">Six functions. The two you need are `from_gmns` and `render_lanes`.</p>

```python
import lanestyle as ls
```

## `render_lanes(lanes, turns=None, palette="mono", settings=None, **kwargs)`

Draw a [lane table](../guides/lane-table.md) as one roadstyle map and return roadstyle's `WebMap`
(`.save(path)`, `.html`).

| Parameter | Meaning |
|---|---|
| `lanes` | GeoDataFrame, one row per lane |
| `turns` | DataFrame `from_lane`, `to_lane`, optional `type`: clicks, type labels, `turns_in` / `turns_out` in the popup |
| `palette` | a roadstyle palette: `mono` (default, so the lane colours stand out), `carto`, `highsat` |
| `settings` | roadstyle settings, plus a `"lanes"` key for lanestyle's own ([Settings](settings.md)) |
| `**kwargs` | anything `roadstyle.render_edges` takes: `basemap`, `boundary`, `overlays`, `name`, `view_3d`, … |

It calls `roadstyle.render_edges` with `width_m_col="width_m"`, `width_m_zoom`, `casing_m` and the
popup columns, then appends its own scripts: the lane lines, the bus and bike rows in the Roads
box, round ends in tunnels, the click script and the type labels.

```python
import roadstyle as rs
ls.render_lanes(lanes, turns=turns,
                boundary=ls.read_boundary("monaco.duckdb"),       # the area's dashed outline
                overlays=[rs.Overlay(route_gdf, label="route")],  # a lane route on top
                basemap="dark_matter").save("lanes.html")
```

## `from_gmns(gmns_db, mode="driving", source_db=None)`

Read `gmns_<mode>.lane` / `.link` / `.movement` (and `.lane_connector` when present) from a duckOSM
GMNS database into `(lanes, turns)`.

- `highway` is the link's `facility_type`, `width_m` the lane's `width` (null where untagged;
  `render_lanes` fills the default), `use` from `allowed_uses`, `name` on lane 1 only.
- Levels (`bridge` / `tunnel` / `layer`) and `osm_id`: from the GMNS `link` if it has those
  columns (duckOSM writes them), else from `source_db`, the duckOSM database the GMNS file was made
  from (older GMNS files). `osm_id` is only available from `source_db`.
- `reverse_link_id`: the link with the same two nodes swapped **and** the same geometry, so the
  two halves of a one-way loop are not a pair.
- `turns`: each inbound lane in the movement's range into the outbound lane at the same place in
  its range (NULL = every lane), with the movement `type`.

## `read_boundary(db)`

The area's boundary from a duckOSM database (`main.boundary`, written when the area was built with
one) as a shapely geometry, or `None`. Pass it on: `render_lanes(..., boundary=geom)`.

## `boundary_from_geojson(path)`

A GeoJSON file's geometries as one shapely geometry (plain json + shapely, no GDAL).

## `lane_settings(settings=None)`

lanestyle's effective settings: the package defaults, then a `lanestyle.json` in the current
folder, then `settings["lanes"]`. Useful to see what a map will use.

## `write_serve(out_html)`

Drop a `serve.py` next to a saved map: `python serve.py [port]` serves that folder without caching
and prints the URL. Returns the script's path.

## Lower level

`lanestyle.lines.lane_lines(lanes, settings)` returns the lane lines as a GeoJSON FeatureCollection
(`t` type, `b` roadstyle band, `k` width factor), and `lanestyle.junctions.junction_fillets` the
optional corner fills. `render_lanes` calls both.
