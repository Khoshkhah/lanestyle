"""The GMNS reader: a duckOSM GMNS database to the lane table and the turns. The Rust engine reads the files; this module makes the
tables (pandas, GeoPandas)."""
import json

from lanestyle._rust_call import rust

_IDS = ("link_id", "reverse_link_id", "from_node_id", "to_node_id", "osm_id", "along_link_id")


def _frame(t):
    import pandas as pd

    return pd.DataFrame(t["rows"], columns=t["columns"], dtype=object)


def _lanes(t):
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import shape

    df = _frame(t)
    for c in df.columns:
        if c in ("geometry", "full_geometry", "cut_geometry"):
            df[c] = [shape(g) if g is not None else None for g in df[c]]
        elif c in _IDS:
            df[c] = df[c].astype("Int64")                       # BIGINT hash ids: never float64
        elif c in ("roundabout", "connector"):
            df[c] = df[c].astype(bool)
        elif c in ("width_m", "lane_num", "lanes"):
            df[c] = pd.to_numeric(df[c])
    geom = df.pop("geometry")
    return gpd.GeoDataFrame(df, geometry=gpd.GeoSeries(geom, crs=4326, index=df.index), crs=4326)


def _crossings(rows):
    import pandas as pd

    cols = ["crossing_id", "lane_id", "start_lr", "end_lr", "across_from", "across_to", "to_left", "painted", "length", "crossing_type",
            "source", "cgeom"]
    return None if rows is None else pd.DataFrame(rows, columns=cols)


def from_gmns(gmns_db, mode="driving", source_db=None, modes=None):
    """``gmns_<mode>`` of a duckOSM GMNS file as ``(lanes, turns)``: a GeoDataFrame of one row per lane (EPSG:4326, each line in the
    direction of travel; with duckOSM's lane connectors, one row per connector too) and a DataFrame of the lane-to-lane turns. The
    crossings are in ``lanes.attrs["crossings"]`` (see :func:`read_crossings`). ``source_db``: the duckOSM file the GMNS file was made
    from (the levels, the OSM ways, the roundabouts). ``modes`` reads several modes into one table (e.g. ``("driving", "walking")``):
    each later one adds only the links the earlier ones do not have; a ``modes`` column says which modes have each link."""
    out = json.loads(rust().from_gmns(str(gmns_db), mode, str(source_db) if source_db else None, list(modes) if modes else None))
    lanes, turns = _lanes(out["lanes"]), _frame(out["turns"])
    if "walkers" in turns:
        turns["walkers"] = turns["walkers"].astype(bool)
    lanes.attrs["crossings"] = _crossings(out["crossings"])
    lanes.attrs["source_db"] = str(source_db) if source_db else None
    return lanes, turns


def read_crossings(gmns_db):
    """duckOSM's ``gmns_driving.crossing`` / ``lane_crossing`` as one table, a row per crossing per lane it covers (``crossing_id``,
    ``lane_id``, ``start_lr``, ``end_lr``, ``across_from``, ``across_to``, ``to_left``, ``painted``, ``length``, ``crossing_type``,
    ``source``, ``cgeom``: the crossing's rectangle, lon/lat WKT); None where the file has none."""
    return _crossings(json.loads(rust().read_crossings(str(gmns_db))))


def read_boundary(db):
    """The area's boundary from a duckOSM database (``main.boundary``) as a shapely geometry, or None."""
    from shapely import wkb

    b = rust().read_boundary(str(db))
    return wkb.loads(bytes(b)) if b is not None else None


def boundary_from_geojson(path):
    """A GeoJSON file's geometries as one shapely geometry (plain json + shapely, no GDAL)."""
    import shapely
    from shapely.geometry import shape

    gj = json.loads(open(path, encoding="utf-8").read())
    feats = gj.get("features", [gj] if gj.get("type") == "Feature" else [{"geometry": gj}])
    return shapely.union_all([shape(f["geometry"]) for f in feats if f.get("geometry")])
