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
- `src/lanestyle/render.py`: the engine.
  - `render_lanes(lanes, turns, palette="mono", settings, **kw)` calls `roadstyle.render_edges` with
    `width_m_col="width_m"`. It adds a "Lane use" `color_options` entry for bus, bike and walk lanes, and defaults a null width by use
    (`_widths`: `width_m_by_use`).
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

roadstyle 0.11.0 (released 2026-09-30) has the metre widths. The `roadstyle` conda env has an
editable install of the `main` checkout (`../roadstyle`, at or ahead of the release), so only
lanestyle itself needs to be on the path:

```bash
PY="env PYTHONPATH=src $HOME/miniconda3/envs/roadstyle/bin/python"
$PY -m pytest -q tests                                                     # all tests
$PY -m pytest -q tests/test_lanestyle.py::test_from_gmns_lane_table_and_turns
$PY render_lanes.py data/monaco_gmns.duckdb out.html --source-db data/monaco.duckdb
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
lives in `data/` (gitignored): `monaco.duckdb` and `monaco_gmns.duckdb`, rebuilt with
`duckosm gmns data/monaco.duckdb -m driving -o data/monaco_gmns.duckdb`.

## Gotchas

- `link_id` is duckOSM's BIGINT hash: keep it `Int64` (never float64). roadstyle turns large ints
  into strings in the page.
- In the page, roadstyle feature ids are indexes into its source, not `lane_id`s. The click script
  maps `lane_id` → id on the first click.
- Lane 1 is the leftmost lane in the direction of travel, on either side (duckOSM fixed `--drive-side left`
  on 2026-10-01: before, left-hand two-way roads counted from the centre line). `lines.py` still draws a
  two-way road's centre line at lane 1's left edge: right for right-hand traffic only, so left-hand maps
  need that changed (`ponytail:` note in `lines.py`).
- Tunnels and bridges follow roadstyle's **levels and looks** (roadstyle `docs/design/levels_and_looks.md`): the level
  alone decides the band (low, ground, high), a tunnel is a lane of the low band with the tunnel look (two-tone casing, light
  dashes, faded fill), a bridge of the high band with the deck look. lanestyle only tunes the look (`_ROADSTYLE`) and
  mirrors the band for its own layers (`lines._band`: low / ground / high / bridge). Needs the roadstyle with that
  change (the `levels-and-looks` branch, not yet released).
- Without `select_color`, roadstyle's violet selection glow hides the red clicked lane. That's why
  `render_lanes` passes the `clicked` colour.
