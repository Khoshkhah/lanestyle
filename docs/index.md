# lanestyle

<p class="lead">Lane-level road maps for Python: every lane drawn at its real width, with painted lane lines, turns, and a click that shows where a lane leads.</p>

<div class="ls-hero" markdown>
![A lanestyle map of Monaco: Boulevard des Moulins with its bus lane in blue, dashed dividers, turn labels on every lane and a roundabout](img/hero.jpg)
</div>

```bash
pip install lanestyle
```

```python
import lanestyle as ls

lanes, turns = ls.from_gmns("monaco_gmns.duckdb", source_db="monaco.duckdb")   # the reader
ls.render_lanes(lanes, turns=turns).save("lanes.html")                          # the engine
```

lanestyle is built on [roadstyle](https://khoshkhah.github.io/roadstyle/): each lane is one
roadstyle line on its own geometry, exactly its width in metres from zoom 16 on. roadstyle brings
the rest: draw order from the OSM `layer` tag, bridges over and tunnels under, base maps, the filter
box, popups, one-way arrows and the `rs*` JavaScript API. lanestyle is to lanes what
[mapstyle](https://khoshkhah.github.io/mapstyle/) is to the full base map.

## What you can do

<div class="grid cards" markdown>

-   :material-road-variant:{ .lg .middle } **Draw any lane table**

    ---

    A GeoDataFrame with one row per lane: id, centre line, road class, width, use, level.

    [:octicons-arrow-right-24: The lane table](guides/lane-table.md)

-   :material-database-outline:{ .lg .middle } **Read a GMNS database**

    ---

    `from_gmns` turns a duckOSM GMNS file into lanes, turns and connectors.

    [:octicons-arrow-right-24: From OSM to lanes](pipeline.md)

-   :material-road:{ .lg .middle } **Painted lane lines**

    ---

    Dashed dividers, solid centre lines and edges, drawn to scale and cut at junctions.

    [:octicons-arrow-right-24: Lane lines](guides/lane-lines.md)

-   :material-cursor-default-click-outline:{ .lg .middle } **Click a lane**

    ---

    It turns red, the lanes it leads into green, U-turns purple; every lane carries its turn label.

    [:octicons-arrow-right-24: Turns, clicks and labels](guides/turns.md)

-   :material-bus:{ .lg .middle } **Bus and bike lanes**

    ---

    Painted over the palette, with their colours as rows in the Roads box.

    [:octicons-arrow-right-24: Settings](reference/settings.md)

-   :material-fullscreen:{ .lg .middle } **See it live**

    ---

    Monaco, lane by lane, full screen in your browser.

    [:octicons-arrow-right-24: Live map](maps/monaco.html)

</div>

## The family

| | draws | from |
|---|---|---|
| [roadstyle](https://khoshkhah.github.io/roadstyle/) | a road network, one line per edge | any edges GeoDataFrame |
| [mapstyle](https://khoshkhah.github.io/mapstyle/) | a whole base map with the roads | a duckOSM database |
| **lanestyle** | every lane of every road | a lane table, or a duckOSM GMNS database |

All three save one HTML page that works offline and speaks the same `rs*` JavaScript API.
