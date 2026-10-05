"""Painted lane arrows (docs/design/lane_arrows.md): the one direction marking of a lane map, a generic arrow from the movements that leave each lane."""
from __future__ import annotations

import math

_TURNS = {"left", "right", "uturn"}


def _kinds(lane_id, link_id, turns_of):
    """The move arrow of a lane: its left / right / thru / uturn, or None. A thru-only lane has one only beside a lane that turns;
    a fork, a merge or an end is shape, not marking, so those lanes get the plain direction arrow only."""
    own = turns_of.get(lane_id, set()) & (_TURNS | {"thru"})
    if not own:
        return None
    if own == {"thru"}:
        return own if any(turns_of.get(o, set()) & _TURNS for o in link_id) else None
    return own - {"uturn"} if own != {"uturn"} and own & {"left", "right", "thru"} else own   # ponytail: a uturn beside other moves is not drawn; a hook of its own if it ever matters


def _shape(kinds, length, width):
    """The arrow as shapely polygons in a local frame: u forward, v to the left, centred on 0."""
    from shapely.geometry import LineString, Polygon

    sh = 0.16                                   # shaft half-width, m
    hl, hw = 1.0, min(0.5, 0.15 * width)        # head length and half-width

    def arm(pts):
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        d = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / d, (y1 - y0) / d
        base = (x1 - ux * hl, y1 - uy * hl)
        body = LineString(pts[:-1] + [base]).buffer(sh, cap_style="flat", join_style="mitre", mitre_limit=2.0)
        head = Polygon([(x1, y1), (base[0] - uy * hw, base[1] + ux * hw), (base[0] + uy * hw, base[1] - ux * hw)])
        return body.union(head)

    a, tip = -length / 2, length / 2
    if kinds == {"uturn"}:                      # a hook: up the right, round, back down the left
        r = min(0.25 * width, 0.8)
        pts = [(a, -r), (0.3, -r)] + [(0.3 + r * math.sin(t / 8 * math.pi), -r * math.cos(t / 8 * math.pi)) for t in range(1, 8)] \
            + [(0.3, r), (a + 1.2, r)]
        return [arm(pts)]
    r = 0.5                                     # a turn: the stem bends a quarter circle and the head points sideways

    def turn(u0, sign):                         # from the stem at u0, round to the side
        return [(u0 + r * math.sin(t / 8 * math.pi / 2), sign * r * (1 - math.cos(t / 8 * math.pi / 2))) for t in range(1, 9)] \
            + [(u0 + r, sign * (r + hl))]

    out = []
    bend = -0.6 if "thru" in kinds else 0.3
    for k, sign in (("left", 1), ("right", -1)):
        if k in kinds:
            out.append(arm(([] if "thru" in kinds else [(a, 0)]) + [(bend, 0)] + turn(bend, sign)))
    if "thru" in kinds:
        out.append(arm([(a, 0), (tip, 0)]))
    return out


def lane_arrows(lanes, turns, s, avoid=None):
    """The arrows as a GeoJSON FeatureCollection of lon/lat polygons (``b``: roadstyle band), or None. ``s``: ``lanes.arrows``; ``avoid``: a lon/lat geometry no arrow may touch (the zebra crossings):
    an arrow slides back along its lane, 1 m at a time, up to 15 m, until it is clear, else it is dropped."""
    import geopandas as gpd
    import shapely
    from shapely.affinity import rotate, scale, translate
    from shapely.ops import substring

    from lanestyle.lines import _band

    if not s or "link_id" not in lanes:
        return None
    turns_of = {}
    if turns is not None and len(turns):
        kind = turns["type"].where(turns["turn"].isna(), turns["turn"]) if "turn" in turns and "type" in turns else (turns["type"] if "type" in turns else [])      # a fork's branch by its movement code
        for a, t in zip(turns["from_lane"].astype(str), kind):
            turns_of.setdefault(a, set()).add(t)
    g = lanes[~lanes["connector"].fillna(False).astype(bool) & (lanes["use"] != "walk")] if "connector" in lanes else lanes[lanes["use"] != "walk"]
    siblings = g.groupby("link_id")["lane_id"].apply(lambda x: [str(i) for i in x]).to_dict()
    u = g.estimate_utm_crs()
    zebra = gpd.GeoSeries([avoid], crs=4326).to_crs(u).iloc[0].buffer(0.3) if avoid is not None else None
    L, back, every, polys, bands = float(s["length_m"]), float(s["end_m"]), float(s.get("repeat_m") or 0), [], []
    for r, geom in zip(g.itertuples(), g.to_crs(u).geometry):
        if geom is None or geom.geom_type != "LineString" or geom.length < L + 2:
            continue
        end = geom.length - back if geom.length >= 2 * back else geom.length / 2
        # the lane's move arrow at its end, then the plain direction arrow back along it every ``repeat_m`` (one on a lane with no move)
        move = _kinds(str(r.lane_id), siblings[r.link_id], turns_of)
        at = [(end, move or {"thru"})]
        while every and at[-1][0] - every > 2 * L:
            at.append((at[-1][0] - every, {"thru"}))
        for d, kinds in at:
            for slide in range(16):                                              # clear of the zebra, or not at all
                d1 = d - slide
                if d1 < L:
                    break
                p, q = geom.interpolate(max(d1 - 0.5, 0)), geom.interpolate(min(d1 + 0.5, geom.length))
                ang = math.degrees(math.atan2(q.y - p.y, q.x - p.x))
                c = geom.interpolate(d1)
                arrow = shapely.union_all(_shape(kinds, L, float(r.width_m)))          # shaft and branches: one arrow
                f = min(1.0, float(r.width_m) / 3.25)                                  # a narrow lane gets a smaller arrow
                poly = translate(rotate(scale(arrow, f, f, origin=(0, 0)), ang, origin=(0, 0)), c.x, c.y)
                if zebra is None or not poly.intersects(zebra):
                    polys.append(poly)
                    bands.append((_band(r), int(r.link_id)))
                    break
    if not polys:
        return None
    ll = gpd.GeoSeries(polys, crs=u).to_crs(4326)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"b": b, "edge_id": link}, "geometry": {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)] for x, y in p.exterior.coords]]}}
        for p, (b, link) in zip(ll, bands) if p.geom_type == "Polygon"]}
