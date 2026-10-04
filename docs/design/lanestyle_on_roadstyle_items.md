# lanestyle on roadstyle: roads for the casing, items for the fill

**Status:** implemented. It replaces how `lanestyle_on_roadstyle_levels.md` and `interval_draw_order.md` draw the lanes; their reading of the data and their geometry stay.

roadstyle has three ways to be used:

1. **Alone:** the casing and the fill of each road.
2. **With items added to the roads** (mapstyle): the road keeps its casing and fill, and items attached to it are drawn at its place.
3. **With the fill given as items** (lanestyle): roadstyle draws the **casing of each road and not its fill** (`road_fill=False`); the lanes, lines, zebra crossings, arrows and names are items attached to the road (`Overlay(edge_col=, order_col=)`), and they are the fill.

lanestyle uses the third way.

## What a road, a lane and a connector are

| Thing | In roadstyle | Casing | Fill |
|---|---|---|---|
| a **road** = a **link** (a duckOSM edge, `edge_id` = `link_id`) | one row: the link's carriageway line, drawn `width_m` wide | **yes**, roadstyle's own | none (`road_fill=False`) |
| a **lane** | an item attached to its link: a polygon | none | its colour |
| a **connector** | an item attached to the link it leaves (`from_lane`'s link): a polygon, **below all** (order −1) | none (lane-like) | its colour |
| a line, a zebra, an arrow, a name | an item attached to its link | none | its own |

- The **road row** has the link's carriageway as its line: the middle of the link's first and last lane (`lane_num` 1 and the last), and as its width the width of all its lanes plus the casing on each side (`width_m = Σ lane widths + 2 · casing_m`). roadstyle draws a casing as a band inside the width, so the band shows `casing_m`
  outside the lanes: it is the road's outline. All rows are undirected (`directed_col` false): a link and its reverse twin are two carriageways, each on its own side, never paired as two lanes.
- A lane has **no casing**, a road has. A connector has none of its own: the casing at a junction is the casing of the roads that meet there, and roadstyle's casing heads merge it with the lanes that join, as for every road. What is lost: the outline that used to run round a connector's outer side as one thin line;
  the casing of the road it hangs from lies under it instead.
- A footway link is a road with one lane, like a car link.

## The drawing order: roadstyle's numbers, of the roads

The casing number and the fill number are those of the **link**, as in mapstyle (`mapstyle/docs/design/stored_levels.md`):

- The band of a link is complete: the `layer`, else bridge 1 / tunnel -1, else 0; a mapped sidewalk -1 (under its street), a crossing 1 (over it).
- roadstyle **computes** them from the roads, with the complete band and **lanestyle's order** (below). The numbers stored in a duckOSM file (`visualization.edge_levels`) are not read: they are computed with the class order only, so they are not the numbers of this order.

- The numbers are given to roadstyle as `casing_level_col`, `fill_level_col`, `casing_start_col`, `casing_end_col` and `head_m`; every item takes the **fill number of its link**.

There is no solver of lanestyle's own. Lanes and connectors are no roads, so a connector is "below all" by its order as an item, not by the numbers. Where two lanes lie over each other at one position, the overlay that comes later in the list is drawn later.

### The order of a road

Where two roads of one band meet, the one with the higher **order** has the later fill (roadstyle's `order=` column of numbers). The order of a road is roadstyle's class order (`z_order`: higher = on top), and two roads are given **a high order whatever their class**:

- a **roundabout** (the `roundabout` of the lane table, from the OSM `junction` tag): the ring is over every road that meets it, an arm of a higher class included;
- a **tunnel** (the tunnel tag, or a band below the ground): a tunnel road is over the roads of its band that it meets.

Both get the class order plus 100, above every class. A road with no class takes no part in the order, as before.

### Roads that meet share their end point, exactly

roadstyle finds where roads meet by **exact equality of their end points** (`compute_levels`: the end points of every road, as node numbers). The rule that a road's casing is not drawn after the fill of the roads that meet it, and the merging of the heads, work only
for roads it sees at one node. The line of a road is the middle of its kerb lanes, so at a node the ends of two roads differ by a little (millimetres to decimetres): roadstyle did not see them meet, and a free road, a short stub for instance, could be
given a number above its neighbour's: its casing was then drawn across the lanes of the road it meets.

So `lanestyle` **snaps the ends**: the road's first point is its `from_node_id` and its last point is its `to_node_id` (of the link the road's line follows). All the ends at one node get the **same point**, written to the same coordinates. Nothing else of the line moves.

**The widest road decides the point** (2026-10-04). The mean of all the ends pulled a roundabout's ring sideways at every arm that joins it (the arm's end is up to 1.6 m off the ring's lane centre; in Monaco 43 % of the road ends moved by more than 30 cm, up to 9.5 m), and the ring's outline stepped by that much at each node:
the dark wedges, the bulges and the uneven inner edge of the ring. Now the point is the mean of the ends of the roads within half a metre of the widest road at the node (the ring's own links), and those ends move to it. A narrower road (an arm) keeps its line and gets the point as **one more vertex at that end**:
a short hook that lies inside the wider road, whose fill hides it. At a node where a narrower end is farther from the point than half the widest road (separate carriageways, a gap in the data), the mean of all the ends is used, as before. Open: where an arm joins at an acute angle, the hook can show a thin sliver of casing
beside the arm. A road keeps its own `from` and `to` nodes, so two roads meet in roadstyle's eyes exactly where the GMNS network says they meet.

## The items and their order

Every item has `edge_id` (its link) and `order` (a whole number, lower first, the same scale for all). In each position roadstyle draws: the casings, the fills (none), the items by `order`, roadstyle's own one-way arrows and street names (turned off here).

| Order | Items | Overlay (label) | Style (theme) |
|---|---|---|---|
| −1 | connectors | `connectors` | `connector` |
| 0 | lanes (polygons) | `lanes` | `lane` |
| 0, listed later | a footpath mapped on a carriageway, so that the road does not hide it | `lanes` (order 1, see below) | `lane` |
| 1 | dividers, centre lines | `dividers`, `centre` | `divider`, `centre` |
| 2 | zebra crossings (stripes) | `zebra` | `zebra` |
| 3 | lane arrows | `lane arrows` | `lane_arrow` |
| 4 | street names | `street names` | `street_name` |

- **Lanes are polygons** (the lane's line, `width_m` wide, round ends, simplified to 3 cm), not lines: an overlay has one `width_m` for the whole style, and lanes have different widths, so lines would need one style for each width. The polygon is as exact and takes the colour of its mode group from the property `color` (`color_col`). A tunnel's colour is the group's colour blended with the land colour (the faded look; the colour is opaque, so no ring shows
  through at a joint, and the tunnel's own body layer is gone). A footpath on a road is a lane with order 1: it lies over the road's lanes (order 0), and the lines (order 1, listed after the lanes) stay over it.
- **Lines** (`lines.py`) are the dividers and centre lines between lanes, as before; each carries its link (the smaller link for a centre line drawn once). They are drawn by roadstyle's overlay line with `width_m` and `dash`. The **edge lines** and bridge edges are gone: the road's casing is the outline.
- **Zebra stripes** carry the link of the first lane the crossing names; **arrows** the link of their lane; a **name** the link it is drawn along.
- The **fillets, the frame gaps** (the verge of a sidewalk) and the **lane-type labels** are not items: they stay lanestyle's own layers, placed by `lsAnchor` right before the fills of their position (under the items) as before.

## The theme

The looks are a **lanestyle theme**: `src/lanestyle/styles/themes/lanestyle.yaml`, whose block `config.overlays.styles` has the named styles (roadstyle ships none, `docs/design/overlay_styles.md` in the roadstyle repo): `lane`, `connector` (fill, colour per item), `divider` (dashed, width in metres, from a zoom), `centre`, `zebra`,
`lane_arrow` and `street_name` (text, size, colour, halo). roadstyle reads it by its address (`settings=`, a YAML file or a dict) with the settings that tune the tunnel and bridge looks of the roads' casing. lanestyle's settings file (`data/lanestyle.json`) keeps what is geometry and data: widths, stripe thickness, arrow size, the colours of the mode groups, the
clearance of the names.

## The page

- **Clicking.** A lane is a feature of the overlay `lanes` (a connector of `connectors`, not clickable unless `connectors_clickable`). The click script reads `rs:select` of the overlay `lanes`, finds the lanes the turns lead into, and colours them (clicked red, the lanes it turns into green, U-turns purple) with the paint of the overlay's layers: roadstyle's `rsColor` on an overlay
  takes one set and one colour, and the three sets are drawn together.
- **Legend rows** (the modes) stay lanestyle's, in the Roads box. The Roads box of roadstyle lists the road classes of the links, which are hidden here as before.
- **The link roads** are in the page, invisible (no fill): a click on the casing band opens the road's popup (the link's name and class); Street View picks them.

## What is lost, and what stays for roadstyle

- **Minimum width of a line.** A divider 0.2 m wide is under a pixel below zoom 18. The old page kept it at least one device pixel and faded it in; an overlay style has no minimum in px (roadstyle). Until it has, `min_zoom` of the line styles is 17.
- **A tunnel's body layer** is gone (the opaque colour does it). **The fade-in** of lines, zebra and arrows over two zooms is gone (an overlay has an opacity for the whole style).
- **Several colours on an overlay at a click:** done in lanestyle's script (above), not by `rsColor`.
- **Icons:** none.
- **A width for each feature** of a line overlay: the lanes are polygons for this reason.

## Tests

- The roads: one row per link, the width and the line of the carriageway, no connector among them.
- The numbers: read from a stored table when there is one (a stale table and an unknown id are errors); computed otherwise; the items take the fill number of their link.
- The items: lanes and connectors as polygons with `color`, `edge_id` and `order`; a connector's order is below every lane's; lines, zebra, arrows and names carry their link; no edge line.
- The page: `road_fill` false; the theme's styles are in use; the order of the layers in a position; the click script works on the overlay.
