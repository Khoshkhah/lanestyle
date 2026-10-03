# Street names that match the painted arrows

**Status:** agreed with Kaveh 2026-10-03 ("go ahead"; white with a halo). Built (`street_names.py`); not pushed (previews first).

## Problem

Street names are roadstyle's `roads-labels` layer: grey text along each lane's line (a road's name is set on its lane 1 only).
Seen next to the painted arrows (`lane_arrows.md`):

- **Colour:** grey text, where the arrows and lines are white paint. Two looks for what is painted or written on one road.
- **Overlap:** the text runs along lane 1, which is also where a lane's arrows are, so a name can lie across an arrow.
- **Position:** on a wide road the name is on lane 1, not at the middle of the road.

## Proposal

1. **Hide roadstyle's `roads-labels`** from lanestyle's page (`setLayoutProperty(..., "visibility", "none")`). No roadstyle change.
2. **One label per road run in lanestyle's own layer** (`street_names.py`, shipped with the arrows): the name placed along the middle of the road
   (the line between its outermost lanes' centres), a text layer in the same font (as `lane-type-labels` already does), colour from `lanes.names`
   in `lanestyle.json`, the same family as `arrows.color`: white, with a dark halo, so it reads as paint on the road.
3. **Keep clear of the arrows and the zebras:** the name's line loses the stretches within `clear_m` of an arrow or inside a zebra crossing
   (the arrows are known in metres, so this is a geometry cut, not a collision guess). MapLibre then places the text on what is left.
4. **Setting:** `lanes.names` (`color`, `halo`, `size`, `from_zoom`, `clear_m`); `false` leaves roadstyle's names on. The repeat distance is MapLibre's
   `symbol-spacing` (300 px), not a setting.

## Checks

- A test that a name is dropped within `clear_m` of an arrow and kept elsewhere.
- Monaco only: pictures of a wide road and a junction before and after, with the interactive map at the spot.

## As built

- A two-way road is named once, on lane 1's left edge (its centre line), by the smaller of its two links; a one-way link along the middle of its lanes.
- The name sits on the centre line's paint, with its halo: like a painted road name, and readable.
- A road mapped as pieces gets a label per piece, a short piece none that fits (MapLibre hides it). ``ponytail:`` no merging of pieces into runs yet.
