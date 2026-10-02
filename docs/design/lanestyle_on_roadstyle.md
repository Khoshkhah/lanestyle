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


## Footway joins and twin footways (2026-10-01)

- **Joins** (moved to duckOSM 2026-10-02: `gmns_walking.lane_connector`, duckOSM `docs/design/gmns_walk_joins.md`; lanestyle's `_join_footways` is gone, `gmns._keep_joins` reads them). Until then: a road lane sits beside its link's line, a footway lane on it, so at a node the two links share
  their ends are up to a lane width apart. Where the two links share a node in the data and the lane ends are 0.3-6 m apart, lanestyle
  adds a straight connector lane (footway kind) from the road lane's end to the footway's. Never between links that share no node
  (that would invent a link OSM does not map). Monaco: 542.
- **Twin footways** are no longer nudged by `_break_twins` (that 0.2 m shift is for car lanes only); both are drawn as the data has them.

## Frames: a road and its sidewalk (2026-10-01)

duckOSM writes, on a `footway=sidewalk` link, the road it runs along (`along_link_id`, `along_mode`, `along_gap_m`; 1,342 of Monaco's 1,374,
394 of them roads that exist only in `gmns_driving`). `frames.py` (`frame_gap_m`, default 2 m, 0 = off) takes each such sidewalk whose
surface lies within that gap of its road's surface, at the same level: the gap is filled (in the walk colour, through the junction-fillet layer's
`c` property), and no outline is drawn between the two (road edge lines and the footpath outline are cut by the frames' area). Drawing only; no
lane moves. Farther sidewalks, and the 32 with no road, keep their own outline. Monaco: 1,310 gap polygons.

Level (Kaveh, 2026-10-01: "consider the level for grouping"): duckOSM picks the road among links of the sidewalk's own level (`layer`, else
bridge 1 / tunnel -1, else 0), so a sidewalk is never tied to the road above or below it (64 were, in Monaco); `frames.py` also groups only
within one band. lanestyle remaps a road whose link the multi-mode merge dropped (the walking twin of a one-way road) to the kept link of the
same OSM way: 144 sidewalks had no road in the table before. Monaco: 1,310 sidewalk links with a road, 1,404 gap polygons.

The gap is a verge, not a lane (Kaveh, 2026-10-02): drawn in a lighter tint of the footway colour; clicking it opens a popup of its own (`frame gap · road …
· sidewalk … · N m apart`, and only that one); in a tunnel it takes the tunnel look (faded, with a light hatch).

One street, several ways (Kaveh, 2026-10-02: `161748267#10f` was not grouped with `568187257#4f`): duckOSM records one road per sidewalk, chosen by the
distance to the road's *edge* (not its centre line, which is far for a wide street), at the sidewalk's midpoint; a sidewalk 58 m long runs
along two ways of one street. `frames.py` therefore groups a sidewalk with every road of the recorded road's street name (lane 1's `name`) at the
same level, within `frame_gap_m`. The popup names the nearest of them. Monaco: 1,658 gap polygons.

Footway twins (Kaveh, 2026-10-02: `680777232#3r` / `#3f` "un-directed roads with different geometry"): the two links of a footway have the
same line both ways, which roadstyle pairs as a two-way road's lanes and shifts apart. `render_lanes` passes roadstyle's `directed_col` (False
for a walk lane), so a footway pair is one undirected strip, unshifted, with no arrows; the 0.2 m nudge (`_break_twins`) is for car lanes only.

Any footpath beside a road (Kaveh, 2026-10-02: "do the same for all footways, with a different label"): duckOSM also fills `along_*` for a footway, path, pedestrian
or cycleway link that is not a mapped sidewalk (not a crossing, a link or steps) when its edge lies within 2 m of a same-level road's edge,
and says `along_kind = 'adjacent'` (a mapped sidewalk: `'sidewalk'`). Nothing moves, and only a mapped sidewalk gets `parent_link_id` or may be
placed from its road. lanestyle frames both kinds the same; the popup says `footpath` for an adjacent one. Monaco: 560 adjacent (2 m; now `adjacent_m` 5 m)
(450 footway, 86 pedestrian, 24 path), median 3.5 m between lines.

Sidewalk colour and the gap's casing (Kaveh, 2026-10-02): a mapped sidewalk (`footway=sidewalk`) has its own colour (`colors.sidewalk`) and legend row; an
adjacent footpath keeps the footway colour. The gap between road and footpath is a lighter tint of its footpath's colour, and its own sides, those
touching neither the road nor the footpath, get the usual edge line (the casing), so the verge ends in a line like every other surface.

The whole gap (Kaveh, 2026-10-02: "when a footway is matched to a road we should fill all its gap, not just the close part"): a footpath that is within
`frame_gap_m` of its road anywhere is a frame, and the gap is then filled along its whole length, up to `frame_reach_m` (default 8 m) wide; the closing
radius follows the widest gap (sampled every metre along the footpath), not `frame_gap_m`.

A crossing that is no crossing (Kaveh, 2026-10-02: `1342546079#1r` "must be a sidewalk but it is a crosswalk"): OSM tags the whole 173 m way
`footway=crossing`, though only its last 4 m cross the road (duckOSM splits it at the nodes: `#1` 2 % on a road, `#2` 76 %). `_demote_crossings`: a crossing
link longer than `crossing_max_m` (12 m) with under `crossing_min_on` (20 %) of its length on the road surface of its level is drawn as a footway, and
its popup says why (`kind`). The data keeps OSM's tag. Monaco: 90 links. They are not framed as sidewalks (no `along_*`: duckOSM leaves crossings out).

Gap casing off, whole gap by strips (Kaveh, 2026-10-02: the gap's casing "makes a lot of issues"): `frame_casing` (default false) turns the gap's own edge line off; the
closing that rounded the gap's ends (stray arcs) is replaced by straight strips between the footpath's centre line and the nearest points of the
road's surface, one per metre, so a gap ends square. A footpath duckOSM matched to a road is a frame wherever it lies within `frame_reach_m` (8 m) of it
(before: only within `frame_gap_m`, 2 m, of it at its nearest point; `712186090#16r`, 2.17 m, was left out). Monaco: 1,742 gap polygons, 1,550 footpaths.

A footway that goes on in another band (Kaveh, 2026-10-02: `1531374855#1f` → `1525443697#1f`): both are layer 1, the first `bridge=yes` (bridge band), the second a raised
walkway (high band), joined at one node. Each band's outline used to end in a round cap with a thick bridge arc across the joint; now a footway's outline stops where
the surface of a footway of another band that meets it at a node begins (not where one merely passes over or under), so the bridge's thick outline ends square
and the thin one carries on.

A connector's modes (Kaveh, 2026-10-02, roundabout `4191422298276505638_1>1158609578243345373_1`): a connector took the mode group of the lane it leaves, so a connector from a
street cars and pedestrians share (teal) onto a car-only ring drew as a teal blob on the grey ring. It now has the modes both its lanes have (here: cars only).

Connectors below lanes (Kaveh, 2026-10-02: "give low order to the connector, so it goes below the other lanes in the same level"): `render_lanes` gives every connector roadstyle's
per-edge draw order `-300` (`order_col`), so inside a level it is drawn under every lane. A connector only fills the gap between lanes; it never sits on a lane of another colour
(a teal connector on a car-only ring). Its colour is the modes both its lanes share (`_from_gmns`).

Tunnel body (Kaveh, 2026-10-02, circles at tunnel joints): roadstyle draws a tunnel's fill at 72 % over its casing, so the ring of one lane's round end shows through the next lane at
every joint. lanestyle puts an opaque polygon (`tunnel_body`, the land colour, `""` = off) under the fills of the low band, over the casings: the rings inside a joint are hidden, the casing beyond the
lane's width stays.

Connectors unclickable (Kaveh, 2026-10-02): `connectors_clickable` (default false). roadstyle picks a click and a hover from `map.queryRenderedFeatures` on its road layers; lanestyle's page
script leaves features with `connector` true out of that answer, so the lane under a connector is picked, or nothing. On Monaco's roundabout cut-out: 405 test points reported a connector with the setting on, 0 off.

The gap at a corner (Kaveh, 2026-10-02: `7093696539804813988_1` / `1638459837974238401_1`, `939530782#3f`): where a footpath goes from one road to the next the strips (footpath centre line to the nearest road point) left a wedge open.
The gap is the strips plus the closing of footpath + road (radius = half the widest gap, up to `frame_reach_m`); with no casing on the gap its rounded ends show nothing.
Straight connectors are drawn above turn connectors (draw order -250 over -300).

A bike lane's connector (2026-10-02): a connector has no `lane_num`, so the "bike lane" test (`lane_num` beyond the link's `lanes`) failed and it drew in the car group; a connector that takes a bike lane's `use` is now a bike
lane's in the mode group (blue). duckOSM gives it the bike lane width (1.5 m, not 3.25 m).

The outline of a tunnel footway that meets a ground footway (Kaveh, 2026-10-02: `688664226#1r` "overlapping visualization with other roads on ground"): the rule "a lower footway that meets a higher one at a node is outlined with the higher level" moved
the whole tunnel footway's outline to the ground band, over every ground road it passes under. Now only the stretch within `_JOIN_M` (3 m) of that node is outlined with the higher level, the rest keeps its own band;
no line is drawn across the seam.
The lanestyle patch that added a "thru" turn for every connector without a movement is removed: duckOSM writes those movements now.

A tunnel footway without an outline (Kaveh, 2026-10-02: `3991034106733057832_1`, edge `690903307#3r`, 47 m): the rule that stops each band's outline where a footway of another band that meets it at a node begins used that footway's whole surface, so a long
ground footway cut the tunnel's outline everywhere the two overlap (62 of 63 m of its visible sides had no line). It now uses that footway's surface within `_JOIN_M + 1` m of the shared node only.

Which footpaths and which roads match (Kaveh, 2026-10-02: `2898748414202046809_1` / `8634413191741468793_1`, `2944189401358023478_1` / `4488916522033515384_1`): (1) a road to run along is one cars can use (a link of `gmns_driving`);
a service road only people walk on is not, so no gap is filled between two walking-only lanes (70 footpaths were matched to one). (2) A `footway=crossing` link is matched, like an adjacent footpath, only when it is 10 m or longer and runs
along the road for most of its length (`899409581#1`: 11 m beside `177189425#1f`); shorter crossings are real (a crossing of a side street also runs along the main road, so direction alone is no test: it matched 581 of Monaco's 1,434).
lanestyle draws a matched crossing-tagged link as a footway. Monaco: 99 such links, 2,226 matched footpaths, 3,161 gap polygons.

Crossings that continue a sidewalk (Kaveh, 2026-10-02: `833633689#1r`, `833633689#2f`, `833633691#1f`, `833633691#2r` "do gap filling"): a short `footway=crossing` link across a side street's mouth runs along the main road and continues the sidewalk on both sides.
duckOSM now matches it (`along_kind` adjacent) when it shares a node with a matched footpath and runs along that footpath's road (372 of Monaco's 1,434 crossing links); a short one is still a crosswalk (cream, with its zebra), only now framed:
the gap between it and the road is filled. lanestyle draws a crossing-tagged link as a footway only when it is longer than `crossing_max_m` (10 m) and matched, or has under `crossing_min_on` on a road.

Popup: the match, and the street's short pieces (Kaveh, 2026-10-02: "why doesn't lane A match lane B?" for `1086377404#2f` / `503462464#2f`, `1086377392#6r` / `851792666#1f`, `1086377392#3r` / `503471324#4f`): the matches existed in the data but nothing showed them. A
footpath's popup now has `along` (the road it runs along, the kind, how many roads its route has) and a road's popup `footpaths` (the footpaths whose route has it). A footpath is also framed with every piece of its street (same name) within `frame_reach_m`, so a 3 m piece it
does not run along for 4 m (`503471324#4f`) is not left out.

A footpath on a road (Kaveh, 2026-10-02: `4644359574953198651_1` "gone under" `6333652900798709432_2`): `1086377387#2f` lies 95 % on the road lane of `8056051#2f`; a road is drawn above a footway by class, so the footway vanished. A footpath (not a crossing, not a connector) with 60 % or
more of its area on the road surface of its level is drawn above the roads (roadstyle's per-edge order `100`). Monaco: 207.

A tunnel differs in colour and pattern only (Kaveh, 2026-10-02: "why are you treating tunnels in another way?"): the rule that moved a tunnel footway's outline to the higher level near a node (and the seam it needed) is removed. Every level keeps its own outline all along; the only
joint rule, for any two footways of different levels that meet at a node, is that each outline is cut where the other footway's surface lies by the shared node (so no round cap shows over the neighbour). `3991034106733057832_1`: no casing missing except the part under the other footways' surfaces.
What stays tunnel-specific is the look: roadstyle's faded fill with a hatch, and the opaque `tunnel_body` base under it (a translucent fill shows the rings of the lanes' round ends).

Layers are levels (Kaveh, 2026-10-02: `2945046272619776365_1` (footway, layer -1) and `6879738458846830640_1` (road, layer -2) "on different layers and shouldn't be connected"; `6038399490234152030_1` / `6879738458846830640_2` too): roadstyle draws every layer below ground in one `low` band, and lanestyle used the draw band to decide what interacts, so
layers -1 and -2 were one level. `lines._group` is what a lane interacts with: its band, and for the low band its layer (`low@-1`, `low@-2`; a tunnel with no layer number is -1). Outlines are merged and cut, lanes framed, matched and drawn above roads by group; the lines still go in the draw band
(`_real`). Higher layers (a layer 1 and a layer 2 bridge) are still one draw band each; split them the same way if a case shows it. duckOSM already matches by the exact level.

Layer -1 over layer -2 (Kaveh, 2026-10-02: "you didn't put layer -1 completely over layer -2, in colour and casing"): the layers below ground are one roadstyle band, drawn by road class, so a layer -2 road could lie over a layer -1 footway. (1) Colour: a lane of the low band gets roadstyle's per-edge
order `layer * 90 + rank`, the rank inside the layer: a connector under its lanes (turns -30, straight -20), a road class by roadstyle's z order (0-9), a footpath on a road +15; every layer -1 lane is above every layer -2 lane (checked in the page: about -85 against -173,
connectors -120 against -200). (2) Casing: a lower layer's lines (lane lines, connector casing, footpath outline) are cut where a higher layer's surface lies (`lines.above`), so no outline of layer -2 shows over layer -1. Layers -1 to -4 exist in Monaco; the order is clamped
at +/-400 (layer -4's connectors at -390 are the last that differ).

A footway end over a road's connector fill (Kaveh, 2026-10-02: `8863753797539555542_1`, `34574368882725376_1`, `6871880265432049446_1`, Boulevard Rainier III): a footway runs to the road's centre node (duckOSM keeps it where OSM maps it), and connectors were drawn at the bottom (-300 / -250), under every lane, so
the footway's round end showed on top of the road's own surface. The root is the connector's draw rank, not the footway: a connector cars can use is part of the road, so it now ranks just under its own road class (roadstyle's z order, `_connector_order`: class z - 0.5, turns - 0.6), over a footway and
under the lanes of its class; a connector only people walk on keeps -300 / -250. Tested by hiding lanestyle's footway joins (no change) and by the rank change (the lump is gone). Not done: `_join_footways` still adds footway connectors in lanestyle, which Kaveh says
a drawing tool should not do; they belong in duckOSM's GMNS. Open: the small dark hook where the two-lane road ends (duckOSM's U-turn connector, "a half-circle curve for U-turns is not built").

The casing at a connector (Kaveh, 2026-10-02: "you didn't fix it completely, the casing issue is there yet", same spot): a connector's own two edge lines were drawn wherever no other lane or connector's surface covered them, with flat lane ends, though the page draws lanes with round ends. Two faults: the edge line closed the mouth of the footway that meets the road (a footway's surface hid no connector casing, though it cuts a road's edge line), and a lane's round end stuck out past the line, which then ran as a hook through the road's surface.
The outline near a connector is now the boundary of the surface the map draws (`lines.lane_lines`): the level's lanes with round ends, plus the connectors, kept within the connector's surface and the end disks of the lanes it joins, and open where a footway's surface lies. Per level (`_group`), so a bridge no longer hides the casing of a road below. Checked on the reported spot at zoom 20.5 and 22 and on three other Monaco junctions (`renders/footway_end/other_junction_*.png`): the same or better. Monaco's page is 4.2 MB (3.8 MB before): the union boundary repeats part of the lane edge lines.

Footway joins are data (Kaveh, 2026-10-02: "lanestyle is a visualization tool, it isn't right to add connectors on its own"): duckOSM writes them (`_build_walk_joins`, `gmns_walking.lane_connector`: Monaco 542, the same footway ends lanestyle joined; 18 of the 542 start from another road lane end,
at nearly the same distance). `_join_footways` is deleted. The multi-mode reader (`gmns._keep_joins`) keeps a later mode's connector when both its lanes are kept, and gives it the footway's class, use, level and link (the road lane belongs to the earlier mode). A GMNS file made before this has no footway joins.
