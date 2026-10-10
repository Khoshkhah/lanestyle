<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/docs/img/logo.svg" alt="lanestyle" width="96">
</p>

<h1 align="center">lanestyle</h1>

<p align="center">
  <b>Lane-level road maps from Python.</b><br>
  Every road as wide as its lanes, its bus and bike lanes, lane lines, arrows, zebras and sidewalks, on roadstyle. One offline HTML file.
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

## Quick start

```bash
pip install lanestyle duckosm[levels]
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving -m walking -m cycling
duckosm gmns monaco.duckdb -o monaco_gmns.duckdb                # the lanes (GMNS, lanes and turns from SUMO)
duckosm levels monaco.duckdb                                    # the drawing order: monaco.levels, where your edits live
```

```python
import lanestyle as ls

ls.lane_page("monaco.levels", "monaco_gmns.duckdb", "monaco.duckdb").save("monaco.html")   # one file, opens offline
```

or `python lane_page.py monaco.levels monaco_gmns.duckdb monaco.duckdb monaco.html`.

## What you get

- **The roads, drawn by [roadstyle](https://github.com/Khoshkhah/roadstyle).** Each road is one line as wide as its lanes, with its
  outline, ends, bridges over and tunnels under, street names, hover and click: the drawing of roadstyle's level editor, so a road
  you fix in the editor (`roadstyle-levels edit monaco.levels --items lanestyle.editor:lane_items`) is the same on the page.
- **Lanes on them.** Bus and bike lanes in their colours, lane lines (dashed between car lanes, solid next to a bus or bike lane, a
  centre line between directions), turn arrows before a junction, BUS and bike marks, all in metres. Car lanes are invisible but
  clickable.
- **Plain junctions.** Lanes, lines and arrows stop where a junction begins, as painted on a real road.
- **Zebras and sidewalks.** Painted crossings as white stripes (from zoom 17); the sidewalks OSM tags on a street as strips beside it.
  A road cars do not use (a footway, a cycleway) is drawn in the colour of who uses it.

lanestyle draws nothing of its own: roadstyle draws every road, lanestyle only reads duckOSM's GMNS lanes and adds them to the roads
as items. Settings (colours, widths, dashes, marks): `src/lanestyle/data/lanestyle.json`, overridden by a `lanestyle.json` in the
current folder.

## For AI agents

- **Using lanestyle:** the agent skill [`skills/lanestyle/SKILL.md`](skills/lanestyle/SKILL.md) has the install, the lane table, the one call, the JavaScript API and the traps in one page. In Claude Code: `/plugin marketplace add Khoshkhah/lanestyle`, then `/plugin install lanestyle@lanestyle`.
- **The docs as text:** [`llms.txt`](https://khoshkhah.github.io/lanestyle/llms.txt) and [`llms-full.txt`](https://khoshkhah.github.io/lanestyle/llms-full.txt) (every page, one file).
- **Changing lanestyle:** [`AGENTS.md`](AGENTS.md) has the layout, the commands and the project's rules.

More: [AI agents](https://khoshkhah.github.io/lanestyle/guides/agents/).

## License

MIT
