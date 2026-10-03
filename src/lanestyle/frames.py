"""A road and its sidewalk as one frame (docs/design/lanestyle_on_roadstyle.md): where a sidewalk lies within ``frame_gap_m`` of the
road it runs along (duckOSM's ``along_link_id``), the gap between them is filled and no outline is drawn between them. Drawing only:
no geometry of the data moves."""
from lanestyle.lines import _band, _group, _level


def frames(lanes, s):
    """``(gaps, inner, edges)``: ``gaps`` a GeoJSON FeatureCollection of the filled gaps (``cls``, ``b`` as the junction fillets, so the page
    draws them with the same layer) and ``inner`` the frames' area (lon/lat polygon) whose outlines are left out; ``(None, None)``
    when off (``frame_gap_m`` 0) or the table has no ``along_link_id``. ``edges``: ``[(band, line)]`` (lon/lat), the gaps' own casing:
    their sides that touch neither the road nor the footpath."""
    import geopandas as gpd
    import pandas as pd
    import shapely
    import shapely.ops

    gap = float(s.get("frame_gap_m") or 0)
    if not gap or "along_link_id" not in lanes or not len(lanes):
        return None, None, []
    g = lanes.to_crs(lanes.estimate_utm_crs())
    surf = g.geometry.buffer(g["width_m"].fillna(2.0) / 2, cap_style="round")
    by_link = {}
    for i, lk in enumerate(g["link_id"]):
        by_link.setdefault(lk, []).append(i)
    street = {}                                      # link -> its name (lane 1 carries it): one street is often several OSM ways
    if "name" in g:
        for lk, nm in zip(g["link_id"], g["name"]):
            if isinstance(nm, str) and nm:
                street[lk] = nm
    band = [_band(r) for r in g.itertuples(index=False)]
    tun = [_level(r) == "low" for r in g.itertuples(index=False)]         # a verge in a tunnel is drawn with the tunnel look (a hatch over a faded fill)
    grp = [_group(r) for r in g.itertuples(index=False)]       # what a lane may be framed with: its level (layer -1 and -2 are two levels, one draw band)
    cls = list(g["highway"]) if "highway" in g else [None] * len(g)
    conn = g["connector"].tolist() if "connector" in g else [False] * len(g)
    casing = bool(s.get("frame_casing"))               # the gap's own edge line: off (it drew stray arcs, Kaveh 2026-10-02)
    reach = float(s.get("frame_reach_m") or 8.0)     # the widest gap that is filled: beyond it a footpath only runs near the road
    def tint(c):                                     # a verge: the footpath's colour, lighter
        h = c.lstrip("#")
        return "#" + "".join(f"{round(int(h[k:k + 2], 16) * 0.45 + 255 * 0.55):02x}" for k in (0, 2, 4))
    cols = s.get("colors") or {}
    paints = {"sidewalk": tint(cols.get("sidewalk") or "#e6b9a6"), "adjacent": tint(cols.get("walk") or "#f0cb8a")}
    ref = list(g["edge_ref"]) if "edge_ref" in g else [None] * len(g)
    kind = list(g["along_kind"]) if "along_kind" in g else ["sidewalk"] * len(g)     # a mapped sidewalk, or any footpath right beside the road
    routes = list(g["along_links"]) if "along_links" in g else [None] * len(g)
    gaps, inner, rims = [], [], []
    for i, along in enumerate(g["along_link_id"]):
        if pd.isna(along) or conn[i] or along not in by_link:                # not a sidewalk with a road, or a connector
            continue
        route = routes[i] if isinstance(routes[i], list) else None
        if route:                                                            # every road it runs along (duckOSM's link_along)
            same = {along, *route}
        else:                                                                # an older file: the road's street, by name
            same = [lk for lk, nm in street.items() if nm == street.get(along)] if along in street else [along]
        road = [j for lk in same for j in by_link.get(lk, ()) if grp[j] == grp[i]]
        if route and along in street:                                        # and the other pieces of its street that are near it (a 3 m piece it does not run along for 4 m is still the street)
            more = [j for lk, nm in street.items() if nm == street[along] and lk not in same for j in by_link.get(lk, ())
                    if grp[j] == grp[i] and surf.iloc[j].distance(surf.iloc[i]) <= reach]
            road += more
        if not road:
            continue
        ru = shapely.union_all([surf.iloc[j] for j in road])
        if surf.iloc[i].distance(ru) > reach:                                # duckOSM matched it (same level, parallel); too far to be one frame
            continue
        # matched: the whole gap along the footpath is filled, not only where it is within `gap` of the road (up to `reach` m wide):
        # strips between the footpath's centre line and the nearest points of the road's surface, one per metre, so the ends are straight
        line = g.geometry.iloc[i]
        half = float(g["width_m"].fillna(2.0).iloc[i]) / 2
        pts = [line.interpolate(d) for d in [*range(0, int(line.length), 1), line.length]]
        pairs = []
        for pt in pts:
            q = shapely.ops.nearest_points(ru, pt)[0]
            pairs.append((pt, q) if pt.distance(q) - half <= reach and not ru.contains(pt) else None)
        quads, run = [], []
        for k in range(len(pairs) + 1):
            cur = pairs[k] if k < len(pairs) else None
            if cur is not None:
                run.append(cur)
            elif len(run) > 1:
                quads.append(shapely.Polygon([*(p_.coords[0] for p_, _ in run), *(q_.coords[0] for _, q_ in reversed(run))]))
                run = []
            else:
                run = []
        if not quads:
            continue
        fill = shapely.make_valid(shapely.union_all([shapely.make_valid(q) for q in quads]))
        both = shapely.union_all([surf.iloc[i], ru.intersection(fill.buffer(0.5))])
        wide = max(p_.distance(q_) for p_, q_ in (pr for pr in pairs if pr)) - half
        rr = max(gap, min(wide, reach)) / 2 + 0.05
        # the strips, and the closing of footpath + road (it fills the wedge where the footpath goes from one road to the next); no casing on the gap, so its rounded ends show nothing
        add = shapely.union_all([fill, both.buffer(rr).buffer(-rr)]).difference(both)
        closed = shapely.union_all([both, add])
        inner.append((grp[i], closed))
        nearest = min(road, key=lambda j: surf.iloc[i].distance(surf.iloc[j]))
        word = "sidewalk" if kind[i] != "adjacent" else "footpath"
        paint = paints["adjacent" if kind[i] == "adjacent" else "sidewalk"]
        info = f"frame gap · road {ref[nearest]} · {word} {ref[i]} · {surf.iloc[i].distance(ru):.1f} m apart"
        for q in getattr(add, "geoms", [add]):
            if q.geom_type == "Polygon" and q.area > 0.05:
                gaps.append((q, cls[nearest], band[i], info, paint, tun[i]))
                if casing:
                    edge = q.boundary.difference(both.buffer(0.05))          # the sides that touch neither: that is where the verge has an edge
                    if not edge.is_empty and edge.length >= 0.3:
                        rims.append((band[i], edge))
    if not inner:
        return None, None, []
    geo = gpd.GeoSeries([q for q, *_ in gaps], crs=g.crs).to_crs(4326)
    rnd = lambda ring: [[round(x, 7), round(y, 7)] for x, y in ring]  # noqa: E731
    feats = [{"type": "Feature", "properties": {"cls": c, "b": b, "c": pt, "info": info, **({"tn": 1} if tn else {})},
              "geometry": {"type": "Polygon", "coordinates": [rnd(gm.exterior.coords)] + [rnd(h.coords) for h in gm.interiors]}}
             for (_, c, b, info, pt, tn), gm in zip(gaps, geo, strict=True)]
    levels = sorted({gp for gp, _ in inner})
    area = dict(zip(levels, gpd.GeoSeries([shapely.union_all([q for gp, q in inner if gp == lv]) for lv in levels], crs=g.crs).to_crs(4326)))
    ed = gpd.GeoSeries([e for _, e in rims], crs=g.crs).to_crs(4326) if rims else []
    return {"type": "FeatureCollection", "features": feats}, area, [(b, e) for (b, _), e in zip(rims, ed, strict=True)]
