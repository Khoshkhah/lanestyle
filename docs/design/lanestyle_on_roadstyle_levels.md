# lanestyle on roadstyle 0.14: the casing and fill numbers

**Status:** implemented; the way the lanes are drawn is replaced by [roads for the casing, items for the fill](lanestyle_on_roadstyle_items.md) (the numbers now belong to the road, not to each lane). Replaces the "interval from mapstyle's `node_levels`" of [interval_draw_order.md](interval_draw_order.md): the numbers now come from roadstyle.

## What roadstyle changed

- roadstyle draws every road by two numbers, a **casing number** and a **fill number** (`casing_level_col`, `fill_level_col`), with the casing in three parts (`casing_start_col`, `casing_end_col`, `head_m`): position by position, lowest first,
  and at each position all casings before all fills. The three bands, the class as a draw order, `band_col` as a layer rule and `order_col` are gone (`order_col` is an error). Two edges at the same position are drawn in no set order.
- roadstyle computes the numbers (`compute_levels`) from a **band** per edge (`band_col`, which replaces the level from the tags: a null is 0) and an **order** per edge (`order`: where two edges meet, the higher is painted later; a null makes no wish).
- mapstyle no longer solves the order, so its `node_levels` is gone; lanestyle must not import it.
- Overlays attached to edges (`Overlay(edge_col=, order_col=)`) draw a feature at its edge's fill number, after the fills, by order.

## Decision 1: the numbers are computed by roadstyle on the lane table

Every row of the lane table is **an edge**: a lane, and a connector too (a lane row with `connector` true, with its own id). roadstyle computes the casing and fill numbers of all of them in one call:

```python
compute_levels(lanes, band_col="band", order="order", head_m=5.0)      # and the four columns go to render_edges
```

- **The band** is complete, as in duckOSM and mapstyle: the level from the tags (the `layer` if a number, else a bridge 1, a tunnel -1, else 0), except a mapped sidewalk -1 and a crossing 1.
- **The order** is lanestyle's own. **A connector is 0, below every other road** (which are 1 and up), so a connector is painted before any road it meets. The other roads keep their relative order: a road's class (roadstyle's class order, plus 1);
  a roundabout's ring half a step above its class (it lies over the arms that join it); a footpath mapped on a carriageway 100 (over its road).
- The four columns, `casing_start`, `casing_level`, `casing_end`, `fill_level`, go to `render_edges` as `casing_start_col`, `casing_level_col`, `casing_end_col`, `fill_level_col`, with `head_m`. lanestyle's own layers read `casing_level` and `fill_level`.

**Why not `visualization.edge_levels`** (duckOSM's `duckosm levels`): it holds the numbers of the roads of the source database (links), computed with the **class** order. lanestyle's edges are lanes and connectors, which are not in
the source database, and its order is its own (connectors below everything). Numbers read from the table would give no number to a connector and not the order lanestyle needs, so lanestyle always computes its own, and does not read the table
(there is nothing stale to check). A table could serve lanestyle only if `duckosm levels` stored lanestyle's order; that is a question, not a change here.

## Decision 2: a road that changes level along itself

roadstyle gives an edge one casing number and one fill number, so it is drawn at one level for its whole length. The cutting of such a road into pieces (`cut_lanes`) is removed.

## Decision 3: the three bands are gone

The page always has positions, so every layer of lanestyle goes by position: after the fills of its position (lines, painted arrows, the zebra), in the casing slot of its position (the outline), before the fills (junction fillets, the tunnel body). `lsAnchor` finds
`roads-fill-lv<p>` (`roads-fill` for 0), never `roads-low-fill`, `roads-high-fill` or `roads-bridge-fill`. A bridge is a road like any other (roadstyle is given an empty bridge column).
roadstyle makes one layer of street names for each position: lanestyle hides all of them (`roads-labels*`), not only the first.

## Decision 4: the lines, the painted arrows, the zebra and the connectors' outlines stay lanestyle's layers

The overlays attached to edges draw a feature at its edge's fill number, so they could replace these layers, but an overlay cannot draw the same thing yet:

| lanestyle's | what an overlay lacks |
|---|---|
| lane lines (dividers, centre lines, outlines), and the outline round a connector's surface | a width in **metres** that follows the zoom, dashes in multiples of the width, a fade-in; an overlay line has a width in pixels and no dashes. An outline is a casing: an overlay is drawn after the fills, never in the casing slot |
| painted lane arrows, zebra stripes | a minimum zoom and a fade-in; a polygon overlay has an outline layer that can only be hidden with width 0 |
| street names | an overlay has no text kind |

So they stay, placed by position with `lsAnchor`; the outline of a connector is drawn at the connector's own casing number. They would move to overlays attached to edges (`edge_col` = the edge's id, here the lane id) with this order, once roadstyle's overlays can draw them
(lane 0 is the roadstyle line itself):

| order | what |
|---|---|
| 1 | lane lines, and the outline of a connector |
| 2 | zebra stripes |
| 3 | painted lane arrows |

(The names stay last, over everything: roadstyle's own one-way arrows and names are the end of each position.)

What roadstyle would need first (a question for Kaveh, since roadstyle changes are agreed one at a time): in an `Overlay`, `minzoom`, an opacity that follows the zoom, a line width in metres with dashes, no outline for a fill, a casing slot, and a symbol kind for text.

## What does not follow the roads yet

lanestyle's own layers (lines, arrows, zebra, names) are separate sources: `rsFilter` on the roads hides roadstyle's layers and its arrows and names, but not these.

## Tests

- The band is complete (layer, bridge, tunnel, sidewalk, crossing).
- A connector is painted before every road it meets: its fill number is lower than that of both lanes it joins; casing never above fill.
- No removed argument or layer id: a page is made with roadstyle 0.14 (no `order_col`), the page's JS never names `roads-low-fill`, `roads-high-fill` or `roads-bridge-fill`, and all `roads-labels*` layers are hidden.
- A bridge over a road is at a higher position, and a table without numbers is drawn (roadstyle computes them).
