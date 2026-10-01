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
    {"lanes": {"colors": {"bus": "#9db8d9", "bike": "#3f8fc9", "clicked": "#e0453a", "turns_into": "#149a86"},
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

## 2b. Lane lines as their own layer

**Status:** approved by Kaveh 2026-09-30 and built the same day (`src/lanestyle/lines.py`).

### Problem (Kaveh, 2026-09-30)

Step 2 separates lanes with roadstyle's **casing**: each lane's 0.15 m dark edge, inside its width.
That fails in two ways (Södermalm, Högalidsgatan / Varvsgatan, zoom 19.5):

- **At intersections the lines vanish.** roadstyle draws every casing first, then every fill, so the
  lanes of the crossing roads cover the dividers. Small white slivers also show where lane ends meet
  at an angle.
- **The line can't be styled.** It is the road casing: no colour, dash or width of its own.

### Proposal

The lanes get **no casing** (`casing_m = 0`): each lane is a plain surface, and neighbours merge into
one road, as asphalt does. The lines are **lanestyle's own layer**, drawn on top of the lanes:

| Type | Where | Default |
|---|---|---|
| `divider` | between lane k and k+1 of one link (same direction) | white, 0.12 m, dashed 3 m / 9 m |
| `centre` | left edge of lane 1 on a two-way road (between the two directions); drawn once per road, by the link with the smaller id | white, 0.12 m, solid (Kaveh, 2026-09-30; first dashed 3 m / 3 m) |
| `edge` | the road's outer edges: the right edge of the last lane, and the left edge of lane 1 on a one-way road | grey, 0.10 m, solid |

- **Geometry, in Python:** each line is the lane's centre line offset by half its width (shapely, in
  metres), from the lane table's `link_id` and `lane_num`. `from_gmns` adds `reverse_link_id` (the
  link with the same two nodes, swapped) so the engine knows which roads are two-way. A lane table
  without `link_id` / `lane_num` gets no lines; the map still draws.
- **Lines stop at intersections**, as painted lines do: a line ending at a node where 3 or more links
  meet is cut back by `junction_trim_m` (default 5 m). Inside the junction the lanes are one surface.
- **Styled in `lanestyle.json`**, each type on its own, the roadstyle way:

    ```json
    {"lanes": {"lines": {"divider": {"color": "#ffffff", "width_m": 0.12, "dash_m": [3, 9]},
                         "centre":  {"color": "#ffffff", "width_m": 0.12, "dash_m": null},
                         "edge":    {"color": "#6b6b6b", "width_m": 0.10, "dash_m": null}},
               "junction_trim_m": 5}}
    ```

  `dash_m: null` = solid. `"lines": false` turns them all off.
- **Drawing:** lanestyle's page script adds a GeoJSON source and one MapLibre line layer per level:
  tunnel lines after `roads-tunnel-fill`, ground after `roads-fill`, bridge after `roads-bridge-fill`.
  So a bridge covers the lines of the street under it. The width is in metres, with the same formula
  as roadstyle's metre widths, and the lines are hidden below `width_m_zoom`. `line-dasharray` counts
  in multiples of the line's width, so `dash_m` is divided by `width_m`. Dashes are then exact at every
  zoom.
- **The slivers and the hairline:** a divider or centre line sits on every seam between two lanes, so
  the hairline is covered. The slivers inside junctions, where round lane ends meet at an angle, may
  remain. If they do, a later option could fill each junction with one polygon in the road's colour.

### Built: what changed from the proposal

- **Lines stop at the crossing road's surface, not a fixed 5 m.** 5 m was too short at wide junctions
  (Högalidsgatan / Varvsgatan: edge lines ran across Varvsgatan). A line whose link meets a junction
  is cut by the lane surfaces of every other link there (not its own or its reverse), grown by
  `junction_trim_m`, now 1 m. So a main road's dividers run on past a side street's mouth and its edge
  line breaks there, as painted roads do.
- **Page size:** lines are offset with mitre joins and simplified by 5 cm (round joins doubled the
  points), and sent as compact columns, not GeoJSON features, rebuilt in the page. Tartu: 10.9 MB
  (7.6 MB without lines; 17.7 MB as plain GeoJSON).
- The white slivers inside junctions are gone with the casing, so no junction polygon is needed.
- A lane highlighted by a click (red / green / purple) covers its own lines: roadstyle's highlight
  draws above them.

### Not in this step

- Solid lines before a junction, or next to a bus lane (Swedish "bussfält"). OSM rarely tags
  `change:lanes`, and duckOSM doesn't export it.
- Turn arrows painted on the lanes (from `turn`).

### Checks

- Tests:
  - line types and counts on the small test db: a divider between lanes 1 and 2, one centre line per
    two-way road, edge lines;
  - trimming at a junction node;
  - settings override one type;
  - no lines without `link_id` / `lane_num`.
- In the browser, at the same Högalidsgatan junction and a Monaco tunnel: screenshots on the
  previews page (port 8090).

## Steps

1. roadstyle: short design note in its `docs/design/`, code and tests on a branch.
2. lanestyle: rebuilt on that branch of roadstyle, with tests; test maps (Monaco, Södermalm, Tartu)
   for Kaveh to try locally.
2b. Lane lines as their own layer: see the section "2b." above. Built 2026-09-30.
3. After Kaveh's OK: roadstyle PR and release 0.10.0; lanestyle made public on GitHub.
4. Later, a separate decision: duckOSM's `gmns-map --style lane` calls lanestyle.

## Open

- ~~lanestyle's history before going public~~ Done 2026-09-30: the commits were rewritten to the
  GitHub noreply address (as duckOSM's were) and the repo made public.
