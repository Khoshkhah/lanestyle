# Lane lines

<p class="lead">Lanes have no casing. The lines between them are lanestyle's own layer, drawn to scale on top of the lanes, each type styled on its own.</p>

<div class="ls-shot" markdown>
![Boulevard Princesse Charlotte at zoom 20: a bus lane and two lanes, dashed dividers, grey edges, stopping at the mini-roundabout](../img/gallery/lane_lines.jpg)
</div>

| Type | Where | Default |
|---|---|---|
| `divider` | between lane k and k+1 of one road (same direction) | off-white `#e8e8e8`, 0.15 m, dashed 3 m / 9 m |
| `centre` | between the two directions of a two-way road, also one mapped as two one-way ways side by side | off-white `#e8e8e8`, 0.15 m, solid |
| `edge` | the road's outer edges | grey `#6b6b6b`, 0.10 m, solid |

## How they are placed

Each line is a lane's centre line offset by half its width, in metres (shapely, in the area's UTM
zone). The lines of a road that runs through several pieces are offset once along the whole chain,
so a bend shows no kinks at the joints.

A centre line is drawn once per road: by the smaller of a link and its `reverse_link_id`, or of two
one-way links whose lane 1 left edges lie on each other (a dual carriageway mapped as two ways).

**Lines stop at junctions**, as painted lines do. A line whose road meets a junction is cut by the
lane surfaces of every other road there, grown by `junction_trim_m` (1 m). So a main road's
dividers run on past a side street's mouth, and its edge line breaks there. Where a road goes on
into the next piece of the same road, nothing is cut.

## In the page

The lines go in as compact columns and become one MapLibre line layer per level and type, inserted
right after that level's lane fill: a bridge covers the lines of the street under it. They are drawn
to scale but never thinner than `line_min_device_px` (1.5) physical pixels, and fade in over two
zoom levels from `width_m_zoom`. `line-dasharray` counts in multiples of the line's width, so the
dashes are exact at every zoom.

## Style them

The roadstyle way: a `lanestyle.json` in the current folder, or a `"lanes"` key in `settings=`,
stating only what changes. `dash_m: null` means solid; `"lines": false` turns them all off.

```python
ls.render_lanes(lanes, turns=turns, settings={"lanes": {
    "lines": {"divider": {"color": "#ffffff", "width_m": 0.12, "dash_m": [3, 6]},
              "edge": {"color": "#444444"}},
    "junction_trim_m": 2,
}})
```

## Corners at junctions

`"fillet_m": 1.5` (off by default) also paves every gap narrower than twice that between lane
surfaces, corners at junctions and slivers where two carriageways diverge, in the nearest lane's
colour. Lane ends are round everywhere, tunnels included, so the gain is small and a Monaco build
takes about 18 s longer.

Right-hand traffic only for now: lane 1 is the leftmost lane. Left-hand areas would need the lane
order checked in duckOSM first.
