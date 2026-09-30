# lanestyle on roadstyle

**Status:** agreed with Kaveh 2026-10-01. Steps 1 and 2 built on 2026-09-30 (roadstyle branch
`metre-width`, not released; lanestyle 0.4.0, not pushed); step 3 waits for Kaveh's OK. duckOSM is not changed: its `gmns-map` stays as
it is until lanestyle is built and tested, and replacing it is a later decision.

## Problem

A lane map needs what roadstyle already does for roads: draw order from the OSM `layer` tag, bridge
decks, tunnels, base maps, a filter box, popups, arrows. lanestyle today has its own deck.gl
renderer, and duckOSM's `gmns-map --style lane` its own canvas one; neither has draw order, so a
bridge and the street under it merge into one surface.

## Idea

Draw lanes with roadstyle: each GMNS lane becomes one line on its own geometry, and roadstyle brings
everything else unchanged (`rsQuery` / `rsColor` included).

One thing is missing: **widths in metres**. roadstyle sets widths in pixels per road class, at fixed
zoom stops blended linearly. Lanes sit side by side, 3.25 m apart, so each must be exactly its width
in metres at every zoom, or neighbours overlap or leave gaps.

## Split (so roadstyle stays stable)

| Where | What | Changes |
|---|---|---|
| **roadstyle** | one general option: "line width in metres, from a column" | once (0.10.0), then left alone |
| **lanestyle** (public on GitHub; PyPI later) | everything about lanes | whenever the lane map changes |

roadstyle learns nothing about lanes or GMNS: the option suits any line data with a real width (a
road with a `width` tag, a canal, a runway). lanestyle is the lane-level companion to roadstyle, as
mapstyle is the full-map one.

## 1. roadstyle: widths in metres

New `render_edges` arguments:

| Argument | Does | Default |
|---|---|---|
| `width_m_col` | a column with each line's width in metres; lines are drawn at that width from `width_m_zoom` on | `None` (as today) |
| `width_m_zoom` | the zoom from which metre widths apply; below it, the class widths as today (so a lane doesn't vanish zoomed out) | `16` |
| `casing_m` | the casing's width on each side, in metres (two lanes side by side show a line of 2 × `casing_m` between them) | `0.15` |

How: MapLibre draws `p(z) = 512 · 2^z / (40,075,017 · cos φ)` pixels per metre at zoom `z` and
latitude `φ` (the data's centre). A zoom `interpolate` with `["exponential", 2]` doubles the value
per zoom level, so stops at `width_m_zoom` and 22 with value `["*", ["get", width_m_col], p(z)]` give
the exact metre width at every zoom in between. Below `width_m_zoom` the stops are the class widths
as now. It applies to every width roadstyle draws (fill, casing, bridge deck, tunnel dashes, tunnel
mouths). Lanes never trigger the two-way fan-out: each lane has its own offset geometry, so no lane
is the reverse of another.

Tests: `w · p(22)` pixels at zoom 22 and the class width below `width_m_zoom`; a map without
`width_m_col` is unchanged (every existing test passes).

## 2. lanestyle

### Input: a lane table, the roadstyle way (decided by Kaveh, 2026-10-01)

roadstyle takes a GeoDataFrame of edges, not a database. lanestyle does the same with lanes, so the
engine works with lanes from any source; a reader turns a GMNS database into that table.

```python
import lanestyle as ls
lanes, turns = ls.from_gmns("monaco_gmns.duckdb", source_db="monaco.duckdb")   # the reader
ls.render_lanes(lanes, turns=turns, palette="mono").save("lanes.html")          # the engine
```

**`lanes`**: a GeoDataFrame, one row per lane, lon/lat (EPSG:4326), each line in the direction of travel:

| Column | Needed? | Meaning |
|---|---|---|
| `lane_id` | yes | unique id |
| `geometry` | yes | the lane's centre line |
| `highway` | yes | road class (colour, filter box), as in roadstyle |
| `width_m` | no, 3.25 | lane width in metres |
| `use` | no, `auto` | `auto`, `bus` or `bike` |
| `bridge`, `tunnel`, `layer` | no | the lane's level, read exactly as roadstyle reads them |
| `name` | no | street-name label (the reader sets it on lane 1 only: one label per road) |
| `link_id`, `lane_num`, `turn` | no | shown in the popup |

**`turns`** (optional): a DataFrame with `from_lane` and `to_lane` (both `lane_id`s), for click-a-lane.
Without it, clicking a lane only selects it.

**`from_gmns(gmns_db, mode="driving", source_db=None)`** reads `gmns_<mode>.lane`, `.link` and
`.movement` and returns `(lanes, turns)`:

- `highway` = the link's `facility_type`; `width_m` = `lane.width` (3.25 where untagged); `use` from
  `lane.allowed_uses`; `name` from the link, on lane 1 only.
- levels (`bridge` / `tunnel` / `layer`): from the GMNS `link` if it has those columns (a later
  duckOSM export may add them), else from `source_db`, the duckOSM database the GMNS file was made
  from (`link_id` = `edge_id`, table `<mode>.edges`); without either, every lane is at ground level.
  Once duckOSM's GMNS export carries the levels, `source_db` is no longer needed; the engine and the
  lane table don't change.
- `turns` from `movement`: each lane of the inbound link in `start_ib_lane`..`end_ib_lane` (NULL =
  every lane) to each lane of the outbound link in `start_ob_lane`..`end_ob_lane` (NULL = every lane).

### The engine

- **Colours, the roadstyle way:** a roadstyle palette (`carto`, `highsat`, `mono`; default **`mono`**
  so the lane colours stand out) and roadstyle's own settings (`roadstyle.json`, or `settings=`
  passed on). lanestyle's own choices are defaults in `src/lanestyle/data/lanestyle.json`, overridden
  the roadstyle way (a `lanestyle.json` in the current folder, or a `"lanes"` key in `settings=`;
  state only what changes):

    ```json
    {"lanes": {"colors": {"bus": "#c9783a", "bike": "#3f8fc9", "clicked": "#e0453a", "turns_into": "#149a86"},
               "default_width_m": 3.25, "casing_m": 0.15, "width_m_zoom": 16}}
    ```

  Bus and bike lanes are marked on top of the palette (roadstyle `color_options`, `missing: base`).
- **Popup:** the lane table's columns that are present (`lane_id`, `lane_num`, `turn`, `use`, `width_m`, `link_id`).
- **Click a lane:** a small script paints the clicked lane red and the lanes `turns` leads into green
  with `rsColor`, which also raises them within their level. `turns` is embedded in the page.
- **Replaced:** lanestyle's current deck.gl and folium maps (kept in the git history). A route is
  no longer built in: pass it as a roadstyle overlay (`overlays=[rs.Overlay(route_gdf)]`).

### Built (2026-09-30): what the code settled

- `width_m` is filled by the engine (`default_width_m`), not by the reader, so any lane table gets the
  default. Every lane in today's duckOSM GMNS files has a null width (3.25 m everywhere).
- `turns` has an optional `type` column; `uturn` rows are painted `colors.uturn` (purple), as the old
  map did (commit bf68692). The clicked lane also gets roadstyle's selection glow in `colors.clicked`
  (`select_color`), else the default violet glow hides the red.
- `render_lanes` returns roadstyle's `WebMap` (`.save`, `.html`), with the click script added.
- The July GMNS files in `../duckOSM/data/db/*_gmns.duckdb` don't match today's duckOSM dbs (0 shared
  ids), so `source_db` can't give them levels. Fresh ones are built into lanestyle's `data/`
  (gitignored) with `duckosm gmns <db> -m driving -o data/<area>_gmns.duckdb`.
- Test maps: `renders/lanes/` (`build.py`, `check.py`, served by its `serve.py`).

## Steps

1. roadstyle: short design note in its `docs/design/`, code and tests on a branch.
2. lanestyle: rebuilt on that branch of roadstyle, with tests; test maps (Monaco, Södermalm, Tartu)
   for Kaveh to try locally.
2b. Lane markings (after step 2 works, its own short section here first): painted lines instead of
   the dark divider. Dashed between lanes of one direction, a centre line between the two
   directions (lane 1 and its reverse link's lane 1), a solid edge line. A MapLibre line layer added
   by lanestyle's page script, width in metres by the same formula; `line-dasharray` counts in line
   widths, so `[20, 60]` on 0.15 m = 3 m dash, 9 m gap, right at every zoom. `casing_m=0` so the
   gaps show the road. Hard part: one marking layer per level (tunnel / ground / bridge). OSM rarely
   tags `change:lanes` and duckOSM doesn't export it, so every line between lanes is dashed.
3. After Kaveh's OK: roadstyle PR and release 0.10.0; lanestyle made public on GitHub.
4. Later, a separate decision: duckOSM's `gmns-map --style lane` calls lanestyle.

## Open

- **lanestyle's history before going public.** Its 14 commits carry the Gmail address in the author
  line. Recommended: a fresh history (one first commit), since almost all the code is replaced. The
  alternative: rewrite the 14 commits to name only (as was done for duckOSM).
