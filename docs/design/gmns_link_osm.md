# One file for lanestyle: a `link_osm` table in the GMNS database

**Status:** SUPERSEDED 2026-10-01. duckOSM main (2bfef81) already writes `bridge` / `tunnel` / `layer`
as columns on `link` (the DuckDB output only; `--to-csv` drops them), so no `link_osm` table is built.
lanestyle reads those columns already (order 2 below). What is left: rebuild Monaco with that duckOSM,
check the map against the `--source-db` one, and drop `--source-db` from the docs. `osm_id` is not on
`link`, so the popup loses it without a source db.

## Problem

lanestyle needs two input files from a duckOSM user:

```bash
python render_lanes.py data/monaco_gmns.duckdb out.html --source-db data/monaco.duckdb
```

The GMNS file has the lanes, links and movements. It has **no levels**: the `link` table has no
`bridge`, `tunnel` or `layer`, which roadstyle needs for draw order, bridge decks and tunnels. So
`from_gmns` attaches the duckOSM database the GMNS file was made from and joins
`link_id = <mode>.edges.edge_id`. That is a second file to keep, to find and to pass; if it is the
wrong one (another build) the join silently returns nothing. A GMNS database should be complete
for drawing.

## Proposal

duckOSM's `gmns` export writes one more table into each `gmns_<mode>` schema:

```sql
gmns_driving.link_osm(link_id BIGINT, osm_id BIGINT, bridge BOOLEAN, tunnel BOOLEAN, layer INTEGER)
```

One row per link, copied from `<mode>.edges` (`edge_id` AS `link_id`). The types are the ones
`edges` already has; the final column types are checked against the source when built.

- **Why a table, not columns on `link`:** `link` is the standard GMNS table and stays standard.
  duckOSM already adds non-standard tables beside it (`lane_connector`, `curb_seg`). `--to-csv`
  writes `link_osm.csv` with the others.
- **Why these columns:** they are the ones `from_gmns` reads from `edges` today (`bridge`, `tunnel`,
  `layer`, and `osm_id` for the popup and the paired-carriageway check).

### duckOSM (small)

In `to_gmns` (`src/duckosm/gmns.py`), next to `_build_link`: `_build_link_osm(con, sch, mode)`, one
`CREATE TABLE ... AS SELECT` from `s.<mode>.edges`, no new options. A test: the table has one row per
`link`, same `link_id`s, and `bridge` / `tunnel` / `layer` equal the source `edges`. Docs: one row in
the tables list of `docs/exports/gmns.md`.

### lanestyle (small)

`from_gmns` finds the levels in this order, and the first that exists wins:

1. `link_osm` in the GMNS db (new);
2. `bridge` / `tunnel` / `layer` columns on `link` (as today);
3. `source_db=` (as today, kept for GMNS files made before this change);
4. ground level.

`--source-db` stays but becomes optional and rarely needed; the quickstart, README and the agent
skill drop it. Test: a tiny GMNS db with a `link_osm` table gives the levels without a source db; the
existing test with a source db still passes.

## Not changed

- The meaning of any existing duckOSM table or column: this only adds a table.
- Rebuild order: the table is written in the same run as `link`, so the ids always match; a GMNS
  file made before this change has no `link_osm` and falls back to the source db, as today.
- The GMNS CSV reader ([GMNS CSV input](gmns_csv_input.md)) stays parked: it is for GMNS from other
  tools and is not needed for duckOSM files.

## Plan

1. Kaveh's OK on this note (and on the duckOSM exception).
2. duckOSM: `_build_link_osm`, its test and docs row, on a branch; not pushed until Kaveh says.
3. lanestyle: the reader order above, a test, docs / README / skill drop `--source-db`.
4. Monaco only: rebuild `data/monaco_gmns.duckdb` with the new duckOSM, check that the map is
   identical to the one built with `--source-db` (same levels, same lane count), and give Kaveh the
   preview in `renders/` on :8090 before anything is pushed.
