# AGENTS.md

Rules for AI coding agents (Claude Code, Codex, Cursor, Copilot, Gemini, …) working on this
repository. To *use* lanestyle rather than change it, read the agent skill
[`skills/lanestyle/SKILL.md`](skills/lanestyle/SKILL.md).

## What this is (rebuilt 2026-10-10)

lanestyle draws lane-level maps on **roadstyle** and **draws nothing of its own**.
roadstyle draws every road: one line as wide as its lanes, with its outline, ends, levels (bridges
over, tunnels under), names, hover and click, exactly as roadstyle's **level editor** draws it.
lanestyle reads duckOSM's GMNS lanes and adds them to the roads as **items** (`render_edges(items=)`):
lanes, lane lines, arrows, BUS and bike marks, zebras, sidewalks. The lane page and the editor share
one function, `editor.lane_items`, so they always draw the same.

The chain: `.osm.pbf` → `duckosm build` → `duckosm gmns` (lanes and turns from SUMO) → `duckosm levels`
(the level area, `<db>.levels`, where the drawing order and your edits live) → `lanestyle.lane_page`.

## Layout (Rust since 0.4.0)

Rust is the design; Python only calls it. The crates are in `rust/`, as roadstyle's are:

- `rust/lanestyle` (the crate `lanestyle`, a Git dependency of duckOSM's Rust):
  - `geo.rs`: the line operations of shapely and GEOS (project, interpolate, substring, the simplify that keeps topology, the
    robust segment test), the UTM zone of geopandas (PROJ's `tmerc`, equal to pyproj to the bit) and PROJ's `aeqd` (geodesics).
  - `lanes.rs`: the lane table (`Lanes`, `Lane`), the turns and the crossings.
  - `gmns.rs` (feature `duckdb`): the reader. `from_gmns`, `read_crossings`, `read_boundary`, the OSM tags of the ways.
  - `items.rs`: `link_roads` (one road for each carriageway), `lane_strokes`, `connector_strokes`, `zebra_strokes`,
    `sidewalk_strokes`. Item order: connector -1, lane 0, lines 1, zebra 2, arrows 3.
  - `arrows.rs`: `mark_strokes` (turn arrows, BUS, bike; `docs/design/lane_arrows.md`). `strokes.rs`: their shapes, `place`, the dashes.
  - `editor.rs`: `strokes` (all the items of a lane table) and `lane_items`, the editor's hook. The lane page and the editor use it.
  - `settings.rs`: `lane_settings` (`data/lanestyle.json`, then a local `lanestyle.json`, then `settings["lanes"]`), the widths.
  - `page.rs` (feature `page`): `area_draw` (the level editor's road table of a level area), `lane_page` (roadstyle's page), `amber`.
  - The rules (no feature) build for WebAssembly.
- `rust/lanestyle-py`: the binding, the module `lanestyle._rust` (PyO3, abi3, maturin).
- `src/lanestyle`: the Python package. It calls `lanestyle._rust` and makes the tables (pandas, GeoPandas). The public API is the
  same as in 0.3: `lane_page`, `from_gmns`, `read_crossings`, `read_boundary`, `boundary_from_geojson`, `lane_settings`,
  `editor.lane_items`.

## The golden files

`tests/golden/make_golden.py` made the golden files from the Python lanestyle 0.3.1 (commit 38995c1, with roadstyle 0.25.0) on
Monaco and Tartu (`data/golden-2026-11-18/`, with their input files and `SHA256SUMS`). `rust/lanestyle/examples/golden.rs` compares
the Rust output with them: coordinates to 1 mm, all other values exactly. Never edit a golden file to pass a test. The Monaco set is
in the pre-release `golden-data` for CI (`.github/workflows/rust.yml`).

## Constraints (agreed with Kaveh)

- Data problems are fixed at the root, in duckOSM (lane counts, widths, movements, crossings), never
  patched in lanestyle. A road's drawing (outline, ends, levels, tunnels, picking) is roadstyle's: fix
  it there, never with a lanestyle rule.
- Work on **Monaco only**: build, check and count there.
- The repo is public: commits use the GitHub noreply address (repo-local `user.email`).
- Non-trivial features: talk the design through with Kaveh, one decision at a time, before coding.
- Never commit a Google Maps or CARTO key, or a page built with one.

## Commands

```bash
PY=$HOME/miniconda3/envs/roadstyle/bin/python
(cd rust && CARGO_BUILD_JOBS=4 cargo test --release -p lanestyle)          # the rules
$PY rust/lanestyle-py/build.py                                               # the extension, next to the package
env PYTHONPATH=src $PY -m pytest -q tests
(cd rust && cargo run --release -p lanestyle --features page --example golden -- ../../data/golden-2026-11-18 monaco tartu)
(cd rust && cargo run --release -p lanestyle --features page --example lane_page -- MONACO.levels MONACO_GMNS.duckdb MONACO.duckdb out.html)
```

The Python tests make a tiny GMNS file, source file and level area in `tmp_path`: they need no real data.

## Gotchas

- `link_id` is duckOSM's BIGINT hash: keep it `Int64`, never float64. roadstyle turns large ints into
  strings in the page; the page's feature ids are roadstyle's, never `link_id`.
- Lane 1 is the leftmost lane in the direction of travel. The centre line sits at lane 1's left edge:
  right for right-hand traffic only.
