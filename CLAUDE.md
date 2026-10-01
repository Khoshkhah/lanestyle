# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

lanestyle draws lane-level maps on **roadstyle** (`../roadstyle`): each lane is one roadstyle line on
its own geometry, exactly its width in metres from zoom 16 on. roadstyle brings levels (bridges,
tunnels, `layer`), base maps, popups, arrows and the `rs*` JavaScript API. The design, with its
status and next steps, is in `docs/design/lanestyle_on_roadstyle.md`. **Read it before changing
anything.** `docs/pipeline.md` walks the whole chain: `.osm.pbf` → duckOSM → GMNS → lanestyle.

## Layout

- `src/lanestyle/gmns.py`: the reader. `from_gmns(gmns_db, mode, source_db)` reads
  `gmns_<mode>.lane` / `.link` / `.movement` into `(lanes, turns)`. Levels come from the GMNS `link`
  if it has `bridge` / `tunnel` / `layer`, else from `source_db` (the duckOSM db:
  `link_id` = `<mode>.edges.edge_id`). A NULL lane range in `movement` means every lane.
- `src/lanestyle/render.py`: the engine.
  - `render_lanes(lanes, turns, palette="mono", settings, **kw)` calls `roadstyle.render_edges` with
    `width_m_col="width_m"`. It adds a "Lane use" `color_options` entry for bus and bike lanes.
  - It appends a click script (`_CLICK_JS`, using `rsQuery` / `rsGetProps` / `rsColor`) and returns
    roadstyle's `WebMap`. Extra keywords go straight to `render_edges`.
  - `write_serve` writes a `serve.py` next to a page.
- `src/lanestyle/lines.py`: the lane lines (step 2b). `lane_lines(lanes, settings)` offsets each
  lane's centre line by half its width. It returns dividers, centre lines (drawn once, by the smaller
  of the link and its `reverse_link_id`, or of two one-way links whose lane 1 left edges lie on each
  other, `_paired`) and edges, with roadstyle's band mirrored in `_band`. Lines
  are cut at junctions by the other links' lane surfaces. `render.py` ships them as compact columns
  (`_compact`), and `_LINES_JS` adds one MapLibre layer per band and type after that band's fill.
  The lanes themselves have no casing (`casing_m` 0).
- `src/lanestyle/data/lanestyle.json`: lanestyle's defaults (colours, `default_width_m`, `casing_m`,
  `width_m_zoom`, `lines`, `junction_trim_m`). `lane_settings()` merges them with a `lanestyle.json` in the current folder, then
  with `settings["lanes"]`.

## Constraints (agreed with Kaveh)

- **roadstyle changes only once:** the metre-width option (`width_m_col`, `width_m_zoom`, `casing_m`),
  released as roadstyle 0.11.0 (PR #20). Lane logic stays in lanestyle; ask before any other
  roadstyle change.
- Don't change duckOSM (its `gmns-map` stays) until lanestyle is built and tested. One exception
  (Kaveh, 2026-09-30): duckOSM branch `paired-carriageways` places a road mapped as two one-way ways
  as one road (`docs/design/gmns_paired_carriageways.md` there). Lane-overlap reports are about our
  placement, not OSM data.
- Work on **Monaco only** (Kaveh, 2026-09-30): build, check and count there; no other areas.
- The repo is public (since 2026-09-30); commits use the GitHub noreply address (repo-local
  `user.email`), never the personal Gmail.
- Non-trivial features: write a design note in `docs/design/` and get Kaveh's OK before coding.
- Previews go in `renders/<topic>/` (gitignored), linked from `renders/index.html`, and served by
  one server, `renders/serve.py` on port 8090 (Kaveh's browser reached 8090 but not 8091). Give him
  `http://localhost:8090/`, and let him see things before anything is pushed.

## Commands

roadstyle 0.11.0 (released 2026-09-30) has the metre widths. The `roadstyle` conda env's editable
install points at the `main` checkout (`../roadstyle`), which may be ahead of the release; the
worktree `../roadstyle-metre-width` is at the release. Put one of them on the path:

```bash
PY="env PYTHONPATH=src:../roadstyle-metre-width/src $HOME/miniconda3/envs/roadstyle/bin/python"
$PY -m pytest -q tests                                                     # all tests
$PY -m pytest -q tests/test_lanestyle.py::test_from_gmns_lane_table_and_turns
$PY render_lanes.py data/monaco_gmns.duckdb out.html --source-db data/monaco.duckdb
$PY renders/lanes/build.py      # the Monaco test map -> renders/lanes/
$PY renders/lanes/check_spot.py monaco LON LAT TAG 19.5 20.5   # screenshots of a reported spot
```

The tests build a tiny GMNS db and source db in `tmp_path`, so they need no real data. Test data
lives in `data/` (gitignored): `monaco.duckdb` and `monaco_gmns.duckdb`, rebuilt with
`duckosm gmns data/monaco.duckdb -m driving -o data/monaco_gmns.duckdb`.

## Gotchas

- `link_id` is duckOSM's BIGINT hash: keep it `Int64` (never float64). roadstyle turns large ints
  into strings in the page.
- In the page, roadstyle feature ids are indexes into its source, not `lane_id`s. The click script
  maps `lane_id` → id on the first click.
- Lane order is right-hand traffic: lane 1 is leftmost, next to the centre line (duckOSM). Left-hand
  areas would need that checked (`ponytail:` note in `lines.py`).
- Without `select_color`, roadstyle's violet selection glow hides the red clicked lane. That's why
  `render_lanes` passes the `clicked` colour.
