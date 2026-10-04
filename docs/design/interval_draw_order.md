# The drawing order from per-edge intervals

**Superseded** (also by [roads for the casing, items for the fill](lanestyle_on_roadstyle_items.md)) by [The casing and fill numbers](lanestyle_on_roadstyle_levels.md): roadstyle computes the numbers (mapstyle's `node_levels` is gone). Kept as the record of the intervals step.

**Status:** proposal, waiting for Kaveh's OK ("go for interval plan", 2026-10-03: "it is a big step"). No code yet.

## Problem

Roads that meet or cross at different levels need an order: arms must join a roundabout ring without round caps on it, a ground path
must lie over a tunnel's sidewalk with its whole outline, a bridge over its street. lanestyle solves each case by hand:

- roadstyle's three bands plus `lines._group` (`low@-1`, `low@-2`) and the `above` cuts, for what interacts with what;
- its own `draw_order` (connectors -300 / -250, a footpath on a road 100, a ring above its class: `render_lanes`);
- outlines cut by hand (`frames` per level, the lines stopped at other links' surfaces).

Each new crossing needed another patch (2026-10-03: the roundabout ring, a ground path over a tunnel's sidewalks). The general
solution already exists and is released: **roadstyle 0.12.0 `casing_level_col` / `fill_level_col`**, with the intervals computed by
**mapstyle `node_levels`** (`mapstyle/docs/design/node_levels.md`). lanestyle does not use it.

## The model (as in node_levels.md)

Every road gets an interval `[casing, fill]` of integers. At each position all casings come before all fills.

- roads that share a node: intervals intersect, they merge cleanly (an arm and the ring);
- an overpass (lines cross, no shared node, different level): disjoint intervals, the upper later, so it is drawn over the lower one, casing included;
- both directions of a segment are one road; a road that changes level along itself is **cut** into pieces, each with its interval.

`mapstyle.node_levels.compute(source_db)` returns `Levels.intervals` `{edge_id: (casing, fill)}` (anything missing is `(0, 0)`) and
`Levels.cuts`. lanestyle's `link_id` is the duckOSM `edge_id`, in every mode, so a link's interval is a dictionary lookup. Monaco: 561 overpass pairs, 3
given up and fixed by cutting, about 5 s. OR-Tools CP-SAT is optional (`pip install mapstyle[solver]`); without it a heuristic is used.

## Proposal, in steps (each checked on Monaco, in pictures, before the next)

1. **Compute.** A small `levels.py`: `link_intervals(source_db)` → `{link_id: (cl, fl)}` from `mapstyle.node_levels.compute`, positions doubled (as `mapstyle.with_cuts`)
   so the odd positions stay free. `from_gmns` puts them in the lane table (`_cl`, `_fl`), as it puts `roundabout`. A lane takes its link's interval; a connector takes
   its from-lane's. Without a `source_db` (or without mapstyle) every lane is `(0, 0)` and the page is drawn as now.
2. **Draw.** `render_lanes` passes `casing_level_col="_cl"`, `fill_level_col="_fl"` to `render_edges`. roadstyle then draws one casing and one fill layer per
   position (`roads-fill-lv<n>`; position 0 keeps the ids). The per-edge `order_col` stays only for what is *inside* a position: a connector under its lanes
   (-300 / -250), a footpath on a road above it, a crossing at +1. The ring rank and the level part of `draw_order` go.
3. **Our own layers per position.** The lane lines, outlines, arrows, junction fillets, frame gaps, zebra and tunnel body are lanestyle's MapLibre layers, today
   inserted after each *band's* fill (`AFTER`). Each feature gets its position `p` (the fill position of its lane) and its layer goes right after that position's fill
   layers, so a higher position covers a lower one's lines and arrows by itself. The names layer stays on top.
4. **Cut roads.** `Levels.cuts` roads (3 in Monaco) are drawn in pieces: lane geometry split at the bounds (drawing only: the data is not touched), each piece with its interval.
5. **Remove what the intervals replace**, one at a time, each only after its Monaco pictures are the same or better: `lines.above` and the `low@` groups in
   `_group` (a level's lines are no longer cut by hand), the per-level frames cut, the ring rank, the footpath-over-road order if a position gives it. What still needs a
   same-level rule stays: frames match a sidewalk with its own road (`_group`), junction trim at a node.
6. **Tests and docs.** A synthetic overpass (a bridge over a road, a ring with arms), `test_a_tunnel_differs_from_ground_in_look_only` stays green, the docs guide, `AGENTS.md`.

## What does not change

- roadstyle: **not changed** (0.12.0 has the columns; lanestyle needs `roadstyle >= 0.12`).
- The lane geometry, widths and the GMNS data. No metre-width, lines or arrows logic changes.
- Tunnel and bridge looks: still roadstyle's (levels and looks); only the order between them comes from the intervals.

## Checks (Monaco only)

Before / after pictures, with the interactive map at each spot: the Sporting roundabout (arms over the ring), the Avenue Pasteur path over the tunnel sidewalks
(lane `7929000899462360833_1`), Boulevard Louis II tunnel, a bridge and the street under it, Avenue Princesse Grace (sidewalks, crossings), a footpath on a road.

## Risks and open questions

- **mapstyle as a dependency.** It is not installed in the `roadstyle` env (only a project folder). Recommended: an optional extra, `pip install -e ../mapstyle` into
  the env, imported lazily like keras; no mapstyle = positions all 0 (today's drawing).
- **Step 3 is the big one:** `_LINES_JS` and the others change from four bands to N positions; a page with many positions has more layers (Monaco: how many? to be counted).
- **roadstyle's positions with the tunnel look** (`tunnel_opacity_scale`, the dashed classes) are described in `level_columns.md` but not yet tried at lane width.
- `tiles=True` is not supported with these columns (not used by lanestyle).

## As built (2026-10-03, steps 1 to 3 and the outlines; not pushed)

- `levels.py` `link_intervals(source_db)`: mapstyle's `node_levels.compute`, positions doubled; `from_gmns(..., source_db)` adds `pos_casing` / `pos_fill` to every lane
  (the names have no leading underscore: `itertuples` renames those). Needs the database of **every mode** (duckOSM's `monaco.duckdb`: 1,278 of 14,529 lanes are off
  position 0, 7 levels, 6 of 594 overpass pairs given up by the heuristic; OR-Tools is not installed, `pip install ortools` for the optimal solution).
- `render_lanes` passes `casing_level_col="pos_casing"`, `fill_level_col="pos_fill"`. `lines._band(r)` is `bridge` or the fill position (`"-2"`, `"0"`, `"2"`),
  `_group(r)` the same (one position is one surface); `lines._level(r)` keeps the old three bands for the popup and the tunnel flag. A table without `pos_fill` is drawn as before.
- The page: `lsAnchor(ids, band, before)` (in `_ANCHOR_JS`) finds `roads-fill-lv<p>` / `roads-fill` / `roads-bridge-fill`; the lines, arrows, junction fillets (and their tunnel
  hatch, flagged `tn`) and the tunnel body go after (fillets and body: before) their own position's fill layers.
- Checked in pictures (Monaco): the Avenue Pasteur path over the tunnel's sidewalks (lane `7929000899462360833_1`: outline whole, no frame cut needed), the Sporting roundabout, a
  stack of bridges at Boulevard d'Italie, a tunnel with a bridge piece. 48 tests.
- **Not yet** (steps 4 and 5): roads that must be drawn in pieces (`Levels.cuts`: none with the heuristic, 0 in Monaco), and removing what the intervals may replace
  (`lines.above` and the `low@` groups still run for tables without a drawing order; the per-level frames and the ring rank stay until their pictures say they can go).

### Correction the same day: the outline is a casing (Kaveh: "you didn't use interval approach!!!")

The first build used the intervals only to order the fills and kept lanestyle's hand-made outlines (a union per level, cut by neighbours' surfaces) on top. Every
road that crosses or meets another at a different position then showed seams: a roundabout ring split over fill positions 0 and 2 (the OSM `layer=1` footway across it)
had a lobe at each joint (lane `3446728318236761534_2`). The model says what to do: **a casing is drawn at the road's casing position, under every fill of that
position**, so roads that share a node merge and a road over another covers its outline. So, with `pos_casing` / `pos_fill` in the table:

- `lane_lines` draws no per-lane `edge`, no union outline of a level (connectors, footpaths), no frame-gap edge and makes no `above` or frame cut of an outline. It draws one boundary
  line per link (a connector or a footway: its own surface), `union of its lanes, round ends, simplified 3 cm`, labelled with the **casing** position, twice the width (the
  lane's fill covers the inner half); only the paint (dividers, centre lines) keeps the junction trim and is labelled with the **fill** position.
- The page puts an outline layer in the **casing slot** of its position (`lsAnchor(..., 2)`: before `roads-fill-lv<p>-under`, so below every fill of the position and below the
  frame-gap fill, which is placed before the fill), and the paint after the fill.
- `_group` is again the level (what interacts, e.g. which footpath a sidewalk is matched with); the position is only the label of a layer.
- A table without a drawing order is drawn as before, with the old outline code (still there, to be deleted when every path has intervals).
- The solver matters: `pip install ortools` (it gave 0 unsatisfied overpass pairs, 5 levels; the heuristic left 6 given up and a ring in three positions).

### Step 4 done, step 5 decided (2026-10-03)

- **Cut roads:** `levels.link_intervals` returns the cuts too; `levels.cut_lanes` splits the lanes of a cut road at the solver's bounds (drawing only: the first piece keeps the row, the others
  are appended with `piece` True and the same `lane_id`, each in its own interval). Monaco (solver): one road, a 100 m footway in a tunnel on layer -3, 3 pieces; it was drawn at ground level
  before. A test covers it (50 tests).
- **Step 5, what is not deleted:** the old outline code (`above`, the `low@` groups, the union outlines, the frame cuts, the hand `draw_order` of a tunnel layer) only runs for a table *without* a
  drawing order. That is every table read without a duckOSM source database: lanestyle's GMNS-only input (the docs' quickstart, `docs/data`) has no edges for `node_levels`. Deleting it would
  break that input. It goes when the intervals can be computed from a GMNS link table alone (from / to nodes, `bridge` / `tunnel` / `layer`), which is a separate step, not started.
- **Kept on purpose in the interval path:** the ring rank (roads of one position and one class tie in roadstyle's order: a ring and an arm of the same class), the footpath-on-road order, connectors under lanes
  (all orders *inside* a position), and the per-level frames (what a sidewalk is matched with is a level, not a position).

### Correction 2 (2026-10-03, Kaveh: "we have casing_level_col, fill_level_col for each road ... at the casing level we draw their casing, at the fill level its lanes, the lane separators and the rest")

That is the model, and the build matched it except for bridges. A bridge lane was labelled with a band of its own (`bridge`, roadstyle's deck layers, above every position), so its outline
(a casing line drawn by us) lay over the road it continues into and ended in a closed black capsule at each joint (Avenue de la Costa, lane `683666470146267312_1`). Now, with a drawing order:

- a bridge is a road like any other: `lines._band` is the lane's fill position, and roadstyle is given an empty bridge column (`bridge_col="rs_bridge"`), so it draws the bridge in its position layers, not
  in the deck band; the bridge's outline is the heavier `bridge_edge` style, at the road's casing position, under the fills of that position: the road it joins covers its end caps;
- the page makes only the line layers that have lines (`present` in `_LINES_JS`), so no layer per band and type that stays empty;
- an option, `lanes.roadstyle_casing` (off), lets roadstyle draw every edge's casing itself (`casing_m` = the outline width) instead of our own outline lines: clean joints too, but a thin dark line
  also shows between neighbouring lanes (roadstyle's casing is the whole width of each lane) and tunnel lane ends show round blobs. Pictures in `renders/intervals/`.
