# The lane table

<p class="lead">`render_lanes` draws a GeoDataFrame with one row per lane. Three columns are required; the others switch features on.</p>

Each lane is a line in lon/lat (EPSG:4326, or any CRS roadstyle can reproject), running **in the
direction of travel**:

| Column | Needed? | Meaning |
|---|---|---|
| `lane_id` | yes | unique id (a string; duckOSM's are `<link_id>_<lane_num>`) |
| `geometry` | yes | the lane's centre line |
| `highway` | yes | road class, as in roadstyle: colour, filter box, width below zoom 16 |
| `width_m` | no, 3.25 | lane width in metres (`default_width_m` where null) |
| `use` | no, `auto` | `auto`, `bus` or `bike`; bus and bike lanes are painted over the palette |
| `bridge`, `tunnel`, `layer` | no | the lane's level, read exactly as roadstyle reads them |
| `name` | no | street-name label; set it on one lane per road, or every lane gets a label |
| `link_id`, `lane_num` | no | the road and the lane's number in it: needed for the [lane lines](lane-lines.md) and shown in the popup |
| `reverse_link_id`, `from_node_id`, `to_node_id` | no | the same road the other way, and the road's end nodes: centre lines and junction cuts |
| `lanes`, `turn`, `osm_id` | no | shown in the popup |
| `connector`, `from_lane`, `to_lane` | no | a row with `connector` True is a lane connector: drawn like a lane, without arrows, lines or labels |

Lane numbering is right-hand traffic: **lane 1 is the leftmost lane**, next to the centre line, and
numbers grow to the right (duckOSM's convention).

## From a GMNS database

`from_gmns` builds the table from a duckOSM GMNS file, levels and `osm_id` from the duckOSM database
it was made from:

```python
lanes, turns = ls.from_gmns("monaco_gmns.duckdb", mode="driving")
```

It reads `gmns_<mode>.lane`, `.link`, `.movement` and, when present, `.lane_connector`. Levels come
from the GMNS `link` if it has `bridge` / `tunnel` / `layer` columns, else (GMNS files made
before duckOSM wrote them) from `source_db`, the duckOSM database (`link_id` = `<mode>.edges.edge_id`), else every lane is at ground level.

!!! warning "Keep the ids exact"
    duckOSM's `link_id` is a 64-bit content hash. Keep it an integer column (`Int64`), never float:
    a float loses the low digits and the lane lines can no longer pair a road with its reverse.

## From your own data

Any source works, as long as each lane has its own centre line. A lane table built by hand:

```python
import geopandas as gpd
from shapely.geometry import LineString

lanes = gpd.GeoDataFrame({
    "lane_id": ["a_1", "a_2"],
    "highway": ["secondary", "secondary"],
    "link_id": [1, 1], "lane_num": [1, 2],
    "use": ["auto", "bus"],
    "geometry": [LineString([(7.4200, 43.7350), (7.4210, 43.7355)]),
                 LineString([(7.4200, 43.7349), (7.4210, 43.7354)])],
}, crs=4326)
ls.render_lanes(lanes).save("two_lanes.html")
```

Without `link_id` / `lane_num` the map still draws, just without lane lines.

## Lane widths

Every lane is exactly `width_m` metres wide from `width_m_zoom` (16) on, with roadstyle's class
widths below, so a zoomed-out map still reads as a road map. OSM rarely tags `width:lanes`, so in
practice every lane is the 3.25 m default: a lane-level *map*, not a survey-grade HD map.
