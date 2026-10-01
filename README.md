<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/logo.svg" alt="lanestyle" width="96">
</p>

<h1 align="center">lanestyle</h1>

<p align="center">
  <b>Lane-level road maps from Python.</b><br>
  Every lane at its real width, painted lane lines, and a click that shows where a lane leads. One offline HTML file.
</p>

<p align="center">
  <a href="https://pypi.org/project/lanestyle/"><img src="https://img.shields.io/pypi/v/lanestyle.svg" alt="PyPI"></a>
  <a href="https://github.com/Khoshkhah/lanestyle/actions/workflows/test.yml"><img src="https://github.com/Khoshkhah/lanestyle/actions/workflows/test.yml/badge.svg?branch=master" alt="Tests"></a>
  <a href="https://khoshkhah.github.io/lanestyle/"><img src="https://img.shields.io/badge/docs-khoshkhah.github.io%2Flanestyle-3f51b5.svg" alt="Docs"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg" alt="Python 3.10+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT"></a>
</p>

<p align="center">
  <a href="https://khoshkhah.github.io/lanestyle/"><b>Documentation</b></a> ·
  <a href="https://khoshkhah.github.io/lanestyle/maps/monaco.html">Live map</a> ·
  <a href="https://khoshkhah.github.io/lanestyle/get-started/">Get started</a> ·
  <a href="https://khoshkhah.github.io/lanestyle/gallery/">Gallery</a> ·
  <a href="https://khoshkhah.github.io/lanestyle/reference/python/">Python API</a>
</p>

---

<p align="center">
  <a href="https://khoshkhah.github.io/lanestyle/maps/monaco.html"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/hero.jpg" alt="Monaco drawn by lanestyle: a bus lane in blue, dashed dividers, a turn label on every lane, a roundabout" width="900"></a>
</p>

## Quick start

```bash
pip install lanestyle
```

```python
import geopandas as gpd, pandas as pd
import lanestyle as ls

lanes = gpd.read_parquet("docs/data/monaco_lanes.parquet")   # Monaco ships with the repo
turns = pd.read_parquet("docs/data/monaco_turns.parquet")
ls.render_lanes(lanes, turns=turns).save("monaco.html")      # one file, opens offline
```

Your own area, from OpenStreetMap with [duckOSM](https://github.com/Khoshkhah/duckOSM):

```bash
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving
duckosm gmns monaco.duckdb -m driving -o monaco_gmns.duckdb
```

```python
lanes, turns = ls.from_gmns("monaco_gmns.duckdb", source_db="monaco.duckdb")
ls.render_lanes(lanes, turns=turns).save("monaco.html")
```

## What you get

- **Lanes, not roads.** Each lane is its own line, exactly its width in metres from zoom 16 on, so neighbours sit side by side with no gap and no overlap.
- **Painted lane lines.** Dashed dividers, a solid centre line, grey edges: drawn to scale and cut at junctions.
- **Turns you can see.** Click a lane: it turns red, the lanes it leads into green, U-turns purple. Every lane carries its turn label.
- **Everything roadstyle has.** Bridges over, tunnels under, base maps, the filter box, popups, arrows and the `rs*` JavaScript API, from [roadstyle](https://github.com/Khoshkhah/roadstyle). lanestyle is to lanes what [mapstyle](https://github.com/Khoshkhah/mapstyle) is to the full base map.

## Gallery

<table>
<tr>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/#lane-lines"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/lane_lines.jpg" alt="Lane lines" width="100%"></a><br><b>Lane lines</b></td>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/#a-roundabout"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/roundabout.jpg" alt="A roundabout" width="100%"></a><br><b>A roundabout</b></td>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/#a-tunnel"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/tunnel.jpg" alt="A tunnel" width="100%"></a><br><b>A tunnel</b></td>
</tr>
<tr>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/#bus-lanes"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/bus_lane.jpg" alt="Bus lanes" width="100%"></a><br><b>Bus lanes</b></td>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/#click-a-lane"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/click.jpg" alt="Click a lane" width="100%"></a><br><b>Click a lane</b></td>
<td width="33%" valign="top"><a href="https://khoshkhah.github.io/lanestyle/gallery/#the-defaults"><img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/gallery/overview.jpg" alt="Zoomed out" width="100%"></a><br><b>Zoomed out</b></td>
</tr>
</table>

## What goes in

A GeoDataFrame with one row per lane. `lane_id`, `geometry` and `highway` are required; the rest
switches features on: `width_m`, `use` (`bus`, `bike`), `bridge` / `tunnel` / `layer`, `name`,
`link_id` + `lane_num` for the lane lines. An optional `turns` table (`from_lane`, `to_lane`,
`type`) gives the clicks and labels. `from_gmns` builds both from a duckOSM GMNS database.

Column by column: [The lane table](https://khoshkhah.github.io/lanestyle/guides/lane-table/) ·
settings: [Settings](https://khoshkhah.github.io/lanestyle/reference/settings/) ·
the whole chain from a `.osm.pbf`: [From OSM to lanes](https://khoshkhah.github.io/lanestyle/pipeline/).

## License

MIT
