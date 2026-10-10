---
name: lanestyle
description: Draw lane-level road maps with the lanestyle Python library - every road as wide as its lanes, with bus and bike lanes, painted lane lines, turn arrows, BUS and bike marks, zebra crossings and sidewalks, on roadstyle - from duckOSM's GMNS lanes and level area, as one offline HTML page. Use when a map must show individual lanes or lane markings, or when visualising GMNS / duckOSM lane data.
---

# lanestyle

Draws duckOSM's GMNS lanes on roadstyle's roads as one self-contained HTML map (MapLibre, data inlined,
works offline, roadstyle's `window.rs*` JavaScript API). lanestyle draws nothing of its own: roadstyle
draws every road (one line as wide as its lanes, its outline, levels, tunnels, bridges, names, hover
and click) exactly as roadstyle's level editor does; lanestyle adds the lanes and markings as the
roads' own items. roadstyle's skill covers what the page inherits:
https://github.com/Khoshkhah/roadstyle/blob/main/skills/roadstyle/SKILL.md.

## Install and data

`pip install lanestyle "duckosm[levels]"` (brings roadstyle, geopandas, shapely 2, duckdb).

```bash
duckosm build --pbf area.osm.pbf -o area.duckdb -m driving -m walking -m cycling
duckosm gmns area.duckdb -o area_gmns.duckdb      # lanes, turns and junction cuts (SUMO)
duckosm levels area.duckdb                        # area.levels: the drawing order; fix places with roadstyle-levels edit
```

## The one call

```python
import lanestyle as ls

m = ls.lane_page("area.levels", "area_gmns.duckdb", "area.duckdb")
m.save("lanes.html")
```

The page is blank by default (no base map, no Roads box, no Tunnels slider); extra keywords go to `roadstyle.render_edges` (`basemap=`, `filter_control=True`, `tunnel_control=True`, `name=` …).
`connectors=True` adds the lane connectors through the junctions, unseen (route highlights).
The same drawing in roadstyle's editor: `LANESTYLE_GMNS=area_gmns.duckdb LANESTYLE_SOURCE_DB=area.duckdb
roadstyle-levels edit area.levels --items lanestyle.editor:lane_items`.

## What is drawn

- Car lanes: unseen but clickable (`items_popup`: road, name, lane, use, width); bus and bike lanes in
  their colours. Lane lines: dashed between car lanes, solid next to a bus or bike lane, a centre line
  between directions. Turn arrows before a junction, BUS and bike marks; all in metres.
- Plain junctions: lanes, lines and arrows stop where SUMO's junction begins.
- Painted crossings (duckOSM `crossing.painted`) as white stripes from zoom 17; sidewalks OSM tags on a
  street (`sidewalk=right/left/both`, `sidewalk:width`) as strips beside it from zoom 17. Nothing guessed.
- A road cars do not use in the colour of who uses it (walking, cycling); pushing a bike is walking.

## Settings

`src/lanestyle/data/lanestyle.json`, overridden by a `lanestyle.json` in the current folder: colours
(`colors.auto/bus/bike/walk`, `colors.groups`), widths (`default_width_m`, `width_m_by_use`,
`casing_m`, `centre_line_m`), `lines`, `arrows`, `zebra`, `sidewalk`.

## Traps

- `link_id` / `edge_id` are duckOSM BIGINT hashes: keep them `Int64`, never float64.
- A road's look (outline, ends, levels, tunnels) is roadstyle's and the level area's: fix it in the
  editor or in roadstyle, not in lanestyle. Lane data problems are fixed in duckOSM.
- A Google Maps key passed to the page is written into it: never commit such a page.
