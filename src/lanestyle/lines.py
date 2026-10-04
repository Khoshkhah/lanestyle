"""Lane lines (docs/design/lanestyle_on_roadstyle.md, 2b): dividers, centre lines and edge lines,
cut from the lanes' own geometry, as GeoJSON for the page's line layers."""
import math

_TRUTHY_NOT = (None, "", "no", "false", "0", 0, False)


_JOIN_M = 3.0         # how far from a node a lower footway is outlined with the higher level it meets there (metres)


def _truthy(v):
    return v not in _TRUTHY_NOT and not (isinstance(v, float) and math.isnan(v))


def _level(r):
    """roadstyle's draw band for a lane without a drawing order (render_web._mark_lvl; docs/design/levels_and_looks.md): the level alone, the OSM
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


def _position(r):
    """The lane's fill position in roadstyle's drawing order (``fill_level``, docs/design/interval_draw_order.md) as text, or None without one."""
    p = getattr(r, "fill_level", None)
    return None if p is None or p != p else str(int(p))


def _band(r):
    """What the page draws a lane's layers after: the lane's fill position (``"-2"``, ``"0"``, ``"2"``: roadstyle's per-position layers) when the table has a drawing order
    (a bridge is a road like any other: roadstyle is told it is none, so it has no deck band of its own), else :func:`_level`'s band."""
    pos = _position(r)
    return _level(r) if pos is None else pos


def _group(r):
    """What a lane interacts with (outlines merged, cut at junctions, matched to a road): its level, and for the low band its layer too. roadstyle draws every
    layer below ground in one band (``low``), but a footway on layer -1 and a road on layer -2 are on different levels and must not touch: ``low@-1`` and ``low@-2``.
    Roads that share a node merge whatever their positions in the drawing order: a ring, its arms and the ramps are one surface, so this stays the level, not the position."""
    b = _level(r)
    if b != "low":
        return b
    try:
        ly = int(float(getattr(r, "layer", None)))
    except (TypeError, ValueError):
        ly = -1                                      # a tunnel with no layer number: -1
    return f"low@{ly if ly < 0 else -1}"


def _real(group):
    """The legacy draw band of a ``_group``."""
    return group.split("@")[0]


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


def lane_lines(lanes, s, avoid=None, frame=None):  # frame: {level: lon/lat area} (frames.py)
    """The dividers and centre lines between lanes as a GeoJSON FeatureCollection; properties ``t`` (type:
    ``divider`` / ``centre``), ``b`` (the fill position of the lane) and ``edge_id`` (the link the line belongs to: the lane's own, the smaller of a
    two-way road's two links for a centre line). None when lines are off or the table has no ``link_id`` / ``lane_num``. The outline of a road is
    not drawn here: it is roadstyle's casing of the road (docs/design/lanestyle_on_roadstyle_items.md).

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
    last = g.groupby("link_id")["lane_num"].transform("max").to_numpy()
    trim = float(s.get("junction_trim_m") or 0)
    line_min = float(s.get("line_min_m", 1.5))     # the shortest piece of a line that is kept
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
        if "zebra" in g:                                  # a zebra crossing is stripes on a road, not a surface that cuts it
            polys = polys[~g["zebra"].fillna(False).astype(bool)]
        surface = {lk: shapely.union_all(p.to_numpy()) for lk, p in polys.groupby(g.loc[polys.index, "link_id"].to_numpy())}

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
            other = [surface[k] for k in at[node] if k in surface and k != link and k not in mates]
            u = shapely.union_all(other) if other else None
            cuts[node, link] = u.buffer(trim) if u is not None and trim and node in junction else u
        return cuts[node, link]
    lband = {r.link_id: _group(r) for r in rows}
    # layers below ground are one draw band, but layer -1 lies over layer -2 over layer -3 (in colour: roadstyle's per-edge order, render.py; in its lines: here): a lower layer's
    # lines are hidden under the surface of every higher layer
    lows = sorted({_group(r) for r in rows if _group(r).startswith("low@")}, key=lambda x: int(x[4:]))
    above = {}
    if len(lows) > 1:
        surf_of = {gp: [] for gp in lows}
        for r in rows:
            if _group(r) in surf_of and r.geometry is not None:
                surf_of[_group(r)].append(r.geometry.buffer(r.width_m / 2, cap_style="round"))
        for k, gp in enumerate(lows):
            polys = [p_ for h in lows[k + 1:] for p_ in surf_of[h]]
            above[gp] = shapely.union_all(polys) if polys else None
    ids = list(surface)
    stree = shapely.STRtree([surface[k] for k in ids]) if ids else None
    over_cache = {}

    def over(link, mates):
        """The surface of the other links of the same level that overlap this link anywhere along it (a footpath
        mapped on a road's edge, parallel ways): lines stop there too, so the overlap is one surface, not two
        roads showing through each other. A bridge over a road is another level and stays whole."""
        if stree is None or link not in surface:
            return None
        if link not in over_cache:
            skip = set(mates) | goes_on.get(link, set())
            hit = [surface[ids[j]] for j in stree.query(surface[link])
                   if ids[j] != link and ids[j] not in skip and lband[ids[j]] == lband[link]
                   and surface[ids[j]].intersection(surface[link]).area > 0.5]
            over_cache[link] = shapely.union_all(hit) if hit else None
        return over_cache[link]
    lane1 = {r.link_id: i for i, r in enumerate(rows) if r.lane_num == 1}
    out = []
    zebra = [bool(getattr(r, "zebra", False)) for r in rows]   # drawn as stripes by the page: no lines, no surface
    zfoot = None
    if avoid is not None:                              # the zebra's stretches of the lanes (lon/lat): no lane line under its stripes
        import geopandas as gpd

        zfoot = gpd.GeoSeries([avoid], crs=4326).to_crs(g.crs).iloc[0]
        shapely.prepare(zfoot)
    fr = {}                                            # a road and its sidewalk are one frame (frames.py): no line between them, on their own level only
    if frame:
        import geopandas as gpd

        for gp, a in frame.items():
            fr[gp] = gpd.GeoSeries([a], crs=4326).to_crs(g.crs).iloc[0].buffer(-0.15)
            shapely.prepare(fr[gp])
    walk = [getattr(r, "use", None) == "walk" for i, r in enumerate(rows)]   # footpaths, crossings too: one merged surface, outlined below
    for i, r in enumerate(rows):
        if walk[i] or zebra[i]:
            continue
        half = r.width_m / 2
        rev = getattr(r, "reverse_link_id", None)
        todo = []
        mate = partner.get(r.link_id)
        if r.lane_num == 1:
            if not (rev is None or pd.isna(rev)):
                if r.link_id < rev:
                    todo.append(("centre", half))
            elif mate is not None:                           # one side of a road mapped as 2 ways
                todo.append(("pair", half))
            else:
                todo.append(("edge", half))
        todo.append(("edge" if r.lane_num == last[i] else "divider", -half))
        mates = {m for m in (None if rev is None or pd.isna(rev) else rev, mate) if m is not None}
        stops = [c for c in (cut(getattr(r, "from_node_id", None), r.link_id, mates),
                             cut(getattr(r, "to_node_id", None), r.link_id, mates)) if c is not None]
        if (ov := over(r.link_id, mates)) is not None:
            stops.append(ov)
        if above.get(_group(r)) is not None:
            stops.append(above[_group(r)])
        band = _band(r)
        for t0, off in todo:
            line = piece_line(i, off)
            if t0 == "pair":
                # a road mapped as two ways: their lane 1 edges are one centre line where they lie together (drawn once, by the
                # smaller link id), and each its own edge where they part (a median, trees): never one side without a border
                j = lane1.get(mate)
                near = piece_line(j, rows[j].width_m / 2).buffer(0.3) if j is not None else None
                pieces = [("edge", line)] if near is None else [("centre", line.intersection(near)), ("edge", line.difference(near))]
                if near is not None and r.link_id > mate:
                    pieces = pieces[1:]
            else:
                pieces = [(t0, line)]
            for t, line in pieces:
                if t == "edge":
                    continue                # the outline is the road's casing, drawn by roadstyle
                st = styles.get(t)
                if not st or line.is_empty:
                    continue
                for c in stops:
                    line = line.difference(c)
                if zfoot is not None and zfoot.intersects(line):          # no lane line under the zebra's stripes
                    line = line.difference(zfoot)
                if (f := fr.get(_group(r))) is not None and f.intersects(line):
                    line = line.difference(f)
                line = shapely.line_merge(line) if line.geom_type == "MultiLineString" else line
                parts = [p for p in getattr(line, "geoms", [line]) if p.length >= line_min]   # no crumbs: a dashed line shows each piece as a tick or a dot
                if not parts:
                    continue
                line = parts[0] if len(parts) == 1 else shapely.MultiLineString(parts)
                out.append((t, band, int(r.link_id), line))
    if not out:
        return None
    import geopandas as gpd

    geo = gpd.GeoSeries([o[3] for o in out], crs=g.crs).to_crs(4326)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"t": t, "b": b, "edge_id": link}, "geometry": _coords(gm)}
        for (t, b, link, _), gm in zip(out, geo)]}
