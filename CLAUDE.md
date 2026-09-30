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
- `src/lanestyle/data/lanestyle.json`: lanestyle's defaults (colours, `default_width_m`, `casing_m`,
  `width_m_zoom`). `lane_settings()` merges them with a `lanestyle.json` in the current folder, then
  with `settings["lanes"]`.

## Constraints (agreed with Kaveh)

- **roadstyle changes only once:** the metre-width option (`width_m_col`, `width_m_zoom`, `casing_m`),
  for release 0.10.0. Until then it lives on roadstyle branch `metre-width`, in the worktree
  `../roadstyle-metre-width`. Lane logic stays in lanestyle; ask before any other roadstyle change.
- Don't change duckOSM (its `gmns-map` stays) until lanestyle is built and tested.
- Before lanestyle goes public on GitHub, the Gmail address must be removed from the commit history.
  Ask whether to start a fresh history or rewrite the existing commits.
- Non-trivial features: write a design note in `docs/design/` and get Kaveh's OK before coding.
- Previews go in `renders/<topic>/` (gitignored), with an `index.html` and a running `serve.py`.
  Give Kaveh the `http://localhost:<port>/` URL, and let him see things before anything is pushed.

## Commands

roadstyle 0.10 isn't released yet, and the `roadstyle` conda env's editable install points at the
`main` checkout. So put the branch worktree on the path:

```bash
PY="env PYTHONPATH=src:../roadstyle-metre-width/src $HOME/miniconda3/envs/roadstyle/bin/python"
$PY -m pytest -q tests                                                     # all tests
$PY -m pytest -q tests/test_lanestyle.py::test_from_gmns_lane_table_and_turns
$PY render_lanes.py data/monaco_gmns.duckdb out.html --source-db data/monaco.duckdb
$PY renders/lanes/build.py      # Monaco / Södermalm / Tartu test maps -> renders/lanes/
```

The tests build a tiny GMNS db and source db in `tmp_path`, so they need no real data. Test data
lives in `data/` (gitignored): `monaco.duckdb` and `<area>_gmns.duckdb`, rebuilt with
`duckosm gmns <db> -m driving -o data/<area>_gmns.duckdb`. The July GMNS files in
`../duckOSM/data/db/` don't match today's duckOSM dbs (0 shared ids), so don't pair those with
`source_db`.

## Gotchas

- `link_id` is duckOSM's BIGINT hash: keep it `Int64` (never float64). roadstyle turns large ints
  into strings in the page.
- In the page, roadstyle feature ids are indexes into its source, not `lane_id`s. The click script
  maps `lane_id` → id on the first click.
- Without `select_color`, roadstyle's violet selection glow hides the red clicked lane. That's why
  `render_lanes` passes the `clicked` colour.
