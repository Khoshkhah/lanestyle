# AGENTS.md

Rules for AI coding agents (Claude Code, Codex, Cursor, Copilot, Gemini, …) working on this
repository. To *use* lanestyle rather than change it, read the agent skill
[`skills/lanestyle/SKILL.md`](skills/lanestyle/SKILL.md): the install, the lane table, the one
call, the JavaScript API and the traps, in one page.

## What this is

lanestyle draws lane-level maps on **roadstyle** (`../roadstyle`): each lane is one roadstyle line on
its own geometry, exactly its width in metres from zoom 16 on. roadstyle brings levels (bridges,
tunnels, `layer`), base maps, popups, arrows and the `rs*` JavaScript API. The design, with its
status and next steps, is in `docs/design/lanestyle_on_roadstyle.md`. **Read it before changing
anything.** `docs/pipeline.md` walks the whole chain: `.osm.pbf` → duckOSM → GMNS → lanestyle.

## Layout

- `src/lanestyle/gmns.py`: the reader. `from_gmns(gmns_db, mode, source_db, modes=None)` reads
  `gmns_<mode>.lane` / `.link` / `.movement` into `(lanes, turns)`; `modes=("driving", "walking")` reads several into one
  table (later modes add only the links the earlier ones lack: footpaths, not the roads walked on). Levels come from the GMNS `link`
  if it has `bridge` / `tunnel` / `layer`, else from `source_db` (the duckOSM db:
  `link_id` = `<mode>.edges.edge_id`). A NULL lane range in `movement` means every lane.
- `src/lanestyle/levels.py`: roadstyle's four numbers (`casing_start/level/end`, `fill_level`) of each road (a link). `link_levels(roads, source_db)` reads duckOSM's `visualization.edge_levels` when the file has it (`stored_levels`: a stale table or an unknown id is an error saying to run `duckosm levels`), else `rs.compute_levels` on the complete band (`tags_band`). `by_link` gives the numbers of the link of each lane.
- `src/lanestyle/items.py`: `link_roads` (one road row per link: carriageway line, width = lanes + casing both sides) and the items (`lane_items` polygons, `tag`, `stripes`); the order scale: connector -1, lane 0, lines 1, zebra 2, arrows 3, names 4 (`docs/design/lanestyle_on_roadstyle_items.md`).
- `src/lanestyle/render.py`: the engine. `render_lanes(lanes, turns, palette, settings, source_db=None, **kw)` builds the roads, their numbers, the items, and calls `roadstyle.render_edges(roads, road_fill=False, overlays=[rs.Overlay(edge_col="edge_id", order_col="order", color_col=..., style=...)])`: roadstyle draws each road's casing, the items are the fill. The looks are the theme `styles/themes/lanestyle.yaml` (`lane_theme()`), merged into `settings=`. It appends the click script (`_CLICK_JS`, on the overlay `lanes`) and returns roadstyle's `WebMap`; extra keywords go to `render_edges`. `write_serve` writes a `serve.py` next to a page.
- `src/lanestyle/lines.py`: the lane lines. `lane_lines(lanes, s, avoid, frame)` offsets each lane's centre line by half its width and returns dividers and centre lines (a centre line once, by the smaller of the link and its `reverse_link_id`, or of two one-way links, `_paired`), cut at junctions by the other links' lane surfaces; each carries `edge_id`. No edge lines: the road's casing is the outline.
- `src/lanestyle/arrows.py`: painted lane arrows (`lane_arrows(lanes, turns, settings["arrows"])`): one generic arrow per lane from the moves that leave it, as lon/lat polygons in
  metres, an item (order 3) of their lane's road. Fork, merge and end get none (`docs/design/lane_arrows.md`).
- `src/lanestyle/street_names.py`: the street names an item (order 4; roadstyle's own names are off): along each road's centre, cut clear of the
  arrows and zebras (`docs/design/street_names.md`).
- `src/lanestyle/frames.py`: a road and its footpaths as one frame. `frames(lanes, s)` fills the gap between a footpath and the roads
  duckOSM matched it to (`along_link_id` / `along_links`, pieces of the same street included) in a tint of the footpath colour and returns the
  area whose outlines are left out. Drawing only: no geometry moves. The gap has no casing .
- `src/lanestyle/data/lanestyle.json`: lanestyle's defaults (colours, `default_width_m`, `casing_m`,
  `width_m_zoom`, `lines`, `junction_trim_m`). `lane_settings()` merges them with a `lanestyle.json` in the current folder, then
  with `settings["lanes"]`.

## Constraints (agreed with Kaveh)

- **roadstyle changes only once:** the metre-width option (`width_m_col`, `width_m_zoom`, `casing_m`),
  released as roadstyle 0.11.0 (PR #20). Lane logic stays in lanestyle; ask before any other
  roadstyle change.
- duckOSM changes are allowed now, and are where a data problem is fixed (branch `gmns-values`, pushed 2026-10-02): lane counts, widths, movements,
  crossings, a footpath's route along roads (`link_along`). Never patch the data in lanestyle's reader or drawing (Kaveh: "fix it at the root").
- Work on **Monaco only** (Kaveh, 2026-09-30): build, check and count there; no other areas.
- The repo is public (since 2026-09-30); commits use the GitHub noreply address (repo-local
  `user.email`), never the personal Gmail.
- Non-trivial features: write a design note in `docs/design/` and get Kaveh's OK before coding.
- Previews go in `renders/<topic>/` (gitignored), linked from `renders/index.html`, and served by
  one server, `renders/serve.py` on port 8090 (Kaveh's browser reached 8090 but not 8091). Give him
  `http://localhost:8090/`, and let him see things before anything is pushed.

## Commands

roadstyle 0.11.0 (released 2026-09-30) has the metre widths. The `roadstyle` conda env has an
editable install of the `main` checkout (`../roadstyle`, at or ahead of the release), so only
lanestyle itself needs to be on the path:

```bash
PY="env PYTHONPATH=src $HOME/miniconda3/envs/roadstyle/bin/python"
$PY -m pytest -q tests                                                     # all tests
$PY -m pytest -q tests/test_lanestyle.py::test_from_gmns_lane_table_and_turns
$PY render_lanes.py data/monaco_gmns.duckdb out.html --source-db ../duckOSM/monaco.duckdb
$PY renders/lanes/build.py      # the Monaco test map -> renders/lanes/
$PY renders/lanes/check_spot.py monaco LON LAT TAG 19.5 20.5   # screenshots of a reported spot
$PY docs/build_maps.py                                  # the docs' live map (docs/maps/, not committed)
$PY docs/build_images.py http://localhost:8090/lanes/monaco.html   # the docs' pictures (docs/img/*.jpg)
$PY -m mkdocs build --strict                            # the docs site (mkdocs-material), as roadstyle/mapstyle
```

The docs site (`mkdocs.yml`, `docs/`) mirrors roadstyle's and mapstyle's layout and is deployed to
GitHub Pages by `.github/workflows/docs.yml` on pushes to master. `docs/data/` holds Monaco's lanes as
GeoParquet (the no-duckOSM quickstart and the live map's input); rebuild it from `data/` when the
GMNS export changes.

The tests build a tiny GMNS db and source db in `tmp_path`, so they need no real data. Test data
is **duckOSM's own Monaco database**, `../duckOSM/monaco.duckdb` (built there with `duckosm build --config config/sample_monaco.yaml`, then `duckosm levels monaco.duckdb`): it is the
`source_db` of every build, check and map here, and lanestyle never keeps or builds a copy of it (a copy drifts out of step: edge_ids, levels). Only the GMNS files are lanestyle's, in `data/`
(gitignored), made from it: `duckosm gmns ../duckOSM/monaco.duckdb -m driving -o data/monaco_gmns.duckdb` and `... -m driving -m walking -o data/monaco_walk_gmns.duckdb`; rebuild both whenever duckOSM's Monaco is rebuilt.

## Footpaths, levels, connectors (2026-10-02)

Build with `duckosm gmns SRC -m driving -m walking -o OUT`, read with `ls.from_gmns(OUT, modes=("driving", "walking"), source_db=SRC)`. Design notes:
`docs/design/lanestyle_on_roadstyle.md` (every decision of that session, in order) and duckOSM's `docs/design/gmns_crossings.md`,
`gmns_lane_connectors.md`, `gmns_walking_frame.md`.

- **A tunnel differs from ground in colour and pattern only.** Outlines, joints, matching and draw order follow the same rules; the guard test is
  `test_a_tunnel_differs_from_ground_in_look_only`. Layers are levels: `lines._group`
  (`low@-1`, `low@-2`) decides what interacts; each layer is its own position in roadstyle's numbers, so layer -1 lies over -2 by itself.
- **Connectors** take the modes both their lanes share, are drawn under the lanes (order 0, below every other road, in the order roadstyle's solver is given) and are not
  clickable (`connectors_clickable`). A bike lane's connector is blue and 1.5 m wide. Their round ends are roadstyle's line cap (open: flat-ended shapes).
- **A footpath on a road** (60 % of its area on the road of its level) is drawn above it; **a crossing tagged by mistake** (long and off a road, or matched along one) is drawn as a footway.
- **Street View**: `render_lanes(..., street_view=True)` for roadstyle's page, or `street_view_key=KEY` for the map's own toggle (a real panorama needs billing on the Google project).
  Never commit a key; `renders/` is gitignored. Previews live at fixed addresses (`renders/pedestrians/monaco_sv.html`, `map.html`): never make new file names.

## Gotchas

- `link_id` is duckOSM's BIGINT hash: keep it `Int64` (never float64). roadstyle turns large ints
  into strings in the page.
- In the page, roadstyle feature ids are indexes into its source, not `lane_id`s. The click script
  maps `lane_id` → id on the first click.
- Lane 1 is the leftmost lane in the direction of travel, on either side (duckOSM fixed `--drive-side left`
  on 2026-10-01: before, left-hand two-way roads counted from the centre line). `lines.py` still draws a
  two-way road's centre line at lane 1's left edge: right for right-hand traffic only, so left-hand maps
  need that changed (`ponytail:` note in `lines.py`).
- Tunnels and bridges are drawn by roadstyle's **casing and fill numbers** (`docs/design/lanestyle_on_roadstyle_levels.md`): a tunnel lane has the tunnel look (two-tone casing, faded fill) at its own position, below the ground lanes it
  passes under; a bridge is a road like any other (roadstyle is given an empty bridge column), at a higher position. lanestyle only tunes the look (`_ROADSTYLE`); its own layers go by position (`lsAnchor`: `roads-fill-lv<p>`).
- A GMNS file needs duckOSM 0.1.0 or later (`pip install duckosm`; on `main` since commit ae813ac) for the footway joins (`gmns_walking.lane_connector`; lanestyle adds no connector itself), the half-circle U-turns, `link_along`, the continuation movements and the crossing tables; older files still draw, without joins, frames and zebras.
- Without `select_color`, roadstyle's violet selection glow hides the red clicked lane. That's why
  `render_lanes` passes the `clicked` colour.
