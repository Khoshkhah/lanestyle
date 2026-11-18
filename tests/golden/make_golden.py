"""Make the golden files of the Rust port from the Python lanestyle (commit 38995c1, before the port). Run it once; never edit its output.

    PYTHONPATH=src python tests/golden/make_golden.py DIR AREA [AREA ...]

DIR holds AREA.duckdb, AREA_gmns.duckdb and AREA_roads.parquet (the level editor's road table of AREA.levels, made by
`cargo run -p lanestyle --example area_roads`). For each area it writes into DIR:

- AREA_lanes.json: from_gmns (the lane table, its columns, and the turns);
- AREA_strokes.json and AREA_strokes_connectors.json: editor._strokes (every item, the widths, the lines, the special lanes);
- AREA_items.json: editor.lane_items on AREA_roads.parquet (the render keywords and the roads' new width_m and lines).
"""
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

import lanestyle as ls
from lanestyle import editor


def plain(v):
    """A value as JSON: NaN and NA as null, numpy scalars as Python ones, a geometry as its GeoJSON."""
    if v is None or v is pd.NA or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "geom_type"):
        return v.__geo_interface__
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [plain(x) for x in v]
    if hasattr(v, "tolist"):
        return plain(v.tolist())
    if hasattr(v, "item"):
        return plain(v.item())
    return v


def table(df):
    return {"columns": list(df.columns), "rows": [[plain(x) for x in r] for r in df.itertuples(index=False)]}


def dump(path, obj):
    path.write_text(json.dumps(obj, allow_nan=False))
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)", flush=True)


def main(d, areas):
    d = Path(d)
    for a in areas:
        gmns, src = str(d / f"{a}_gmns.duckdb"), str(d / f"{a}.duckdb")
        lanes, turns = ls.from_gmns(gmns, source_db=src)
        dump(d / f"{a}_lanes.json", {"lanes": table(lanes.drop(columns="geometry").assign(geometry=lanes.geometry)), "turns": table(turns)})
        for conn in (False, True):
            editor._strokes.cache_clear()
            names = ("lanes", "lines", "marks", "width", "lines_of", "connectors", "zebras", "sidewalks", "special")
            out = dict(zip(names, editor._strokes(gmns, src, conn), strict=True))
            out["special"] = sorted(out["special"])
            dump(d / f"{a}_strokes{'_connectors' if conn else ''}.json", plain(out))
        roads = gpd.read_parquet(d / f"{a}_roads.parquet")
        editor._strokes.cache_clear()
        items, kw = editor.lane_items(roads, gmns=gmns, source_db=src, connectors=False)
        dump(d / f"{a}_items.json", plain({"items": items, "kw": kw, "edge": list(roads["edge"].astype(str)), "width_m": list(roads["width_m"]),
                                           "geometry": list(roads.geometry)}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
