# Footways that lie on the carriageway

**Status:** analysis; the "narrow, then shift" proposal below was prototyped and is NOT recommended (see the last section). Waiting for Kaveh's choice (2026-10-03: lanes `5322443421394628197_2` and `8965540963774805217_1`, Avenue Princesse Grace, lon 7.43686 lat 43.74904,
"lane overlapping"). No code yet. The fix is in duckOSM (data), not in lanestyle's drawing.

## Problem

A footway matched to a road (duckOSM `link_along`, `along_link_id`) lies partly on the road's lanes. In the example the footway (OSM way 851792665 `#2r`, 2 m wide) is 0.94 m from the centre line of
lane 2 of 2 (3.25 m wide, `tertiary`): **74 % of the footway is inside the carriageway**. lanestyle draws a footpath that is 60 % or more on a road above it (`_footpaths_on_roads`), which hides most of
that lane and its arrow. The rule is a workaround for the data.

## How common (Monaco, 2,499 footways matched to a road)

| Overlap with the road's lanes | Footways |
|---|---|
| 30 % or more | 486 (19 %) |
| 60 % or more | 196 |
| 90 % or more | 58 |

Mostly `residential` (76 roads), `tertiary` (51), `secondary` (43), `service` (34) streets.

## First idea, and why it is not enough: fit the lane width

Narrow the lanes of the overlapped side down to a floor of 2.5 m, so the carriageway ends where the footway starts. Measured on the 486: the mean depth of the overlap is 1.15 m and
the median room to narrow (down to 2.5 m a lane) is 0.75 m: **only 160 of the 486 (33 %) can be cleared by width alone; 326 cannot.** The example is one of those: the footway's centre line is about 2.4 m from
the way line, so even a 2.5 m lane reaches past it.

## What the data says

The OSM footway is mapped closer to the road's line than half a carriageway. Either the carriageway is narrower than the class default (a lane of 2.5 to 3 m, not 3.25), or the footway is mapped
on the kerb or in the road. duckOSM cannot know which.

## Options

1. **Narrow, then shift (prototyped: not recommended, see below).** For a link with a matched footway that overlaps its lanes: first narrow the overlapped side's lanes (floor 2.5 m), then shift the whole carriageway away from the
   footway by what is still missing, up to a limit (about 1 m). What remains is a footway really mapped in the road: it stays and is drawn above (today's rule), and is counted in the log. Needs
   the footway match (`link_along`) *before* the driving lanes are placed, or a second pass that re-offsets them (the lane lines come from one offset curve per run, `gmns_lane_runs.md`).
2. **Width only:** fixes a third, leaves two thirds; simple.
3. **Move the footway out of the road** (walking geometry): changes the pedestrian network; avoid.
4. **Leave it:** what is drawn now.

## Checks (Monaco)

Before and after pictures at the example and the five worst overlaps; the count of footways at or over 30 % overlap (486 now); no lane narrower than the floor; no change to links without a matched footway;
duckOSM's tests; the lane count, turn arrows and movements unchanged.

## Open questions

- The floor (2.5 m) and the shift limit (1 m): Kaveh's choice.
- Does a carriageway shifted off its OSM line matter for the paired carriageways (`gmns_paired_carriageways.md`), whose gap between the two ways is computed from the lane widths?

## Prototype result (2026-10-03, scratch code, no duckOSM change)

Narrow-then-shift on Monaco's 486 footways at 30 % overlap or more (floor 2.5 m, shift limit 1 m): narrowing alone clears 34, narrow + shift about 76 (16 %); 336 stay at 30 % or more; the mean
overlap falls from 0.57 to 0.41. It narrows 705 lanes by 0.56 m on average (max 0.75 m) and shifts 160 roads by up to 1 m (7 shifts refused for the line shape); no lane goes under the floor. At the
example (Avenue Princesse Grace) the outer lane and its arrow become visible on the grey road, but the footway still covers a strip of it. Most of these footways are mapped in the road, which width
and placement cannot fix. **Recommended instead:** a drawing-side change, arrows and lane lines keep clear of a footway that lies on the road (as they do for zebras); or leave it as it is.
