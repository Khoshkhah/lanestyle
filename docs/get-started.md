# Get started

<p class="lead">Install lanestyle, draw Monaco from the bundled sample, then your own area.</p>

## Install

Python 3.10 or newer. roadstyle 0.11 or newer (line widths in metres), geopandas, shapely 2,
duckdb and pandas come with it.

```bash
pip install lanestyle
```

??? note "Developing lanestyle"

    ```bash
    git clone https://github.com/Khoshkhah/lanestyle.git && cd lanestyle
    pip install -e ".[dev]"
    pytest -q
    ```

    The tests build a tiny GMNS database on the fly, so they need no data.

## A first map, no data needed

The repo ships Monaco's lanes as GeoParquet, read straight from duckOSM's GMNS export
(`docs/data/monaco_lanes.parquet` and `monaco_turns.parquet`, 1 MB together):

```python
import geopandas as gpd
import pandas as pd
import lanestyle as ls

lanes = gpd.read_parquet("docs/data/monaco_lanes.parquet")
turns = pd.read_parquet("docs/data/monaco_turns.parquet")
ls.render_lanes(lanes, turns=turns).save("monaco.html")
```

Open `monaco.html`. Zoom past 16 and the lanes take their real width, 3.25 m each; click one.

<iframe src="../maps/monaco.html" loading="lazy" title="Monaco, lane by lane" class="ls-demo" id="monaco-demo" allowfullscreen></iframe>
<p class="ls-demo-bar"><a href="#" onclick="document.getElementById('monaco-demo').requestFullscreen(); return false;">Full screen</a> ·
<a href="../maps/monaco.html" target="_blank" rel="noopener">Open in a new tab</a></p>

The page is a plain file: it opens without a server, and only the base-map tiles come from the
internet. `ls.write_serve("monaco.html")` drops a `serve.py` next to it for when you want a URL
(`python serve.py 8080`).

## Your own area

Lanes come from [duckOSM](https://github.com/Khoshkhah/duckOSM), which places each lane of an
OpenStreetMap road and works out the lane-to-lane turns, as a GMNS database:

```bash
pip install "duckosm @ git+https://github.com/Khoshkhah/duckOSM"
curl -LO https://download.geofabrik.de/europe/monaco-latest.osm.pbf
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving
duckosm gmns monaco.duckdb -m driving -o monaco_gmns.duckdb
```

```python
import lanestyle as ls

lanes, turns = ls.from_gmns("monaco_gmns.duckdb")
ls.render_lanes(lanes, turns=turns).save("monaco.html")
```

One file is enough: duckOSM writes each link's bridge, tunnel and `layer` into the GMNS file. Two
optional extras, from the duckOSM database the GMNS file was made from (`source_db=`): the area's
boundary outline, and the levels for GMNS files made before duckOSM wrote them. The whole chain, step
by step: [From OSM to lanes](pipeline.md).

Or from the shell, with the script in the repo:

```bash
python render_lanes.py monaco_gmns.duckdb monaco.html
```

## What you see

| | |
|---|---|
| **Lanes** | one line per lane, exactly its width in metres from zoom 16 on, roadstyle's class widths below; coloured by road class (the `mono` palette) |
| **Lane lines** | dashed dividers between lanes of one direction, a solid centre line between the two directions, grey edges; they stop at junctions |
| **Levels** | tunnels under the street, bridges over it, in the order of the OSM `layer` tag |
| **Labels** | the street name once per road, and each lane's turns (`left + thru`, `right`, `U-turn`, `fork`, `merge`, `end`) from zoom 18 |
| **Bus and bike lanes** | painted over the palette; their colours are rows in the Roads box |
| **Click a lane** | it turns red with a popup (road, lane, turns, width, level, ids); the lanes it leads into turn green, U-turns purple |
| **Connectors** | the curves that join a lane to the next through a junction, drawn like lanes and coloured with them on a click |

Every look with its code: [the gallery](gallery.md). Every keyword: [Python API](reference/python.md).
