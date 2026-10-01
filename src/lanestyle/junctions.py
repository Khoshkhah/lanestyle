"""Fillets: the paved gaps between lane surfaces. Where a lane joins a road, or two carriageways
start to diverge, a sliver between the surfaces shows the background. A real road paves it. The
whole lane surface is closed (grown by ``fillet_m``, shrunk back) and what the closing adds is drawn
under the lanes, in the colour of the nearest lane."""
import math

from lanestyle.lines import _band

_CLASS_ORDER = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
                "living_street", "service"]


def _rank(cls):
    c = str(cls or "").replace("_link", "")
    return _CLASS_ORDER.index(c) if c in _CLASS_ORDER else len(_CLASS_ORDER)


def junction_fillets(lanes, s):
    """GeoJSON polygons (``cls``: the road class whose colour to use, ``b``: the band) of the gaps
    narrower than ``2 × fillet_m`` anywhere between lane surfaces (lanes and connectors): the whole
    surface is closed (grown by ``fillet_m``, shrunk back) and what the closing adds is drawn under
    the lanes, in the colour and band of the nearest lane. Corners at junctions, the slivers between
    two carriageways that start to diverge, the notches between adjacent lanes' round ends. Real
    medians wider than ``2 × fillet_m`` stay open. None when off."""
    import shapely

    r_m = float(s.get("fillet_m") or 0)
    if not r_m or not len(lanes):
        return None
    g = lanes.to_crs(lanes.estimate_utm_crs())
    surf = g.geometry.buffer(g["width_m"] / 2, cap_style="round")
    u = shapely.union_all(surf.to_numpy())
    add = shapely.make_valid(u.buffer(r_m).buffer(-r_m).difference(u)).simplify(0.05)
    parts = [q for p in getattr(add, "geoms", [add]) for q in getattr(shapely.make_valid(p), "geoms", [shapely.make_valid(p)])
             if q.geom_type == "Polygon" and q.area > 0.3 and not q.buffer(-0.12).is_empty and q.is_valid]
    if not parts:
        return None
    tree = shapely.STRtree(g.geometry.to_numpy())
    cls = list(g["highway"]) if "highway" in g else [None] * len(g)
    band = [_band(r) for r in g.itertuples(index=False)]
    import geopandas as gpd

    geo = gpd.GeoSeries(parts, crs=g.crs).to_crs(4326)
    rnd = lambda ring: [[round(x, 7), round(y, 7)] for x, y in ring]  # noqa: E731
    feats = []
    for part, gm in zip(parts, geo, strict=True):
        k = int(tree.nearest(part.representative_point()))
        feats.append({"type": "Feature", "properties": {"cls": cls[k], "b": band[k]},
                      "geometry": {"type": "Polygon", "coordinates": [rnd(gm.exterior.coords)] + [rnd(i.coords) for i in gm.interiors]}})
    return {"type": "FeatureCollection", "features": feats}
