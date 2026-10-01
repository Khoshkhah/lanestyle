"""The live map embedded in the docs (docs/maps/monaco.html), from the bundled Monaco sample.

Run from the repo root::

    python docs/build_maps.py        # writes docs/maps/monaco.html

It is not committed: the docs workflow (.github/workflows/docs.yml) builds it before ``mkdocs build``.
With ``CARTO_API_KEY`` set (the repo secret) the base map is CARTO's Voyager; without it, Esri's
keyless street map.
"""
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

import lanestyle as ls

DOCS = Path(__file__).resolve().parent
OUT = DOCS / "maps"
OUT.mkdir(exist_ok=True)

lanes = gpd.read_parquet(DOCS / "data" / "monaco_lanes.parquet")
turns = pd.read_parquet(DOCS / "data" / "monaco_turns.parquet")
boundary = ls.boundary_from_geojson(DOCS / "data" / "monaco_boundary.geojson")
basemap = "voyager" if os.environ.get("CARTO_API_KEY") else "esri_street"
ls.render_lanes(lanes, turns=turns, boundary=boundary, basemap=basemap, name="lanestyle — Monaco").save(OUT / "monaco.html")
print("wrote", OUT / "monaco.html", f"{(OUT / 'monaco.html').stat().st_size / 1e6:.1f} MB")
