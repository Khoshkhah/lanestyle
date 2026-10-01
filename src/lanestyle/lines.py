"""Lane lines (docs/design/lanestyle_on_roadstyle.md, 2b): dividers, centre lines and edge lines,
cut from the lanes' own geometry, as GeoJSON for the page's line layers."""
import math

_TRUTHY_NOT = (None, "", "no", "false", "0", 0, False)


def _truthy(v):
    return v not in _TRUTHY_NOT and not (isinstance(v, float) and math.isnan(v))


def _band(r):
    """roadstyle's draw band for a lane (render_web._mark_lvl): the OSM ``layer`` tag, else 1 for a
    bridge, -1 for a tunnel; the look (tunnel / bridge) from the tags."""
    try:
        ly = int(float(getattr(r, "layer", None)))
    except (TypeError, ValueError):
        ly = 0
    br, tu = _truthy(getattr(r, "bridge", None)), _truthy(getattr(r, "tunnel", None))
    lvl = ly or (1 if br else -1 if tu else 0)
    if lvl < 0:
        return "tunnel" if tu else "low"
    if lvl > 0:
        return "bridge" if br else "high"
    return "ground"


def _coords(g):
    r = lambda cs: [[round(x, 7), round(y, 7)] for x, y in cs]
    if g.geom_type == "LineString":
        return {"type": "LineString", "coordinates": r(g.coords)}
    return {"type": "MultiLineString", "coordinates": [r(p.coords) for p in g.geoms]}


def lane_lines(lanes, s):
    """The lines between and beside lanes as a GeoJSON FeatureCollection; properties ``t`` (type:
    ``divider`` / ``centre`` / ``edge``), ``b`` (roadstyle band) and ``k`` (the line's width in
    metres over cos(latitude): × 512·2^z / C is its width in pixels). None when lines are off or
    the table has no ``link_id`` / ``lane_num``.

    In a link, lane 1 is the leftmost lane in the direction of travel and the lane numbers grow to
    the right (duckOSM, right-hand traffic): lane k's right edge is the divider to lane k+1, the
    last lane's the road's edge, lane 1's left edge the centre line (two-way: a ``reverse_link_id``,
    drawn once, by the smaller link id) or the edge (one-way). At each end node a line stops where it
    enters the surface of the other links there (every link at that node but its own and its
    reverse): at a junction (3 or more neighbours) ``junction_trim_m`` short of it, elsewhere right
    at it, so the inner edges of a sharp bend meet instead of crossing."""
    # ponytail: right-hand traffic only (every area so far); left-hand needs duckOSM's lane order there
    from collections import defaultdict

    import pandas as pd
    import shapely

    styles = s.get("lines") or {}
    if not any(styles.values()) or not {"link_id", "lane_num"} <= set(lanes.columns):
        return None
    g = lanes.to_crs(lanes.estimate_utm_crs())
    lat = lanes.geometry.representative_point().y.to_numpy()
    last = g.groupby("link_id")["lane_num"].transform("max").to_numpy()
    trim = float(s.get("junction_trim_m") or 0)
    at, surface, cuts = defaultdict(set), {}, {}      # node -> its links; link -> its lanes' surface
    if {"from_node_id", "to_node_id"} <= set(g.columns):
        nb = defaultdict(set)
        for lk, a, b in set(zip(g["link_id"], g["from_node_id"], g["to_node_id"])):
            nb[a].add(b)
            nb[b].add(a)
            at[a].add(lk)
            at[b].add(lk)
        junction = {n for n in at if len(nb[n]) >= 3}
        polys = g.geometry.buffer(g["width_m"] / 2, cap_style="flat")
        surface = {lk: shapely.union_all(p.to_numpy()) for lk, p in polys.groupby(g["link_id"].to_numpy())}

    def cut(node, link, rev):
        """The other links' surface at a node (grown by the trim at a junction): where lines stop."""
        if node not in at:
            return None
        if (node, link) not in cuts:
            other = [surface[k] for k in at[node] if k != link and not (rev is not None and k == rev)]
            u = shapely.union_all(other) if other else None
            cuts[node, link] = u.buffer(trim) if u is not None and trim and node in junction else u
        return cuts[node, link]
    out = []
    for i, r in enumerate(g.itertuples(index=False)):
        half = r.width_m / 2
        rev = getattr(r, "reverse_link_id", None)
        todo = []
        if r.lane_num == 1:
            if rev is None or pd.isna(rev):
                todo.append(("edge", half))
            elif r.link_id < rev:
                todo.append(("centre", half))
        todo.append(("edge" if r.lane_num == last[i] else "divider", -half))
        rv = None if rev is None or pd.isna(rev) else rev
        stops = [c for c in (cut(getattr(r, "from_node_id", None), r.link_id, rv),
                             cut(getattr(r, "to_node_id", None), r.link_id, rv)) if c is not None]
        band, sec = _band(r), 1 / math.cos(math.radians(lat[i]))
        for t, off in todo:
            st = styles.get(t)
            if not st:
                continue
            line = r.geometry.offset_curve(off, join_style="mitre", mitre_limit=2.0).simplify(0.05)
            for c in stops:
                line = line.difference(c)
            line = shapely.line_merge(line) if line.geom_type == "MultiLineString" else line
            parts = [p for p in getattr(line, "geoms", [line]) if p.length >= 0.5]   # no crumbs
            if not parts:
                continue
            line = parts[0] if len(parts) == 1 else shapely.MultiLineString(parts)
            out.append((t, band, round(st["width_m"] * sec, 4), line))
    if not out:
        return None
    import geopandas as gpd

    geo = gpd.GeoSeries([o[3] for o in out], crs=g.crs).to_crs(4326)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"t": t, "b": b, "k": k}, "geometry": _coords(gm)}
        for (t, b, k, _), gm in zip(out, geo)]}
