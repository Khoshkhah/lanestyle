#!/usr/bin/env python3
"""Render a duckOSM GMNS db as a lane-level map (optionally with a lane route overlay).

Usage:
    python render_lanes.py [gmns_db.duckdb] [out.html] [route.geojson]

  gmns_db      a duckOSM GMNS db (built with `duckosm gmns`); default: Södermalm.
  out.html     output map; default: lanes.html
  route.geojson  optional lane route from `duckosm route-lanes <db> <from> <to> -o route.geojson`.
"""
import sys

from lanestyle import render_lane_map

DB = sys.argv[1] if len(sys.argv) > 1 else "../duckOSM/data/db/sodermalm_pbf_gmns.duckdb"
OUT = sys.argv[2] if len(sys.argv) > 2 else "lanes.html"
ROUTE = sys.argv[3] if len(sys.argv) > 3 else None

render_lane_map(DB, OUT, route_geojson=ROUTE)
print(f"wrote {OUT}" + (f" (with route {ROUTE})" if ROUTE else ""))
