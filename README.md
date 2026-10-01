<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/logo.svg" alt="lanestyle logo" width="96">
</p>

<h1 align="center">lanestyle</h1>

<p align="center">
  <b>Lane-level road maps from Python.</b><br>
  Every lane drawn at its real width, with painted lane lines, turns, and a click that shows where a lane leads. One offline HTML file.
</p>

<p align="center">
  <a href="https://pypi.org/project/lanestyle/"><img src="https://img.shields.io/pypi/v/lanestyle.svg" alt="PyPI"></a>
  <a href="https://github.com/Khoshkhah/lanestyle/actions/workflows/test.yml"><img src="https://github.com/Khoshkhah/lanestyle/actions/workflows/test.yml/badge.svg?branch=master" alt="Tests"></a>
  <a href="https://khoshkhah.github.io/lanestyle/"><img src="https://img.shields.io/badge/docs-khoshkhah.github.io%2Flanestyle-3f51b5.svg" alt="Docs"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg" alt="Python 3.10+">
  <a href="https://github.com/Khoshkhah/lanestyle/blob/master/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#gallery">Gallery</a> ·
  <a href="#what-goes-in">What goes in</a> ·
  <a href="https://khoshkhah.github.io/lanestyle/">Documentation</a>
</p>

![A lanestyle map of Monaco: Boulevard des Moulins with its bus lane in blue, dashed dividers, turn labels on every lane and a roundabout](https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/hero.jpg)

## Why lanestyle

- **Lanes, not roads.** Each lane is its own line, exactly its width in metres from zoom 16 on
  (3.25 m where OSM says nothing), so neighbours sit side by side with no gap and no overlap.
- **Painted lane lines.** Dashed dividers between lanes of one direction, a solid centre line
  between the two directions, grey edges: drawn to scale, cut at junctions, styled per type.
- **Turns you can see.** Click a lane: it turns red, the lanes it leads into green, U-turns purple.
  Every lane carries its turn label (`left + thru`, `right`, `fork`, `merge`, `end`).
- **Built on [roadstyle](https://github.com/Khoshkhah/roadstyle).** Bridges over, tunnels under
  (from the OSM `layer` tag), base maps, the filter box, popups, arrows and the `rs*` JavaScript API
  come with it. lanestyle is to lanes what [mapstyle](https://github.com/Khoshkhah/mapstyle) is to the
  full base map.
- **From OpenStreetMap.** [duckOSM](https://github.com/Khoshkhah/duckOSM) places the lanes and works
  out the lane-to-lane turns as a GMNS database; `from_gmns` reads it. Any other lane table draws too.
- **One offline file.** Map, data and styling in a single HTML page: open it, serve it, embed it.

## Install

```bash
pip install lanestyle
```

Python ≥ 3.10. Brings roadstyle ≥ 0.11 (line widths in metres), geopandas, shapely 2, duckdb and pandas.

## Quickstart

**No data needed.** Monaco's lanes ship with the repo as GeoParquet
([`docs/data/`](docs/data), 1 MB):

```python
import geopandas as gpd, pandas as pd
import lanestyle as ls

lanes = gpd.read_parquet("docs/data/monaco_lanes.parquet")
turns = pd.read_parquet("docs/data/monaco_turns.parquet")
ls.render_lanes(lanes, turns=turns).save("monaco.html")     # open it: no server needed
```

**Your own area**, with duckOSM (`pip install "duckosm @ git+https://github.com/Khoshkhah/duckOSM"`):

```bash
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving
duckosm gmns monaco.duckdb -m driving -o monaco_gmns.duckdb
```

```python
lanes, turns = ls.from_gmns("monaco_gmns.duckdb", source_db="monaco.duckdb")   # + levels, boundary
ls.render_lanes(lanes, turns=turns, boundary=ls.read_boundary("monaco.duckdb")).save("monaco.html")
```

Or from the shell: `python render_lanes.py monaco_gmns.duckdb monaco.html --source-db monaco.duckdb`.
The whole chain from a raw `.osm.pbf`: [From OSM to lanes](https://khoshkhah.github.io/lanestyle/pipeline/).

**More looks:** every roadstyle keyword passes through.

```python
ls.render_lanes(lanes, turns=turns, basemap="dark_matter")                              # dark
ls.render_lanes(lanes, turns=turns, settings={"lanes": {"colors": {"bus": "#d35400"}}})  # your colours
ls.render_lanes(lanes, settings={"lanes": {"lines": False, "type_label_zoom": None}})     # plain lanes
ls.render_lanes(lanes, turns=turns, overlays=[rs.Overlay(route_gdf, label="route")])     # a lane route on top
```

## Gallery

<table>
<tr>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/lane_lines.jpg" alt="Lane lines" width="100%"></a><br><b>Lane lines</b><br><sub>dividers, centre line, edges, to scale</sub></td>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/roundabout.jpg" alt="A roundabout" width="100%"></a><br><b>A roundabout</b><br><sub>one ring, one road</sub></td>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/tunnel.jpg" alt="A tunnel" width="100%"></a><br><b>A tunnel</b><br><sub>under the street, from the <code>layer</code> tag</sub></td>
</tr>
<tr>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/bus_lane.jpg" alt="Bus lanes" width="100%"></a><br><b>Bus lanes</b><br><sub>painted over the palette, a row in the Roads box</sub></td>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/click.jpg" alt="Click a lane" width="100%"></a><br><b>Click a lane</b><br><sub>red, into green, U-turns purple</sub></td>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/overview.jpg" alt="Zoomed out" width="100%"></a><br><b>Zoomed out</b><br><sub>roadstyle's class widths below zoom 16</sub></td>
</tr>
</table>

Every look with its code: **[the gallery](https://khoshkhah.github.io/lanestyle/gallery/)**.

## What goes in

`lanes` is a GeoDataFrame, one row per lane, each line in the direction of travel. Three columns
are required; the others switch features on:

| Column | Powers |
|---|---|
| `lane_id`, `geometry`, `highway` | the lane: unique id, centre line, road class (colour, filter box) |
| `width_m` | its width in metres (3.25 where null) |
| `use` | `auto`, `bus` or `bike`: bus and bike lanes are painted over the palette |
| `bridge` / `tunnel` / `layer` | grade separation, read as roadstyle reads them |
| `name` | the street label (set it on one lane per road) |
| `link_id`, `lane_num` (+ `reverse_link_id`, `from_node_id`, `to_node_id`) | the lane lines: which lanes share a road, which road is the other direction, where junctions are |
| `connector`, `from_lane`, `to_lane` | lane connectors: the curves through a junction, drawn like lanes |
| anything else | shown in the popup |

`turns` (optional) has `from_lane`, `to_lane` and a `type` (`thru`, `left`, `right`, `uturn`,
`diverge`, `merge`): the click colours, the lane type labels, and `turns_in` / `turns_out` in the
popup. Lane 1 is the leftmost lane (right-hand traffic). Details:
[The lane table](https://khoshkhah.github.io/lanestyle/guides/lane-table/).

## Settings

roadstyle's settings apply as they are; lanestyle adds a `lanes` key
([defaults](src/lanestyle/data/lanestyle.json)): the lane and click colours, the three lane line
types (`color`, `width_m`, `dash_m`), `junction_trim_m`, `type_label_zoom`, `default_width_m`,
`width_m_zoom`. Override them the roadstyle way, a `lanestyle.json` in the current folder or
`settings={"lanes": {...}}`, stating only what changes.

## Drive it from JavaScript

A lanestyle page is a roadstyle page, so the whole `window.rs*` API is there, with the lane table's
columns as properties:

```js
const bus = rsQuery(p => p.use === "bus");  rsColor(bus, "#ff8800");  rsFocus(bus);
rsSelect(rsQuery(p => p.lane_id === "8121729169906061189_2")[0]);     // click a lane by id
```

## Fidelity

Lane geometry is duckOSM's drive-side offset centre line, one continuous curve along a road.
Widths are the 3.25 m default wherever OSM lacks `width:lanes`, which today is nearly everywhere.
Lane-to-lane turns follow `turn:lanes` where tagged and osm2gmns's defaults elsewhere. A lane-level
*map*, not a survey-grade HD map.

## Documentation

**[khoshkhah.github.io/lanestyle](https://khoshkhah.github.io/lanestyle/)**: get started, guides
(the lane table, lane lines, turns and clicks, the duckOSM pipeline, websites), the gallery, the
Python API, settings, the command line, and the design notes.

## License

MIT.
