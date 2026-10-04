"""Street names in lanestyle's own layer (docs/design/street_names.md): each road's name along the middle of the road, cut clear of the painted arrows."""
from __future__ import annotations


def street_names(lanes, arrows, s, avoid=None):
    """The names as a GeoJSON FeatureCollection of lon/lat lines (properties ``name`` and ``edge_id``, the link it is drawn along), or None. ``arrows``: :func:`lanestyle.arrows.lane_arrows`' output
    (or None); ``s``: ``lanes.names``; ``avoid``: a lon/lat geometry to keep clear of too (the zebra crossings). A two-way road is labelled once, on lane 1's left edge (the centre line), by the smaller of its two links;
    a one-way link along the middle of its lanes. Each line loses the stretches within ``clear_m`` of an arrow or in ``avoid``."""
    import geopandas as gpd
    import pandas as pd
    import shapely

    if not s or "name" not in lanes or "link_id" not in lanes or "lane_num" not in lanes:
        return None
    g = lanes[~lanes["connector"].fillna(False).astype(bool)] if "connector" in lanes else lanes
    g = g[(g["use"] != "walk") & g["name"].notna()]
    if not len(g):
        return None
    u = g.estimate_utm_crs()
    g = g.to_crs(u)
    keep = []                                   # the shapes a name keeps clear of, one by one: a line is cut only against the ones near it (one merged shape made every cut slow)
    if arrows and arrows["features"]:
        a = gpd.GeoDataFrame.from_features(arrows["features"], crs=4326).to_crs(u)
        keep += [q.buffer(float(s["clear_m"])) for q in a.geometry]
    if avoid is not None:
        z = gpd.GeoSeries([avoid], crs=4326).to_crs(u).iloc[0]
        keep += list(getattr(z, "geoms", [z]))
    tree = shapely.STRtree(keep) if keep else None
    two_way = "reverse_link_id" in g
    lines, names = [], []
    for lk, grp in g.groupby("link_id"):
        first = grp.sort_values("lane_num").iloc[0]
        if first.geometry is None or first.geometry.geom_type != "LineString":
            continue
        rev = first["reverse_link_id"] if two_way else None
        if rev is not None and not pd.isna(rev):                       # two-way: the centre line, drawn once
            if str(rev) < str(lk):
                continue
            off = first["width_m"] / 2
        else:                                                    # one-way: the middle of the link's lanes
            off = -(grp["width_m"].sum() / 2 - first["width_m"] / 2)
        line = first.geometry.offset_curve(off) if off else first.geometry
        if tree is not None:
            near = tree.query(line)
            if len(near):
                line = line.difference(shapely.union_all([keep[i] for i in near]))
        for p in getattr(line, "geoms", [line]):
            if p.geom_type == "LineString" and p.length > 3:
                lines.append(p)
                names.append((first["name"], int(lk)))
    if not lines:
        return None
    ll = gpd.GeoSeries(lines, crs=u).to_crs(4326)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": n, "edge_id": lk},
         "geometry": {"type": "LineString", "coordinates": [[round(x, 7), round(y, 7)] for x, y in p.coords]}} for p, (n, lk) in zip(ll, names)]}
