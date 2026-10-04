# Design notes

<p class="lead">How lanestyle came to be built the way it is: the problems, the options and what was decided.</p>

- [lanestyle on roadstyle](lanestyle_on_roadstyle.md): why each lane is a roadstyle line, the one
  roadstyle change (widths in metres), the lane table, and the lane lines as their own layer.
- [GMNS CSV input](gmns_csv_input.md): reading plain GMNS files without duckOSM, and the simple lane
  placement that needs.
- [One file: `link_osm`](gmns_link_osm.md): levels inside the GMNS database, so lanestyle needs one input.
- [Pedestrian lanes](pedestrian_lanes.md): a colour for footways, narrow default widths for foot and bike
  lanes, and driving and walking in one map.
- [Painted lane arrows](lane_arrows.md): a generic arrow per lane for turn, straight and combined
  movements; none for fork and merge.
- [Street names](street_names.md): lanestyle's own names, in the arrows' colour and clear of them.
- [Roads for the casing, items for the fill](lanestyle_on_roadstyle_items.md): roadstyle draws the casing of each road (a link) and not its fill; lanes, connectors, lines, zebra, arrows and names are items attached to it, in one order scale; the looks are a theme.
- [The casing and fill numbers](lanestyle_on_roadstyle_levels.md): roadstyle computes the drawing order of the lane table, a connector below every road; the three bands are gone.
- [The drawing order from per-edge intervals](interval_draw_order.md) (superseded): roadstyle 0.12's `casing_level_col` / `fill_level_col` instead of bands and hand cuts.
- [Footways on the carriageway](footway_overlap.md): 19 % of matched footways lie on the road's lanes in Monaco; why lane width alone does not fix it.

The lane placement itself lives in duckOSM, with its own notes: paired carriageways, lane
movements, lane connectors, and runs of pieces as one road.
See [duckOSM's design notes](https://github.com/Khoshkhah/duckOSM/tree/main/docs/design).
