"""Lane lines (docs/design/lanestyle_on_roadstyle.md, 2b): dividers, centre lines and edge lines,
cut from the lanes' own geometry, as GeoJSON for the page's line layers."""
import math

_TRUTHY_NOT = (None, "", "no", "false", "0", 0, False)


def _truthy(v):
    return v not in _TRUTHY_NOT and not (isinstance(v, float) and math.isnan(v))


def _band(r):
    """roadstyle's draw band for a lane (render_web._mark_lvl; docs/design/levels_and_looks.md): the level alone, the OSM
    ``layer`` tag, else 1 for a bridge, -1 for a tunnel: ``low`` (a tunnel is a road of it), ``ground`` or ``high``; a bridge's
    deck look draws after the high band, so its lines go with it."""
    try:
        ly = int(float(getattr(r, "layer", None)))
    except (TypeError, ValueError):
        ly = 0
    br, tu = _truthy(getattr(r, "bridge", None)), _truthy(getattr(r, "tunnel", None))
    lvl = ly or (1 if br else -1 if tu else 0)
    if lvl < 0:
        return "low"
    if lvl > 0:
        return "bridge" if br else "high"
    return "ground"


def _coords(g):
    r = lambda cs: [[round(x, 7), round(y, 7)] for x, y in cs]
    if g.geom_type == "LineString":
        return {"type": "LineString", "coordinates": r(g.coords)}
    return {"type": "MultiLineString", "coordinates": [r(p.coords) for p in g.geoms]}


def _paired(g):
    """{link_id: partner link_id} for one-way links whose lane 1's left edge lies on another one-way
    link's lane 1 left edge, running the other way, for at least half its length: a road mapped as
    two one-way ways (duckOSM places them side by side, docs/design/gmns_paired_carriageways.md).
    Their shared edge is the centre line, not two edge lines."""
    import pandas as pd
    import shapely

    rows = [r for r in g.itertuples(index=False)
            if r.lane_num == 1 and pd.isna(getattr(r, "reverse_link_id", None))]
    left = [r.geometry.offset_curve(r.width_m / 2, join_style="mitre", mitre_limit=2.0) for r in rows]
    keep = [k for k, a in enumerate(left) if a.geom_type == "LineString" and not a.is_empty]
    rows, left = [rows[k] for k in keep], [left[k] for k in keep]
    if not rows:
        return {}
    tree = shapely.STRtree(left)
    out = {}
    for i, a in enumerate(left):
        if rows[i].link_id in out:
            continue
        near = a.buffer(0.6)
        for j in tree.query(near):
            b = left[j]
            if rows[j].link_id in (rows[i].link_id, *out):
                continue
            (ax, ay), (bx, by) = _dir(a), _dir(b)
            if ax * bx + ay * by > -0.866:                       # not running the other way
                continue
            if b.intersection(near).length >= 0.5 * min(a.length, b.length):
                out[rows[i].link_id], out[rows[j].link_id] = rows[j].link_id, rows[i].link_id
                break
    return out


def _dir(line):
    """The line's overall direction (start to end), a unit vector."""
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    n = math.hypot(x1 - x0, y1 - y0) or 1.0
    return (x1 - x0) / n, (y1 - y0) / n


def _start_dir(line):
    """The line's start direction (its first segment), a unit vector."""
    (x0, y0), (x1, y1) = line.coords[0], line.coords[1]
    n = math.hypot(x1 - x0, y1 - y0) or 1.0
    return (x1 - x0) / n, (y1 - y0) / n


def _end_dir(line):
    """The line's end direction (its last segment), a unit vector."""
    (x0, y0), (x1, y1) = line.coords[-2], line.coords[-1]
    n = math.hypot(x1 - x0, y1 - y0) or 1.0
    return (x1 - x0) / n, (y1 - y0) / n


def lane_lines(lanes, s):
    """The lines between and beside lanes as a GeoJSON FeatureCollection; properties ``t`` (type:
    ``divider`` / ``centre`` / ``edge``), ``b`` (roadstyle band) and ``k`` (the line's width in
    metres over cos(latitude): × 512·2^z / C is its width in pixels). None when lines are off or
    the table has no ``link_id`` / ``lane_num``.

    In a link, lane 1 is the leftmost lane in the direction of travel and the lane numbers grow to
    the right (duckOSM, right-hand traffic): lane k's right edge is the divider to lane k+1, the
    last lane's the road's edge, lane 1's left edge the centre line (two-way: a ``reverse_link_id``;
    or a one-way link paired with the opposite one beside it, ``_paired``; drawn once, by the smaller
    link id) or the edge (one-way). At each end node a line stops where it
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
    if "connector" in lanes:                     # connectors carry no lane lines
        lanes = lanes[~lanes["connector"].fillna(False).astype(bool)]
    g = lanes.to_crs(lanes.estimate_utm_crs())
    lat = lanes.geometry.representative_point().y.to_numpy()
    last = g.groupby("link_id")["lane_num"].transform("max").to_numpy()
    trim = float(s.get("junction_trim_m") or 0)
    partner = _paired(g)
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

    # a lane that goes on into another link's lane (lane k's end on lane k's start within 0.3 m,
    # heading on within 45 degrees, the same width: duckOSM places a road's pieces as one run) is
    # the same road. Such lanes form a chain: its lines are offset once from the chain's merged
    # geometry and each piece takes its share, so the joints have no ticks or kinks; and the chain's
    # links never cut each other's lines. The heading matters: a one-lane one-way road has its lane
    # on its own line, so at a T-junction the side road's lane starts exactly where the road's ends.
    from collections import Counter

    from shapely.geometry import LinearRing, LineString, Point, Polygon
    from shapely.ops import substring

    rows = list(g.itertuples(index=False))
    nxt, goes_on = {}, defaultdict(set)
    if {"from_node_id", "to_node_id"} <= set(g.columns):
        starts = [(r.link_id, r.lane_num, Point(r.geometry.coords[0]), _start_dir(r.geometry), r.width_m) for r in rows]
        tree = shapely.STRtree([p for _, _, p, _, _ in starts])
        cand = {}
        for i, r in enumerate(rows):
            end, (ex, ey) = Point(r.geometry.coords[-1]), _end_dir(r.geometry)
            c = [j for j in tree.query(end.buffer(0.3))
                 if starts[j][0] != r.link_id and starts[j][1] == r.lane_num and starts[j][2].distance(end) <= 0.3
                 and ex * starts[j][3][0] + ey * starts[j][3][1] > 0.707 and abs(starts[j][4] - r.width_m) < 0.01]
            if len(c) == 1:
                cand[i] = c[0]
        taken = Counter(cand.values())
        nxt = {i: j for i, j in cand.items() if taken[j] == 1}
        for i, j in nxt.items():
            goes_on[rows[i].link_id].add(rows[j].link_id)
            goes_on[rows[j].link_id].add(rows[i].link_id)
    prv = {j: i for i, j in nxt.items()}
    chains, chain_of = [], {}
    for start in [i for i in range(len(rows)) if i not in prv] + list(range(len(rows))):
        if start in chain_of:
            continue
        ch, x = [], start
        while x is not None and x not in chain_of:
            chain_of[x] = len(chains)
            ch.append(x)
            x = nxt.get(x)
        chains.append(ch)
    closed = {ci for ci, ch in enumerate(chains) if len(ch) > 1 and nxt.get(ch[-1]) == ch[0]}
    offset_cache = {}

    def chain_line(ci, off):
        """The chain's merged lanes offset once: (line, is_ring), or None when the geometry won't do."""
        if (ci, off) in offset_cache:
            return offset_cache[ci, off]
        coords = list(rows[chains[ci][0]].geometry.coords)
        for i in chains[ci][1:]:
            c = list(rows[i].geometry.coords)
            coords += c[1:] if Point(c[0]).distance(Point(coords[-1])) < 0.01 else c
        res = None
        if ci in closed:
            if Point(coords[0]).distance(Point(coords[-1])) >= 0.01:
                coords.append(coords[0])
            poly = Polygon(coords)
            if poly.is_valid and poly.area >= 1.0:
                ccw = LinearRing(coords).is_ccw
                buf = poly.buffer(-abs(off) if (off > 0) == ccw else abs(off))     # left (+) is inside a ccw ring
                if not buf.is_empty and buf.geom_type == "Polygon":
                    bd = list(buf.exterior.coords)
                    res = (LineString(bd if LinearRing(bd).is_ccw == ccw else bd[::-1]), True)
        else:
            line = LineString(coords).offset_curve(off, join_style="mitre", mitre_limit=2.0)
            if line.geom_type == "LineString" and not line.is_empty:
                res = (line, False)
        offset_cache[ci, off] = res
        return res

    def piece_line(i, off):
        """Lane i's line at offset ``off``: its share of the chain's one offset line, else its own."""
        gm = rows[i].geometry
        ci = chain_of[i]
        if len(chains[ci]) > 1 and chain_line(ci, off):
            line, ring = chain_line(ci, off)
            s0, s1 = line.project(Point(gm.coords[0])), line.project(Point(gm.coords[-1]))
            if ring and s1 <= s0:
                seg = LineString(list(substring(line, s0, line.length).coords) + list(substring(line, 0, s1).coords)[1:])
            else:
                seg = substring(line, s0, s1)
            if seg.geom_type == "LineString" and seg.length >= 0.1:
                return seg.simplify(0.05)
        return gm.offset_curve(off, join_style="mitre", mitre_limit=2.0).simplify(0.05)

    def cut(node, link, mates):
        """The other links' surface at a node (grown by the trim at a junction): where lines stop.
        ``mates``: the link's reverse and paired carriageway, whose surface it shares an edge with,
        and the links its lanes go on into (one road)."""
        if node not in at:
            return None
        mates = set(mates) | goes_on.get(link, set())
        if (node, link) not in cuts:
            other = [surface[k] for k in at[node] if k != link and k not in mates]
            u = shapely.union_all(other) if other else None
            cuts[node, link] = u.buffer(trim) if u is not None and trim and node in junction else u
        return cuts[node, link]
    out = []
    for i, r in enumerate(rows):
        half = r.width_m / 2
        rev = getattr(r, "reverse_link_id", None)
        todo = []
        mate = partner.get(r.link_id)
        if r.lane_num == 1:
            if not (rev is None or pd.isna(rev)):
                if r.link_id < rev:
                    todo.append(("centre", half))
            elif mate is not None:                           # one side of a road mapped as 2 ways
                if r.link_id < mate:
                    todo.append(("centre", half))
            else:
                todo.append(("edge", half))
        todo.append(("edge" if r.lane_num == last[i] else "divider", -half))
        mates = {m for m in (None if rev is None or pd.isna(rev) else rev, mate) if m is not None}
        stops = [c for c in (cut(getattr(r, "from_node_id", None), r.link_id, mates),
                             cut(getattr(r, "to_node_id", None), r.link_id, mates)) if c is not None]
        band, sec = _band(r), 1 / math.cos(math.radians(lat[i]))
        for t, off in todo:
            st = styles.get(t)
            if not st:
                continue
            line = piece_line(i, off)
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
