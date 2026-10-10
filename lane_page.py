#!/usr/bin/env python3
"""Draw the lanes of a duckOSM GMNS db on the roads of its level area: one offline HTML map.

Usage:
    python lane_page.py AREA GMNS_DB SOURCE_DB OUT.html [--connectors]

  AREA         the level area folder (`duckosm levels SOURCE_DB` makes SOURCE_DB.levels; your edits live there)
  GMNS_DB      the GMNS db (`duckosm gmns SOURCE_DB -o GMNS_DB`)
  SOURCE_DB    the duckOSM db both were made from
  OUT.html     the map
  --connectors also the lane connectors through the junctions, unseen (route highlights)
"""
import argparse

import lanestyle as ls

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("area")
p.add_argument("gmns_db")
p.add_argument("source_db")
p.add_argument("out")
p.add_argument("--connectors", action="store_true")
a = p.parse_args()
ls.lane_page(a.area, a.gmns_db, a.source_db, connectors=a.connectors, tunnel_control=True).save(a.out)
print(f"wrote {a.out}")
