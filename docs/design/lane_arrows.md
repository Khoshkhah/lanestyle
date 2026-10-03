# Painted lane arrows

**Status:** agreed with Kaveh 2026-10-03 ("use generic", "go ahead"). Built (`arrows.py`); not pushed (previews first).

## Problem

A lane says what it is for only in text along the line (`lane_type`: `left + thru`, `fork`, `merge`).
The only arrow is roadstyle's direction chevron. A driver reads a road by the arrows painted on it.
"Turn arrows painted on the lanes" was left out of the first step (`lanestyle_on_roadstyle.md`, *Not in this step*).

## Proposal

One arrow per lane, from the movements that leave it (the same `turns` table `_lane_types` reads):

| Lane type | Arrow |
|---|---|
| `thru`, `left`, `right`, `uturn` | the plain arrow |
| a mix (`left + thru`, `thru + right`, `left + right`, …) | the combined arrow: a straight shaft with a branch per turn |
| `diverge` (fork), `merge`, `end`, a bus or bike lane with no turn | none |

- **Fork and merge get no arrow.** A fork is a lane splitting into lanes that each carry their own arrow; a merge is the reverse. Roads
  do not paint them, and the geometry and connectors already show them. The text label still names them.
- **Generic style** (Kaveh's choice, not the French or any national set): a straight shaft, a triangular head, and a branch at 90°
  for left and right. A U-turn is a hook back. One shape set, drawn as SVG paths.
- **Placement:** one arrow per lane, 10 m before the lane's end (the stop line), pointing along the lane. A lane under 20 m
  long gets one in its middle. Connectors, footpaths, crossings get none (as the direction chevron today).
- **Size:** in metres, like the lanes: about 4 m long, 0.6 × the lane width wide, so it fits a 2 m bike lane too.
  It is drawn as a polygon layer from zoom 18, not an icon, so it scales and rotates with the map.
- **Where it lives:** a new `arrows.py` (lane table + turns → polygons), shipped as a compact column and drawn by a MapLibre
  layer in lanestyle's own JS, added after that band's fill and the lane lines (as `_LINES_JS`). A setting `lanes.arrows`
  (default on, `false` to hide) and `arrow_from_zoom` in `lanestyle.json`. **No roadstyle change.**
- **Order:** above the lane fill and lines, below the zebra and the footpaths on roads.

## As built (differences from the proposal)

- **A thru-only lane gets an arrow only beside a lane of the same link that turns** (left, right, U-turn): that is where the
  choice of lane matters. Without it every piece end of a long road would carry one (Monaco: 1,929 thru-only lanes).
- **A U-turn beside other moves is not drawn** (a hook of its own only when it is the lane's only move).
- **The setting is one block**, `lanes.arrows`: `color`, `length_m` (4), `end_m` (10), `from_zoom` (18); `false` turns the arrows off.
- A turn branch leaves at 45°, at most 1 m sideways, so the arrow stays within 60 % of a 3.25 m lane.
- An arrow that would touch a zebra crossing slides back along its lane (1 m steps, up to 15 m) until clear, else it is dropped.

## Checks

- A unit test per type: `thru` → one shaft polygon, `left + thru` → shaft + one branch, `fork` / `merge` / `end` → none.
- A test that the arrow lies inside its lane and ends 10 m before the lane's end.
- Monaco only: pictures of a junction with several lanes, a fork and a merge, with the interactive map at the spot.

## Open

- Whether a bus lane gets the word BUS painted too (not proposed here).
