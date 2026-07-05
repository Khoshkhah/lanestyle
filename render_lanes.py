#!/usr/bin/env python3
"""Render a duckOSM GMNS db as a lane-level map (optionally with a lane route overlay).

Usage:
    python render_lanes.py [gmns_db.duckdb] [out.html] [route.geojson] [--debug]

  gmns_db      a duckOSM GMNS db (built with `duckosm gmns`); default: Södermalm.
  out.html     output map; default: lanes.html
  route.geojson  optional lane route from `duckosm route-lanes <db> <from> <to> -o route.geojson`.
  --debug      inspectable QA viewer — hover a lane for its use / lane # / edge_id / width + counts.
"""
import sys

from lanestyle import render_lane_debug, render_lane_map

DEBUG = "--debug" in sys.argv
_pos = [a for a in sys.argv[1:] if not a.startswith("--")]
DB = _pos[0] if len(_pos) > 0 else "../duckOSM/data/db/sodermalm_pbf_gmns.duckdb"
OUT = _pos[1] if len(_pos) > 1 else ("lanes_debug.html" if DEBUG else "lanes.html")
ROUTE = _pos[2] if len(_pos) > 2 else None

(render_lane_debug if DEBUG else render_lane_map)(DB, OUT, route_geojson=ROUTE)
print(f"wrote {OUT}" + (" [debug]" if DEBUG else "") + (f" (with route {ROUTE})" if ROUTE else ""))
