# AGENTS.md

Rules for AI coding agents (Claude Code, Codex, Cursor, Copilot, Gemini, …) working on this
repository. To *use* lanestyle rather than change it, read the agent skill
[`skills/lanestyle/SKILL.md`](skills/lanestyle/SKILL.md).

## What this is (rebuilt 2026-10-10)

lanestyle draws lane-level maps on **roadstyle** (`../roadstyle`) and **draws nothing of its own**.
roadstyle draws every road: one line as wide as its lanes, with its outline, ends, levels (bridges
over, tunnels under), names, hover and click, exactly as roadstyle's **level editor** draws it.
lanestyle reads duckOSM's GMNS lanes and adds them to the roads as **items** (`render_edges(items=)`):
lanes, lane lines, arrows, BUS and bike marks, zebras, sidewalks. The lane page and the editor share
one function, `editor.lane_items`, so they always draw the same.

The chain: `.osm.pbf` → `duckosm build` → `duckosm gmns` (lanes and turns from SUMO) → `duckosm levels`
(the level area, `<db>.levels`, where the drawing order and your edits live) → `lanestyle.lane_page`.

## Layout

- `src/lanestyle/page.py`: `lane_page(area, gmns, source_db, connectors=False, **kw)`: the level
  area's roads as the editor draws them (`roadstyle.level_editor.Area(area).draw`), the items of
  `lane_items`, one `rs.render_edges` call; `kw` go to it.
- `src/lanestyle/editor.py`: `lane_items(roads, gmns, source_db)`, the editor's hook
  (`roadstyle-levels edit AREA --items lanestyle.editor:lane_items`, files from `LANESTYLE_GMNS` /
  `LANESTYLE_SOURCE_DB` there): each road one line at its lanes' full width (`width_m`, its line the
  middle of its carriageway), the items, and the render keywords. `_strokes` builds everything once
  (cached): `to_junctions` cuts each lane where SUMO's junction begins (plain junctions).
- `src/lanestyle/items.py`: `link_roads` (one road per carriageway: a link and its `reverse_link_id`),
  and the items as LINE strokes: `lane_strokes` (lanes and the lines between them), `connector_strokes`,
  `zebra_strokes` (painted crossings' stripes, `minzoom`), `sidewalk_strokes` (the sidewalks OSM tags
  on a street). Item order: connector -1, lane 0, lines 1, zebra 2, arrows 3.
- `src/lanestyle/arrows.py`: `mark_strokes`, the painted marks (turn arrows, BUS, bike) as strokes
  (`docs/design/lane_arrows.md`); `src/lanestyle/strokes.py`: their shapes and the metre dashes.
- `src/lanestyle/gmns.py`: `from_gmns` reads `gmns_<mode>.lane` / `.link` / `.movement` into
  `(lanes, turns)`; `read_crossings`, `read_boundary`.
- `src/lanestyle/settings.py`: `lane_settings()` (`data/lanestyle.json`, then a local
  `lanestyle.json`, then `settings["lanes"]`), the colour rule (`_colour_groups`: a lane by its use; a
  road cars do not use by who uses it) and the widths (`_widths`). `levels.py`: `tags_band`.

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
PY="env PYTHONPATH=src:../roadstyle/src $HOME/miniconda3/envs/roadstyle/bin/python"
$PY -m pytest -q tests
$PY lane_page.py MONACO.levels MONACO_GMNS.duckdb MONACO.duckdb out.html
```

The tests build a tiny GMNS db, source db and level area in `tmp_path`, so they need no real data.

## Gotchas

- `link_id` is duckOSM's BIGINT hash: keep it `Int64`, never float64. roadstyle turns large ints into
  strings in the page; the page's feature ids are roadstyle's, never `link_id`.
- Lane 1 is the leftmost lane in the direction of travel. The centre line sits at lane 1's left edge:
  right for right-hand traffic only.
