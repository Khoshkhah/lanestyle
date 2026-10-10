"""The roads and the items attached to them (docs/design/lanestyle_on_roadstyle_items.md).

roadstyle draws the **casing of each road and not its fill**: a road is a link, one row with the line of its carriageway. The fill is the **items**
(lanes, connectors, lane lines, zebra stripes, arrows, street names): each has ``edge_id`` (its link) and ``order`` (a whole number, lower first), and roadstyle draws it at the fill
number of its road (``rs.Overlay(edge_col="road_id", order_col="order", style=...)``; ``road_id`` is put on the items by :func:`on_roads`).
"""
from __future__ import annotations

# the order of the items, one scale for all (lower first)
ROAD_END, CONNECTOR, LANE, FOOTPATH_ON_ROAD, LINE, ZEBRA, ARROW, NAME = -2, -1, 0, 1, 1, 2, 3, 4


def _round(coords):
    return [[round(x, 7), round(y, 7)] for x, y in coords]


def _polygon(p):
    return {"type": "Polygon", "coordinates": [_round(p.exterior.coords)] + [_round(i.coords) for i in p.interiors]}


def _snap_ends(lines, nodes, widths=None):
    """``lines`` with the ends at one node made the same point: ``nodes[k]`` is the (from, to) node of line ``k``.
    roadstyle finds where roads meet by the exact equality of their end points (docs/design/lanestyle_on_roadstyle_items.md, "Roads that meet share their end point").
    Without ``widths`` the point is the mean of all the ends at the node, and the end of each line is replaced by it. With ``widths`` (the road widths) the **widest roads decide**: the point is the
    mean of the ends of the roads within half a metre of the widest, and those ends are replaced by it; a narrower road keeps its line and gets the point as one more vertex at that end (a short
    hook that lies inside the wider road, where its fill hides it), so an arm does not pull the ring it joins sideways. A node where a narrower end is farther from the point than half the widest road
    is wide (separate carriageways, a gap in the data): the mean of all the ends, as without ``widths``. Nothing else of a line moves."""
    from collections import defaultdict

    from shapely.geometry import LineString

    at = defaultdict(list)                                      # node -> [(line, end 0/-1, point, width)]
    for k, (ln, (a, b)) in enumerate(zip(lines, nodes, strict=True)):
        w = widths[k] if widths is not None else 0.0
        at[a].append((k, 0, ln.coords[0][:2], w))
        at[b].append((k, -1, ln.coords[-1][:2], w))
    point, hook = {}, set()                                     # node -> shared point; (line, end) that gets it as an extra vertex
    for node, ends in at.items():
        wmax = max(e[3] for e in ends)
        main = [e for e in ends if e[3] >= wmax - 0.5]
        pt = (sum(e[2][0] for e in main) / len(main), sum(e[2][1] for e in main) / len(main))
        far = [e for e in ends if e[3] < wmax - 0.5 and ((e[2][0] - pt[0]) ** 2 + (e[2][1] - pt[1]) ** 2) ** 0.5 > wmax / 2]
        if widths is None or far:
            pt = (sum(e[2][0] for e in ends) / len(ends), sum(e[2][1] for e in ends) / len(ends))
            main = ends
        point[node] = pt
        hook |= {(e[0], e[1]) for e in ends if e not in main and ((e[2][0] - pt[0]) ** 2 + (e[2][1] - pt[1]) ** 2) ** 0.5 > 1e-6}
    out = []
    for k, (ln, (a, b)) in enumerate(zip(lines, nodes, strict=True)):
        mid = [c[:2] for c in ln.coords[1:-1]]
        first, last = [point[a]], [point[b]]
        if (k, 0) in hook:
            first = [point[a], ln.coords[0][:2]]
        if (k, -1) in hook:
            last = [ln.coords[-1][:2], point[b]]
        out.append(LineString([*first, *mid, *last]))
    return out


def link_roads(g, casing_m, centre_m=0.0):
    """One road per **carriageway** (``edge_id`` = the smaller ``link_id`` of its links), as a GeoDataFrame in lon/lat: a street's two directions (a link and its ``reverse_link_id``) are **one road**, a one-way link is one road.
    roadstyle draws the casing of the road, around the whole carriageway, and not its fill; the lanes of both directions are the items inside it. The line is the middle of the carriageway: between the kerb-side
    lanes of the two directions (reversed to the road's direction), or, for a one-way link, between its first and last lane; it is taken at every vertex of the lanes' lines, so a bend is exact and both ends are
    at the node. ``width_m`` is the lanes' widths together, plus ``centre_m`` (the centre line) for two directions, plus the casing on each side (roadstyle draws a casing as a band inside the width, so ``casing_m`` shows outside the lanes). ``g``: the lane table without
    its connectors. ``roads.attrs["road_of"]`` maps every link to its road. ``band`` is the complete band (:func:`lanestyle.levels.tags_band`)."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from shapely.geometry import LineString, Point

    import math

    from lanestyle.levels import tags_band

    u = g.to_crs(g.estimate_utm_crs())
    keep = [c for c in ("name", "highway", "layer", "bridge", "tunnel", "footway", "edge_ref", "osm_id", "reverse_link_id", "level", "roundabout") if c in g]
    lanes_of = {int(k): grp.sort_values("lane_num") if "lane_num" in grp else grp for k, grp in u.groupby("link_id", sort=True)}
    rev = {}
    if "reverse_link_id" in u:
        for lk, rv in zip(u["link_id"], u["reverse_link_id"]):
            if pd.notna(rv) and int(rv) in lanes_of and int(rv) != int(lk):
                rev[int(lk)] = int(rv)
    road_of = {lk: min(lk, rev.get(lk, lk)) for lk in lanes_of}

    def lines_of(link):
        return [ln for ln in lanes_of[link].geometry if ln is not None and ln.geom_type == "LineString" and ln.length > 0]

    def widths_of(link):
        return [float(w) for ln, w in zip(lanes_of[link].geometry, lanes_of[link]["width_m"], strict=True)
                if ln is not None and ln.geom_type == "LineString" and ln.length > 0]

    def middle(a, b, wa=0.0, wb=0.0):
        """The line halfway between the outer edges of lane ``a`` (``wa`` wide) and lane ``b`` (``wb``; the same direction), at every vertex of both:
        their centres' middle moved ``(wb - wa) / 4`` toward ``b`` (2026-10-10: kerb lanes of different widths, a car lane and a bike lane, put the
        middle of their centres 0.44 m off the carriageway's middle and the narrow casing under the wider side's lane)."""
        fr = sorted({0.0, 1.0, *(a.project(Point(c), normalized=True) for c in a.coords),
                     *(b.project(Point(c), normalized=True) for c in b.coords)})
        pa, pb = [a.interpolate(x, normalized=True) for x in fr], [b.interpolate(x, normalized=True) for x in fr]
        k = (wb - wa) / 4.0

        def mid(p, q):
            d = math.hypot(q.x - p.x, q.y - p.y)
            ux, uy = ((q.x - p.x) / d, (q.y - p.y) / d) if d > 1e-9 else (0.0, 0.0)
            return ((p.x + q.x) / 2 + ux * k, (p.y + q.y) / 2 + uy * k)
        pts = [mid(p, q) for p, q in zip(pa, pb, strict=True)]
        return LineString([c for k, c in enumerate(pts) if k == 0 or c != pts[k - 1]])

    rows, geoms, nodes = [], [], []
    for road in sorted(set(road_of.values())):
        links = [road] + ([rev[road]] if road in rev else [])
        ls = lines_of(road)
        if not ls:
            continue
        if len(links) == 2 and lines_of(links[1]):
            other = lines_of(links[1])[-1]
            line = middle(ls[-1], LineString(list(other.coords)[::-1]), widths_of(road)[-1], widths_of(links[1])[-1])            # the kerb lane of each direction (its last lane), the other one reversed: for 1 + 2 lanes the inner lanes' middle is half a lane off the road
        elif len(ls) > 1:
            line = middle(ls[0], ls[-1], widths_of(road)[0], widths_of(road)[-1])
        else:
            line = ls[0]
        line = line.simplify(0.02)                      # the middle line has a vertex at every vertex of both lanes (every 10 cm on a ring): a wide, translucent stroke (roadstyle's tunnel dashes) piles up its joins into fans; 2 cm is not seen
        first = lanes_of[road].iloc[0]
        width = float(sum(lanes_of[k]["width_m"].sum() for k in links)) + 2 * casing_m + (centre_m if len(links) == 2 else 0.0)
        rows.append({"edge_id": int(road), "width_m": width, **{c: first[c] for c in keep}})
        geoms.append(line)
        nodes.append((int(first["from_node_id"]), int(first["to_node_id"])))
    geoms = _snap_ends(geoms, nodes, [r["width_m"] for r in rows])
    roads = gpd.GeoDataFrame(rows, geometry=geoms, crs=u.crs).to_crs(4326)
    roads["band"] = tags_band(roads)
    roads["directed"] = False                          # a road is one carriageway: never paired as two lanes
    roads.attrs["road_of"] = road_of
    roads["cap0"], roads["cap1"], roads.attrs["ext"] = _ends(geoms, nodes, [r["width_m"] for r in rows], [r["edge_id"] for r in rows])
    return roads


def _ends(lines, nodes, widths, ids):
    """How each road ends (UTM ``lines``): where only two roads meet (a road that goes on) its outline keeps its round end and the lane lines run on through the
    node (``ext[(road, node)]``, the node is a key; the value, half the road's width x tan(half the bend), is no longer used: the lanes keep their GMNS length). At a junction (three or more roads) and a dead end the outline ends flat at the node (cap True): the
    connectors are the junction's surface, and a round outline would show as a dark half disc beyond the lanes."""
    import math
    from collections import defaultdict

    at = defaultdict(list)                                       # node -> [(road index, unit vector from the node along the road, width)]
    for k, (ln, (a, b)) in enumerate(zip(lines, nodes, strict=True)):
        cs = [c[:2] for c in ln.coords]
        for node, p, q in ((a, cs[0], cs[1]), (b, cs[-1], cs[-2])):
            d = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
            at[node].append((k, ((q[0] - p[0]) / d, (q[1] - p[1]) / d), widths[k]))
    caps, ext = [[None, None] for _ in lines], {}
    for k, (a, b) in enumerate(nodes):
        for j, node in enumerate((a, b)):
            if len(at[node]) != 2:
                caps[k][j] = True
    for node, ends in at.items():
        if len(ends) != 2:
            continue
        (k1, u, w1), (k2, v, w2) = ends
        bend = math.pi - math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1])))     # 0 = straight on
        for k, w in ((k1, w1), (k2, w2)):
            ext[(int(ids[k]), node)] = min(w / 2 * math.tan(bend / 2), w)
    return [c[0] for c in caps], [c[1] for c in caps], ext


def on_roads(fc, road_of):
    """``fc`` (a FeatureCollection of items) with a ``road_id`` on each item: the road of its ``edge_id`` (a link); ``edge_id`` stays the link. A link that is no road's (a connector's) is its own road. None stays None."""
    if not fc:
        return fc
    return {"type": "FeatureCollection", "features": [
        {**f, "properties": {**f["properties"], "road_id": road_of.get(int(f["properties"]["edge_id"]), f["properties"]["edge_id"])}} for f in fc["features"]]}


def _blend(hex_colour, land, k=0.85):
    """``hex_colour`` over ``land`` at ``k`` opacity, as an opaque ``#rrggbb`` (a tunnel's faded lane: an opaque colour shows no ring where two lanes join)."""
    a, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)), (int(land.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(k * x + (1 - k) * y):02x}" for x, y in zip(a, b, strict=True))


def end_caps(roads, g, colours, land, casing_m, level_of=None):
    """The round end of every road, as a half-width disc at each end of the road's line in the colour of its lanes (a tunnel's blended with ``land``), under all the other items (:data:`ROAD_END`).
    roadstyle draws the casing of a road, with a round cap, and no fill: this is the fill of the cap, so only the casing's rim shows round the end, as for a road with a fill. ``roads``: :func:`link_roads`
    (``width_m`` includes the casing on each side); ``g``, ``colours``: the lane table without its connectors and a colour for each row. None when there is no road."""
    if not len(roads):
        return None
    import geopandas as gpd
    from shapely.geometry import Point

    first = {}
    for i, lk in enumerate(g["link_id"]):
        first.setdefault(roads.attrs["road_of"].get(int(lk), int(lk)), i)
    ru = roads.to_crs(g.estimate_utm_crs())
    polys, props = [], []
    for eid, line, w in zip(ru["edge_id"], ru.geometry, ru["width_m"], strict=True):
        i = first.get(int(eid))
        if i is None or line is None or line.is_empty:
            continue
        colour = colours.iloc[i]
        if level_of and level_of(g.iloc[i]) == "low":
            colour = _blend(colour, land)
        for x, y in (line.coords[0], line.coords[-1]):
            polys.append(Point(x, y).buffer(max(w - 2 * casing_m, 0.1) / 2, quad_segs=16))
            props.append({"edge_id": int(eid), "order": ROAD_END, "color": colour})
    geo = gpd.GeoSeries(polys, crs=ru.crs).to_crs(4326)
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": pr, "geometry": _polygon(p)} for p, pr in zip(geo, props, strict=True)]}


def _band(road, t1, t2, width_resolution=8):
    """The part of the strip along ``road`` (UTM line) between the lateral offsets ``t1 < t2`` (metres, positive to the left of the line), as one polygon: one-sided buffers with round joins, the same
    that roadstyle's casing (a band of constant width around the line, round joins) is made of."""
    from shapely.ops import unary_union

    def side(t):
        return None if abs(t) < 1e-6 else road.buffer(t, single_sided=True, quad_segs=width_resolution)
    a, b = side(t1), side(t2)
    if t1 >= 0:
        shape = b.difference(a) if a is not None else b
    elif t2 <= 0:
        shape = a.difference(b) if b is not None else a
    else:
        shape = unary_union([x for x in (a, b) if x is not None])
    if shape.geom_type == "MultiPolygon":
        shape = max(shape.geoms, key=lambda x: x.area)
    return shape


def _round_ends(road, t1, t2, shape):
    """``shape`` with a half-width disc at each end of the lane's middle (the lane's round ends)."""
    from shapely.geometry import Point
    from shapely.ops import unary_union

    tm, r = (t1 + t2) / 2, (t2 - t1) / 2
    discs = []
    for (x0, y0), (x1, y1), sign in ((road.coords[0], road.coords[1], 1), (road.coords[-1], road.coords[-2], -1)):     # at the end the line is read backwards: -1
        dx, dy = x1 - x0, y1 - y0
        d = (dx * dx + dy * dy) ** 0.5 or 1.0
        nx, ny = -dy / d * sign, dx / d * sign
        discs.append(Point(x0 + nx * tm, y0 + ny * tm).buffer(r, quad_segs=8))
    return unary_union([shape, *discs])


def lane_shapes(u, roads, road_of):
    """``{row position in u: lane polygon (UTM)}`` for the lanes of the carriageways: the lanes of a road are laid side by side across its band (the road's line, ``width_m`` wide, minus the casing on
    each side), leftmost first, each as wide as its ``width_m``. So the lanes fill the band exactly and the casing around them is the same width all along the road. ``u``: the lane table in UTM;
    ``roads``: the roads (:func:`link_roads`) in UTM; ``road_of``: link -> road."""
    by_road = {}
    for i, lk in enumerate(u["link_id"]):
        by_road.setdefault(road_of[int(lk)], []).append(i) if int(lk) in road_of else None
    line_of = dict(zip(roads["edge_id"].astype("int64"), roads.geometry, strict=True))
    out = {}
    for road, rows in by_road.items():
        c = line_of[road]
        widths = {i: float(u["width_m"].iloc[i]) for i in rows}

        def lateral(i, c=c):
            ln = u.geometry.iloc[i]
            p = ln.interpolate(0.5, normalized=True)
            at = c.project(p)
            a, b = (c.interpolate(at), c.interpolate(min(at + 0.1, c.length))) if at + 0.1 <= c.length else (c.interpolate(at - 0.1), c.interpolate(at))
            return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)       # > 0: left of the road's direction
        top = sum(widths.values()) / 2
        for i in sorted(rows, key=lambda i: -lateral(i)):
            t1, t2 = top - widths[i], top
            out[i] = _round_ends(c, t1, t2, _band(c, t1, t2))
            top = t1
    return out


def lane_items(g, colours, land, popup, on_road=(), level_of=None, roads=None, road_of=None):
    """The lanes of ``g`` as polygons (with ``roads``: laid across the band of their road, see :func:`lane_shapes`; else the lane's line, ``width_m`` wide; round ends, simplified to 3 cm) in a GeoJSON FeatureCollection: ``edge_id`` (the link), ``order``
    (:data:`LANE`, or :data:`FOOTPATH_ON_ROAD` for the row positions in ``on_road``: a footpath mapped on a carriageway lies over the road's lanes), ``color`` (``colours``: a colour for each
    row; a tunnel's is blended with ``land``) and the ``popup`` columns. None when ``g`` is empty."""
    if not len(g):
        return None
    u = g.to_crs(g.estimate_utm_crs())
    if roads is not None:             # the lanes of the carriageways: laid across the road's band, so the casing is the same width all along
        shapes = lane_shapes(u, roads.to_crs(u.crs), road_of)
        if len(shapes) != len(u):
            raise ValueError(f"{len(u) - len(shapes)} lane(s) are on no road: the lane table and the roads do not match")
        import geopandas as gpd

        polys = gpd.GeoSeries([shapes[i] for i in range(len(u))], index=u.index, crs=u.crs).simplify(0.03)
    else:
        polys = u.geometry.buffer(u["width_m"] / 2, cap_style="round", join_style="round", resolution=8).simplify(0.03)
    import geopandas as gpd

    geo = gpd.GeoSeries(polys, crs=u.crs).to_crs(4326)
    cols = [c for c in dict.fromkeys([*popup, "lane_id"]) if c in g]                 # the popup fields, and the lane_id the click script finds a lane by
    feats, on = [], set(on_road)
    tun = [(level_of(r) == "low") if level_of else False for r in g.itertuples(index=False)]
    for i, (p, row) in enumerate(zip(geo, g[cols].to_dict("records") if cols else [{}] * len(g), strict=True)):
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        colour = colours.iloc[i]
        props = {k: (None if v is None or v != v else (v.item() if hasattr(v, "item") else v if isinstance(v, (str, int, float, bool)) else str(v))) for k, v in row.items()}
        props.update({"edge_id": int(g["link_id"].iloc[i]), "order": FOOTPATH_ON_ROAD if i in on else LANE,
                      "color": _blend(colour, land) if tun[i] else colour})
        feats.append({"type": "Feature", "properties": props, "geometry": _polygon(p)})
    return {"type": "FeatureCollection", "features": feats}


def _line(geom):
    return {"type": geom.geom_type, "coordinates": [_round(p.coords) for p in geom.geoms] if geom.geom_type == "MultiLineString" else _round(geom.coords)}


def two_way_links(road_of):
    """The links that are one direction of a road of two (``road_of``: link -> road, :func:`link_roads`)."""
    from collections import Counter
    links = Counter(road_of.values())
    return {lk for lk, rd in road_of.items() if links[rd] == 2}


def lane_shifts(g, road_of, centre_m):
    """Each lane's sideways shift (metres, + = right of its travel): ``centre_m / 2`` on a road of two directions, so the centre line has its
    own width between them; 0 on a one-way road. The one rule for the lanes and everything painted on them (lines, arrows, BUS, bike)."""
    two = two_way_links(road_of)
    # ponytail: right-hand traffic only (the centre is on the left of travel), as lines.py; left-hand moves the lanes the other way
    return [centre_m / 2 if int(lk) in two else 0.0 for lk in g["link_id"]]


def lane_strokes(g, colours, land, popup, road_of, centre_m, lines, trim_m, on_road=(), level_of=None, ext=None):
    """The lanes of ``g`` (no connectors) and the lines between them, as LINE items (roadstyle's simple mode draws them in the one road layer at their road's fill):
    ``(lanes, lines)``, two FeatureCollections. A lane is its own GMNS line, ``width_m`` wide, in its colour (``colours``; a tunnel's blended with ``land``); on a road of two
    directions every lane is moved ``centre_m / 2`` to the right of its travel (``offset_m``), so the centre line has its own width between the directions.
    The lines lie on the borders between neighbouring lanes of a link: dashed in metres (``lines["dash_m"]`` / ``lines["gap_m"]``, :func:`lanestyle.strokes.dashes`) between two car lanes,
    solid next to any other lane (bus, bike); a road of two directions gets one solid centre line, ``centre_m`` wide, on lane 1's left edge of its first link. A line stops
    ``trim_m`` short of a junction end of its lane and runs on through a node where its road goes on (``ext``'s nodes). ``road_of``: link -> road (:func:`link_roads`)."""
    from collections import Counter

    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import substring

    from lanestyle import strokes

    if not len(g):
        return None, None
    g = g.reset_index(drop=True)
    bad = [i for i, ln in enumerate(g.geometry) if ln is None or ln.geom_type != "LineString" or ln.is_empty]
    if bad:
        raise ValueError(f"{len(bad)} lane(s) have no line (first: {list(g['lane_id'].iloc[bad[:5]])})")
    drawn = g.geometry           # each lane its own GMNS line, never longer (2026-10-10: no change in a lane's length without connectors)
    two = two_way_links(road_of)
    shift = lane_shifts(g, road_of, centre_m)
    cols = [c for c in dict.fromkeys([*popup, "lane_id"]) if c in g]
    on = set(on_road)
    lane_fs = []
    for i, row in enumerate(g[cols].to_dict("records") if cols else [{}] * len(g)):
        colour = colours.iloc[i]
        if level_of and level_of(g.iloc[i]) == "low":
            colour = _blend(colour, land)
        props = {k: (None if v is None or v != v else (v.item() if hasattr(v, "item") else v if isinstance(v, (str, int, float, bool)) else str(v))) for k, v in row.items()}
        props.update({"edge_id": int(g["link_id"].iloc[i]), "order": FOOTPATH_ON_ROAD if i in on else LANE, "color": colour,
                      "width_m": float(g["width_m"].iloc[i]), "offset_m": shift[i]})
        lane_fs.append({"type": "Feature", "properties": props, "geometry": _line(drawn.iloc[i])})

    line_fs = []

    ext = ext or {}

    def add(link, i, x, dashed, width, kind):
        # a line stops trim_m short of a REAL junction only; where its road goes on (a node in ``ext``) it runs on with the lanes, drawn line
        # included, so the lines of one street do not break at every node (2026-10-10: "a lot of breaks")
        rd = road_of.get(int(link))
        t0 = 0.0 if (rd, int(g["from_node_id"].iloc[i])) in ext else trim_m
        t1 = 0.0 if (rd, int(g["to_node_id"].iloc[i])) in ext else trim_m
        ln = drawn.iloc[i]
        n = strokes.length_m(ln)
        if n <= t0 + t1 + 0.2:
            return
        if t0 or t1:
            ln = substring(ln, t0 / n, 1 - t1 / n, normalized=True)
        if dashed:
            parts = [LineString(f["geometry"]["coordinates"]) for f in strokes.dashes(ln, float(lines["dash_m"]), float(lines["gap_m"]), width, offset_m=x)]
            if not parts:
                return
            ln, x = MultiLineString(parts), 0.0
        line_fs.append({"type": "Feature", "geometry": _line(ln),
                        "properties": {"edge_id": int(link), "order": LINE, "color": lines["color"], "width_m": width, "offset_m": x, "t": kind}})

    use = g["use"] if "use" in g else None
    for lk, grp in g.groupby("link_id", sort=True):
        rows = grp.sort_values("lane_num").index.tolist() if "lane_num" in grp else grp.index.tolist()
        if lines.get("divider", True):
            for a, b in zip(rows, rows[1:]):
                dashed = use is not None and use[a] == "auto" and use[b] == "auto"
                add(lk, a, shift[a] + float(g["width_m"][a]) / 2, dashed, float(lines["width_m"]), "divider")
        if lines.get("centre", True) and int(lk) in two and road_of[int(lk)] == int(lk):
            add(lk, rows[0], -float(g["width_m"][rows[0]]) / 2, False, centre_m, "centre")
    fc = lambda fs: {"type": "FeatureCollection", "features": fs} if fs else None       # noqa: E731
    return fc(lane_fs), fc(line_fs)


def connector_strokes(c, colours, land, popup, lane_width, level_of=None):
    """The lane connectors ``c`` (rows of the lane table with ``connector``) as LINE items: each its own line through the junction, as wide as the lane it leaves
    (``lane_width``: lane_id -> width; GMNS's own connector width is narrower), in its colour, attached to the link it leaves (its ``link_id``) with the order
    :data:`CONNECTOR`: under that road's lanes, over the outlines of the roads before it. None without any."""
    if not len(c):
        return None
    c = c.reset_index(drop=True)
    cols = [k for k in dict.fromkeys([*popup, "lane_id"]) if k in c]
    feats = []
    for i, row in enumerate(c[cols].to_dict("records")):
        colour = colours.iloc[i]
        if level_of and level_of(c.iloc[i]) == "low":
            colour = _blend(colour, land)
        props = {k: (None if v is None or v != v else (v.item() if hasattr(v, "item") else v if isinstance(v, (str, int, float, bool)) else str(v))) for k, v in row.items()}
        props.update({"edge_id": int(c["link_id"].iloc[i]), "order": CONNECTOR, "color": colour, "width_m": float(lane_width[c["from_lane"].iloc[i]]), "offset_m": 0.0})
        feats.append({"type": "Feature", "properties": props, "geometry": _line(c.geometry.iloc[i])})
    return {"type": "FeatureCollection", "features": feats}


def tag(fc, order, **extra):
    """``fc``'s features with ``order`` (and ``extra``) in their properties: a copy; None stays None."""
    if not fc or not fc["features"]:
        return None
    return {"type": "FeatureCollection", "features": [
        {**f, "properties": {**f["properties"], "order": order, **extra}} for f in fc["features"]]}


def stripes(rings, links):
    """The zebra stripes (lon/lat rings) as a FeatureCollection, each with the link of its crossing and the order :data:`ZEBRA`. None without any."""
    if not rings:
        return None
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"edge_id": int(link), "order": ZEBRA}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
        for ring, link in zip(rings, links, strict=True)]}


def only(fc, **match):
    """The features of ``fc`` whose properties equal ``match`` (e.g. ``t="divider"``), as a FeatureCollection; None when there are none."""
    if not fc:
        return None
    keep = [f for f in fc["features"] if all(f["properties"].get(k) == v for k, v in match.items())]
    return {"type": "FeatureCollection", "features": keep} if keep else None


def zebra_strokes(g, cr, st, colour):
    """The painted zebra crossings as LINE items (2026-10-10): each stripe a stroke along the road, ``stripe_m`` wide, as long as the crossing is
    wide, in ``colour``, an item (:data:`ZEBRA`: over the lanes and their lines, under the arrows) of the link of the lane under it, shown from
    ``st["minzoom"]`` (roadstyle items= ``minzoom``). The stripes lie across duckOSM's crossing rectangle (``cr``, :func:`lanestyle.read_crossings`:
    ``length`` across the road, its width along it), ``stripe_m + gap_m`` apart, the row centred; only crossings duckOSM calls painted.
    ``g``: the lanes (``lane_id`` -> ``link_id``). None without any."""
    import math

    import geopandas as gpd
    from shapely import wkt as _w
    from shapely.geometry import LineString

    if cr is None or not len(cr) or "painted" not in cr or "cgeom" not in cr:
        return None
    cr = cr[cr["painted"].fillna(False).astype(bool)]
    if not len(cr):
        return None
    u = g.estimate_utm_crs()
    pitch, thick = float(st["stripe_m"]) + float(st["gap_m"]), float(st["stripe_m"])
    link_of = dict(zip(g["lane_id"], g["link_id"], strict=True))
    lines, links = [], []
    for _cid, grp in cr.groupby("crossing_id"):
        rect = gpd.GeoSeries([_w.loads(grp["cgeom"].iloc[0])], crs=4326).to_crs(u).iloc[0]
        if rect.geom_type != "Polygon":
            continue
        (x0, y0), (x1, y1), _, (x3, y3) = list(rect.exterior.coords)[:4]
        length = math.hypot(x1 - x0, y1 - y0)                       # across the road: the rectangle's first side
        wx, wy = x3 - x0, y3 - y0                                   # along the road: the second side, as long as the zebra is wide
        if length < thick or math.hypot(wx, wy) < 0.5:
            continue
        under = [(r.across_from, r.across_to, int(link_of[r.lane_id])) for r in grp.itertuples() if r.lane_id in link_of]
        if not under:
            continue
        dx, dy = (x1 - x0) / length, (y1 - y0) / length
        n = int((length - thick) // pitch) + 1
        first = (length - ((n - 1) * pitch + thick)) / 2
        for i in range(n):
            mid = first + i * pitch + thick / 2                     # the stripe's middle across the road: its stroke runs along the road
            a = (x0 + dx * mid, y0 + dy * mid)
            lines.append(LineString([a, (a[0] + wx, a[1] + wy)]))
            links.append(min(under, key=lambda x, m=mid: 0.0 if x[0] <= m <= x[1] else min(abs(m - x[0]), abs(m - x[1])))[2])
    if not lines:
        return None
    back = gpd.GeoSeries(lines, crs=u).to_crs(4326)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[round(x, 7), round(y, 7)] for x, y in ln.coords]},
         "properties": {"edge_id": link, "order": ZEBRA, "color": colour, "width_m": thick, "offset_m": 0.0, "minzoom": float(st.get("minzoom", 17))}}
        for ln, link in zip(back, links, strict=True)]}


def _sidewalk_sides(tags, default_m):
    """The sides of an OSM way with a sidewalk in its tags (``sidewalk`` / ``sidewalk:both|left|right``), each with its width in metres
    (``sidewalk[:side]:width``, else ``default_m``): ``{"left": m, "right": m}``, sides of the way's own direction. ``separate`` (its own way,
    drawn as one), ``no`` and a bare ``yes`` (which side?) give none: nothing is guessed."""
    def num(v):
        try:
            return float(str(v).split()[0].replace(",", "."))
        except (TypeError, ValueError, IndexError):
            return None
    tags = tags or {}
    have = {"left": False, "right": False}
    main = tags.get("sidewalk")
    if main in ("both", "left", "right"):
        for side in ("left", "right"):
            have[side] = main in ("both", side)
    if tags.get("sidewalk:both") in ("yes",):
        have = {"left": True, "right": True}
    for side in ("left", "right"):
        if tags.get(f"sidewalk:{side}") in ("yes",):
            have[side] = True
        elif tags.get(f"sidewalk:{side}") in ("no", "separate"):
            have[side] = False
    return {side: (num(tags.get(f"sidewalk:{side}:width")) or num(tags.get("sidewalk:both:width")) or num(tags.get("sidewalk:width")) or default_m)
            for side, on in have.items() if on}


def sidewalk_strokes(g, road_of, lines, width, tags, st, colour):
    """The sidewalks OSM tags on a street (2026-10-10; ``sidewalk=right/left/both``, not ``separate``, which is its own way) as LINE items:
    a strip in ``colour`` along the street's drawn line (``lines``: link -> the road's line in that link's direction), just outside its full
    width (``width``: link -> metres), so its outline reads as the kerb; ``st["width_m"]`` wide unless tagged, shown from ``st["minzoom"]``. It
    stops where the street's lanes stop at a junction (their ``cut_geometry``), so it never runs across a crossing street. One strip per side
    per road, on the road's own link (``road_of``: link -> road). ``g``: the lanes (``link_id``, ``osm_id``, ``edge_ref``, ``cut_geometry``);
    ``tags``: OSM way id -> its tags. None without any."""
    import pandas as pd
    from shapely.geometry import Point
    from shapely.ops import substring

    info = g.drop_duplicates("link_id").set_index("link_id")
    cut = {}                                                   # link -> (share cut at its start, at its end) of its lanes, the most
    if "cut_geometry" in g:
        for lk, ln, c in zip(g["link_id"], g.geometry, g["cut_geometry"], strict=True):
            if c is None or c != c or ln is None or c.is_empty or ln.length == 0:
                continue
            a, b = ln.project(Point(c.coords[0]), normalized=True), 1 - ln.project(Point(c.coords[-1]), normalized=True)
            s0, s1 = cut.get(int(lk), (0.0, 0.0))
            cut[int(lk)] = (max(s0, a), max(s1, b))
    fs = []
    for lk, rd in road_of.items():
        if int(lk) != int(rd) or int(lk) not in info.index or str(lk) not in lines or str(lk) not in width:
            continue                                          # one strip per road: on its own link
        row = info.loc[int(lk)]
        back = str(row.get("edge_ref") or "").endswith("r")   # the link runs against its OSM way: the way's right is its left
        rev = row.get("reverse_link_id")
        a, b = cut.get(int(lk), (0.0, 0.0))
        if pd.notna(rev) and int(rev) in cut:  # the other direction's cut, turned round
            ra, rb = cut[int(rev)]
            a, b = max(a, rb), max(b, ra)
        if a + b >= 0.95:
            continue
        line = substring(lines[str(lk)], a, 1 - b, normalized=True)
        if line.geom_type != "LineString" or line.length == 0:
            continue
        for side, m in _sidewalk_sides(tags.get(int(row["osm_id"])) if pd.notna(row.get("osm_id")) else None, float(st["width_m"])).items():
            sign = (1 if side == "right" else -1) * (-1 if back else 1)
            fs.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[round(x, 7), round(y, 7)] for x, y in line.coords]},
                       "properties": {"edge_id": int(lk), "order": LANE, "color": colour, "width_m": m, "minzoom": float(st.get("minzoom", 17)),
                                      "offset_m": sign * (float(width[str(lk)]) / 2 + m / 2), "kind": "sidewalk"}})
    return {"type": "FeatureCollection", "features": fs} if fs else None
