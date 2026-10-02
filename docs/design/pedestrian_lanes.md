# Pedestrian lanes, narrow bike and foot lanes, and several modes in one map

**Status:** agreed with Kaveh 2026-10-01 ("go ahead with all three"). Built; not pushed (previews first).

## Problem

lanestyle shows which lane is for a bus or a bike (a "Lane use" colouring) but not which is for people on foot:

- only `bus` and `bike` are painted (`_MARKED`); a `walk` lane keeps the road colour;
- every lane without a width is drawn 3.25 m wide, so a footpath looks as wide as a car lane, and an on-road
  bike lane (duckOSM places it 1.5 m wide) overlaps the car lane beside it;
- a map has one GMNS mode: a road with its sidewalks needs the driving and the walking tables together, and the
  roads are in both.

## Proposal

1. **A colour for `walk`.** `colors.walk` in `lanestyle.json` (an amber, apart from the blues of bus and bike);
   `walk` joins `_MARKED`, so the "Lane use" colouring and its legend list *footways* when there are any.
2. **Default widths by use** (`width_m_by_use`, overridable like every setting):

   | Lane | Where `width_m` is null |
   |---|---|
   | `walk` | 2.0 m |
   | `bike` **beyond the link's motor lanes** (`lane_num > lanes`, `lanes` empty counts as 0) | 1.5 m |
   | anything else (a `bike` lane that is one of the motor lanes, `auto`, `bus`) | `default_width_m`, 3.25 m |

   The bike rule matches duckOSM: its on-road bike lane (`cycleway=lane`) is the last lane, beyond `link.lanes`, and is
   placed 1.5 m wide; a lane that `bicycle:lanes` marks inside the carriageway is a full lane. A footway or a cycleway
   has `lanes` empty (it has no motor lanes), so its lane counts as beyond and gets the narrow width.
3. **Several modes in one map:** `from_gmns(db, modes=("driving", "walking"))`. The first mode is read as it is; each
   later mode adds only the lanes of links the earlier ones do not have (a footpath, not the road you also walk on),
   and only the turns between lanes that are kept. `render_lanes.py --modes driving,walking`.

Not changed: lane lines, popups, the click colouring, roadstyle.

## Checks

Tests with a tiny GMNS database that has a driving and a walking schema; a preview of Monaco (driving + walking) in
`renders/pedestrians/` for Kaveh to look at before anything is pushed.
