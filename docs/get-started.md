# Get started

<p class="lead">From an OpenStreetMap extract to a lane-level page: three duckOSM commands and one call.</p>

## Install

Python 3.10 or newer. lanestyle brings roadstyle (0.21 or newer), geopandas, shapely 2, duckdb and pandas;
duckOSM makes the data (it needs [SUMO](https://eclipse.dev/sumo/)'s `netconvert` for the lanes).

```bash
pip install lanestyle "duckosm[levels]"
```

## Make the data

```bash
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving -m walking -m cycling
duckosm gmns monaco.duckdb -o monaco_gmns.duckdb
duckosm levels monaco.duckdb
```

| step | makes | what is in it |
|---|---|---|
| `build` | `monaco.duckdb` | the roads of every mode, routable, with the OSM tags |
| `gmns` | `monaco_gmns.duckdb` | the lanes (count, width, use: car, bus, bike), the turns between them and where each junction begins (from SUMO), the crossings |
| `levels` | `monaco.levels/` | the drawing order of the roads: which is over which, their ends. Your fixes go here too ([the editor](guides/editor.md)) |

## Draw it

```python
import lanestyle as ls

m = ls.lane_page("monaco.levels", "monaco_gmns.duckdb", "monaco.duckdb", tunnel_control=True)
m.save("monaco.html")
```

or from the repo: `python lane_page.py monaco.levels monaco_gmns.duckdb monaco.duckdb monaco.html`.

The page is one HTML file that opens offline. Zoom in: lanes and their colours show at every zoom, lane
lines, zebras and sidewalks from zoom 17, arrows and BUS / bike marks from 18. Click a lane to see it;
click a road for its name, class and modes.

Extra keywords go to roadstyle's [`render_edges`](https://khoshkhah.github.io/roadstyle/reference/parameters/):
`basemap=`, `name=`, `street_view_key=` and the rest.

## Next

- [Lanes and markings](guides/lanes-and-markings.md): what is drawn, and why that way.
- [Junctions, zebras and sidewalks](guides/junctions-zebras-sidewalks.md).
- [Fix the drawing in the editor](guides/editor.md): a road under the wrong one, an end that looks wrong.
- [Settings](guides/settings.md): colours, widths, dashes.
