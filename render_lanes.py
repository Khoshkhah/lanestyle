#!/usr/bin/env python3
"""Render a duckOSM GMNS db as a lane-level map.

Usage:
    python render_lanes.py GMNS_DB OUT.html [--source-db DB] [--mode driving]

  GMNS_DB      a duckOSM GMNS db (built with `duckosm gmns`).
  OUT.html     the map; a serve.py is written next to it.
  --source-db  optional, the duckOSM db the GMNS db was made from: the area's boundary (dashed
               outline) when it was built with one, `osm_id`, and the levels of GMNS files made
               before duckOSM wrote bridge / tunnel / layer into `link`.
  --boundary   a GeoJSON file to outline instead.
"""
import argparse

import lanestyle as ls

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("gmns_db")
p.add_argument("out")
p.add_argument("--source-db")
p.add_argument("--mode", default="driving")
p.add_argument("--boundary")
a = p.parse_args()

lanes, turns = ls.from_gmns(a.gmns_db, mode=a.mode, source_db=a.source_db)
if a.boundary:
    boundary = ls.boundary_from_geojson(a.boundary)
else:
    boundary = ls.read_boundary(a.source_db) if a.source_db else None
ls.render_lanes(lanes, turns=turns, boundary=boundary).save(a.out)
serve = ls.write_serve(a.out)
print(f"wrote {a.out}: {len(lanes)} lanes, {len(turns)} turns")
print(f"serve it:  python {serve} 8080")
