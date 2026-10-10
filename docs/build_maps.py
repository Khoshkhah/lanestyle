"""The live map of the docs (docs/maps/monaco.html), built here from the Monaco files and committed: the
docs workflow cannot make them (the GMNS export needs SUMO, the level area holds the fixes made in the editor).

    python docs/build_maps.py AREA GMNS_DB SOURCE_DB      # writes docs/maps/monaco.html

No key goes into the committed page: CARTO and Google keys are removed from the environment first, and
the base map is blank, with no Roads box and no Tunnels slider: just the lanes.
"""
import os
import sys
from pathlib import Path

for k in [k for k in os.environ if "CARTO" in k or "GOOGLE" in k]:
    del os.environ[k]

import lanestyle as ls  # noqa: E402  after the keys are gone

area, gmns, source_db = sys.argv[1:4]
out = Path(__file__).resolve().parent / "maps" / "monaco.html"
out.parent.mkdir(exist_ok=True)
ls.lane_page(area, gmns, source_db, name="lanestyle — Monaco").save(out)
html = out.read_text()
assert "AIza" not in html and "carto_api_key" not in html.lower(), "a key went into the page"
print("wrote", out, f"{out.stat().st_size / 1e6:.1f} MB")
