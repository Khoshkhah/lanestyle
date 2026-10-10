# Lanes and markings

<p class="lead">Each road is one line as wide as its lanes; the lanes and their paint lie on it, in metres.</p>

![Boulevard Princesse Charlotte at zoom 20: its bus lane, a zebra, sidewalks, the roundabout's arrows](../img/gallery/lane_lines.jpg)

## The road

roadstyle draws the road: one line whose width is its lanes together, plus the centre line between two
directions (`centre_line_m`) and a thin outline (`casing_m`). Its outline, ends, bridges and tunnels, its
place under or over other roads and its street name are roadstyle's, from the level area: the
[editor](editor.md) changes them.

## The lanes

| lane | drawn | width |
|---|---|---|
| car | invisible, but it highlights and opens its popup when clicked | its OSM `width:lanes`, else `default_width_m` (3.25 m) |
| bus | in `colors.bus` | as a car lane |
| bike | in `colors.bike` | `width_m_by_use.bike` (1.5 m) unless tagged |
| bus and bike | in `colors.bus`, with both marks | as a car lane |

A road cars do not use (a footway, a cycleway, a pedestrian street) is drawn in the colour of who uses
it (`colors.groups`: walking, cycling); pushing a bike counts as walking.

## The paint

- **Lane lines**: dashed between two car lanes (`lines.dash_m` 3 m, `lines.gap_m` 9 m), solid next to a bus
  or bike lane, a solid centre line between two directions; `lines.width_m` wide, from zoom 17.
- **Arrows**: one per lane `arrows.end_m` before it reaches a junction, the moves the lane allows (from
  SUMO's turns: straight, left, right, U-turn, and the forks the movement codes say), from zoom 18.
- **BUS and bike**: painted on bus and bike lanes from 15 m, drawn with strokes, from zoom 18.

All of it is roadstyle items (`render_edges(items=)`), so a road over another covers its paint, and a
tunnel's paint takes the tunnel's colour.
