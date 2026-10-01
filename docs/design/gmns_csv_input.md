# GMNS CSV input

**Status:** PARKED 2026-10-01 (Kaveh). Not needed for duckOSM files; [`link_osm`](gmns_link_osm.md) removes the second input file instead. Revisit for GMNS from other tools. Nothing is built.

## Problem

`from_gmns()` reads one thing: a duckOSM DuckDB file with `gmns_<mode>.lane`, `.link`, `.movement`
and a lane geometry that duckOSM has already placed. Users with plain GMNS (osm2gmns output, a
planning model, any tool that writes `node.csv` / `link.csv`) cannot draw their network without
installing duckOSM and its OSM data.

## What standard GMNS gives us

| File | Needed | Used columns |
|---|---|---|
| `link.csv` | yes | `link_id`, `from_node_id`, `to_node_id`, `geometry` (WKT), `lanes`, `facility_type` |
| `node.csv` | only if a link has no `geometry` | `node_id`, `x_coord`, `y_coord` |
| `lane.csv` | no | `link_id`, `lane_num`, `width`, `allowed_uses` |
| `movement.csv` | no | `ib_link_id`, `ob_link_id`, `start_ib_lane`..`end_ob_lane`, `type` |

There is **no lane geometry**: lanes are a count (and, optionally, a width) per link. So the reader
has to place the lanes itself. That is the whole feature.

## Proposal

```python
lanes, turns = from_gmns_csv("path/to/gmns_folder", drive_on="right")
render_lanes(lanes, turns)           # unchanged: same table as from_gmns()
```

Same return contract as `from_gmns()` (design note on roadstyle, section 2), so `render_lanes`,
`lane_lines` and the click script need no change. The CLI gets the same input: `render_lanes.py`
takes a folder instead of a `.duckdb` file.

### Placement rule (deliberately simple)

1. Take each link's centre line (`geometry`, else the node-to-node straight line).
2. A link is **two-way** if another link has the same nodes swapped and the same geometry reversed
   (`reverse_link_id`, found the way `from_gmns` finds it). Its lanes then sit on the right of the
   centre line (left of it for `drive_on="left"`), lane 1 next to the centre line. A **one-way** link
   is centred: its lanes are spread equally to both sides.
3. Lane *k* of *n*: its centre line is the link's centre line offset by the widths of lanes
   1..k-1 plus half of its own width. Width = `lane.width`, else `default_width_m`.
4. Offsets are done in metres (local UTM from `estimate_utm_crs`), and the result goes back to
   EPSG:4326. `offset_curve` with a mitre join, as `lines.py` does.
5. `highway` = `facility_type`; `use` and `width_m` from `lane.csv` if present; `lanes` = the link's
   count; `from_node_id`, `to_node_id`, `reverse_link_id` as in `from_gmns`.
6. Levels: `bridge` / `tunnel` / `layer` from `link.csv` if it has those columns, else ground level.
   (They are not GMNS standard; osm2gmns does not write them.)
7. `turns` from `movement.csv`, reusing `from_gmns`'s range-pairing code (moved into one shared
   function, not copied).

### Not included (ceilings, said in the docs)

- No duckOSM **runs** or **connectors**: lanes are placed per link, so at bends and junctions the
  lanes of neighbouring links meet with jogs, gaps or overlaps. The map is a good picture of a
  network, not duckOSM-quality junctions.
- No cut-back of lanes at junctions beyond what `lane_lines` already does.
- A dual carriageway mapped as two *separate* links is not placed as one road (duckOSM's
  paired carriageways); each is a one-way link, centred on its own line, so they overlap where they
  are closer than their lanes need.
- No `lane_connector` rows.

## Alternatives considered

- **Call duckOSM from lanestyle.** Rejected: duckOSM needs the OSM data, which GMNS CSV does not have.
- **Write the placement in roadstyle.** Rejected: roadstyle changes only once.
- **Port duckOSM's run / connector placement.** Too large for a first version; revisit if the simple
  rule is not good enough for users.

## Plan

1. `src/lanestyle/gmns_csv.py`: `from_gmns_csv`, plus the shared turn builder (moved out of `gmns.py`).
2. Tests in `tests/`: a tiny CSV folder in `tmp_path` (one two-way link, one one-way link, one
   movement): lane count, offsets in metres (3.5 m lane 2 centre is 5.25 m from the centre line), lane 1 beside the
   centre line, `drive_on="left"` mirrors, no `geometry` falls back to nodes, `link_id` stays Int64.
3. Monaco check (Monaco only): export `data/monaco_gmns.duckdb` to CSV (`COPY ... TO`) and compare the
   lanes placed here with duckOSM's: the share of lanes within 1 m of the duckOSM lane, and the
   count of opposite-direction overlaps. Preview in `renders/gmns-csv/` on :8090 for Kaveh before any push.
4. `render_lanes.py`: accept a folder; `docs/get-started.md` and the skill get a short section; README
   one line.

## Questions for Kaveh

1. Is "simple per-link placement, with the junction ceiling stated" acceptable for a first version?
2. Should the CSV reader live in the same package (`from lanestyle import from_gmns_csv`) or a
   separate module name only? (Proposed: same package, new module.)
