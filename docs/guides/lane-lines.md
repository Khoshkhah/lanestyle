# Lane lines

<p class="lead">Lanes have no casing; the road has. The lines between lanes are items attached to the road, drawn to scale on top of the lanes, each type styled in the theme.</p>

<div class="ls-shot" markdown>
![Boulevard Princesse Charlotte at zoom 20: a bus lane and two lanes, dashed dividers, stopping at the mini-roundabout](../img/gallery/lane_lines.jpg)
</div>

| Type | Where | Default |
|---|---|---|
| `divider` | between lane k and k+1 of one road (same direction) | off-white `#f4f4f4`, 0.2 m, dashed 3 m / 9 m |
| `centre` | between the two directions of a two-way road, also one mapped as two one-way ways side by side | off-white `#f4f4f4`, 0.2 m, solid |

## How they are placed

Each line is a lane's centre line offset by half its width, in metres (shapely, in the area's UTM
zone). The lines of a road that runs through several pieces are offset once along the whole chain,
so a bend shows no kinks at the joints.

A centre line is drawn once per road: by the smaller of a link and its `reverse_link_id`, or of two
one-way links whose lane 1 left edges lie on each other (a dual carriageway mapped as two ways).

**Lines stop at junctions**, as painted lines do. A line whose road meets a junction is cut by the
lane surfaces of every other road there, grown by `junction_trim_m` (1 m). So a main road's
dividers run on past a side street's mouth. Where a road goes on
into the next piece of the same road, nothing is cut.

## In the page

Each line is a feature with its road (`edge_id`) and `order` 1, drawn by roadstyle's overlay `dividers` /
`centre` at the fill number of its road: a bridge covers the lines of the street under it. The look is the
theme's style `divider` / `centre` ([the design](../design/lanestyle_on_roadstyle_items.md)): a width in
metres, `dash` (in line widths, so exact at every zoom) and `min_zoom` 17. The road's casing is the outline;
there are no edge lines.

## Style them

The look is a **theme**: `src/lanestyle/styles/themes/lanestyle.yaml`, block `config.overlays.styles`. Pass your
own file or dict as `settings=` to change it; `"lines": false` in `settings={"lanes": ...}` leaves the lines out.

```python
ls.render_lanes(lanes, turns=turns, settings={
    "config": {"overlays": {"styles": {"divider": {"kind": "line", "color": "#ffffff", "width_m": 0.12, "dash": [3, 6], "min_zoom": 17}}}},
    "lanes": {"junction_trim_m": 2},
})
```

## Corners at junctions

`"fillet_m": 1.5` (off by default) also paves every gap narrower than twice that between lane
surfaces, corners at junctions and slivers where two carriageways diverge, in the nearest lane's
colour. Lane ends are round everywhere, so the gain is small and a Monaco build
takes about 18 s longer.

Right-hand traffic only for now: lane 1 is the leftmost lane. Left-hand areas would need the lane
order checked in duckOSM first.
