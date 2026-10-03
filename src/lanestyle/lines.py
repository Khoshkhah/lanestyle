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
    """The lane's fill position in roadstyle's drawing order (``pos_fill``, docs/design/interval_draw_order.md) as text, or None without one."""
    p = getattr(r, "pos_fill", None)
    return None if p is None or p != p else str(int(p))


def _band(r):
    """What the page draws a lane's layers after: ``bridge`` for a bridge (roadstyle keeps its deck layers), else the lane's fill position (``"-2"``, ``"0"``, ``"2"``:
    roadstyle's per-position layers) when the table has a drawing order, else :func:`_level`'s band."""
    lv = _level(r)
    pos = _position(r)
    return lv if lv == "bridge" or pos is None else pos


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


def lane_lines(lanes, s, avoid=None, frame=None, frame_edges=None):  # frame: {level: lon/lat area} (frames.py)
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
    # With a drawing order (pos_casing / pos_fill, docs/design/interval_draw_order.md) the outline is a casing: drawn once per carriageway at its casing position,
    # under every fill of that position, so the order alone merges what meets and covers what lies over. No hand cuts then: only the paint (dividers, centre lines) is cut.
    ordered = {"pos_casing", "pos_fill"} <= set(lanes.columns)
    conn = None
    if "connector" in lanes:                     # connectors carry no lane lines: their outer sides get casing (below)
        isc = lanes["connector"].fillna(False).astype(bool)
        conn, lanes = lanes[isc], lanes[~isc]
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
        band, sec = _band(r), 1 / math.cos(math.radians(lat[i]))
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
                if t == "edge" and band == "bridge" and styles.get("bridge_edge"):
                    t = "bridge_edge"       # a bridge's outline: its own casing, cut where a road joins it, whole where one crosses
                if ordered and t in ("edge", "bridge_edge"):
                    continue                # drawn as a casing below
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
                parts = [p for p in getattr(line, "geoms", [line]) if p.length >= 0.5]   # no crumbs
                if not parts:
                    continue
                line = parts[0] if len(parts) == 1 else shapely.MultiLineString(parts)
                out.append((t, band, round(st["width_m"] * sec, 4), line))
    if conn is not None and len(conn) and styles.get("edge") and not ordered:
        # Casing at a connector: the outline of the surface the map draws there. A connector joins lanes the page draws with round ends, so its own edge
        # is not the outline (a lane's cap sticks out past it, and a neighbour's cap covers part of it). The outline is the boundary of the union of the
        # level's lanes (round ends) and connectors, kept near a connector (its surface and the end caps of the lanes it joins), and open where a
        # footway's surface meets it, as a road's edge line is (above).
        gc = conn.to_crs(g.crs)
        cap = lambda r: r.geometry.buffer(r.width_m / 2, cap_style="round")          # noqa: E731
        by_level = defaultdict(lambda: ([], [], []))                                 # level -> road + connector surfaces, footway surfaces, near-connector zone
        by_id = {r.lane_id: r for r in rows}
        for i, r in enumerate(rows):
            if not zebra[i] and r.geometry is not None:
                by_level[_group(r), _band(r)][1 if walk[i] else 0].append(cap(r))
        for r in gc.itertuples(index=False):
            if r.geometry is None or r.geometry.geom_type != "LineString" or r.geometry.length < 0.5:
                continue
            lv = by_level[_group(r), _band(r)]
            lv[0].append(cap(r))
            zone = [cap(r)]
            for ln, end in ((getattr(r, "from_lane", None), -1), (getattr(r, "to_lane", None), 0)):
                if ln in by_id and by_id[ln].geometry is not None:
                    zone.append(Point(by_id[ln].geometry.coords[end]).buffer(by_id[ln].width_m / 2))
            lv[2].extend(zone)
        for (gp, bd), (surfaces, foot, zone) in by_level.items():
            if not zone:
                continue
            u = shapely.union_all(surfaces)
            u = shapely.MultiPolygon([Polygon(q.exterior, [h for h in q.interiors if Polygon(h).area >= 1.0]) for q in getattr(u, "geoms", [u])])   # a sliver between two lanes is no outline
            edge = u.boundary.intersection(shapely.union_all(zone).buffer(trim + 0.1))      # the lane lines stop trim short of a junction: the outline covers that stretch
            if foot:
                edge = edge.difference(shapely.union_all(foot))
            if above.get(gp) is not None:
                edge = edge.difference(above[gp])
            beside = [q for (g2, b2), (s2, f2, _z) in by_level.items() if g2 == gp and b2 != bd for q in (*s2, *f2)]
            if beside:                                                                   # the same level at another position is one surface with this: no outline across the joint
                edge = edge.difference(shapely.union_all(beside))
            parts = [q for q in getattr(shapely.line_merge(edge) if edge.geom_type == "MultiLineString" else edge, "geoms", [edge])
                     if q.geom_type == "LineString" and q.length >= 0.2]                # a boundary piece is never a crumb: a short one closes a corner
            if parts:
                t = "bridge_edge" if bd == "bridge" and styles.get("bridge_edge") else "edge"
                out.append((t, bd, round(styles[t]["width_m"] / math.cos(math.radians(float(lat.mean()))), 4),
                            parts[0] if len(parts) == 1 else shapely.MultiLineString(parts)))
    if any(walk) and styles.get("edge") and not ordered:
        # Walkers have no lanes: the footpaths of a level are one surface, its outline one line (not a pair of edges per
        # strip that cross each other at every junction), stopping where a road's surface begins
        sec = 1 / math.cos(math.radians(float(lat.mean())))
        by = defaultdict(list)                          # (level, position) -> its footway surfaces
        road_of = defaultdict(list)                     # level -> the road and connector surfaces that stop its footways' outline
        joint = defaultdict(list)                       # (level, position) -> the end of a footway that goes on in another one
        level = {"low": 0, "ground": 1, "high": 2, "bridge": 3}
        at_node = defaultdict(set)                      # footway node -> the bands of the footways that meet there
        lanes_at = defaultdict(list)                    # footway node -> the footways that meet there
        eff = {}                                        # footway -> the band it is outlined in
        for i, r in enumerate(rows):
            if walk[i]:
                for nd in (getattr(r, "from_node_id", None), getattr(r, "to_node_id", None)):
                    if nd is not None and not pd.isna(nd):
                        at_node[nd].add((_group(r), _band(r)))
                        lanes_at[nd].append(i)
        if conn is not None and len(conn):             # junction surface: the lane connectors hide the footpath outline too
            for rc in conn.to_crs(g.crs).itertuples(index=False):
                if rc.geometry is not None and rc.geometry.geom_type == "LineString":
                    road_of[_group(rc)].append(rc.geometry.buffer(rc.width_m / 2, cap_style="round"))
        for i, r in enumerate(rows):
            band = (_group(r), _band(r))
            surf = r.geometry.buffer(r.width_m / 2, cap_style="round")                  # the map draws every lane with round ends
            if walk[i]:
                by[band].append(surf)
                eff[i] = band
            else:
                road_of[band[0]].append(surf)
        # a footway that goes on as a footway of another band (a bridge's end, a ramp: layer 1 with and without bridge=yes) has no outline
        # across the joint: each band's outline stops where the other footway's surface is (not where one merely passes over or under)
        for nd, ix in lanes_at.items():
            for i in ix:
                for j in ix:
                    if i != j and eff[i] != eff[j]:
                        # only by the node: the other footway's whole surface would cut this outline wherever the two overlap (a ground footway over a tunnel)
                        end = rows[j].geometry.coords[0] if rows[j].from_node_id == nd else rows[j].geometry.coords[-1]
                        joint[eff[i]].append(rows[j].geometry.buffer(rows[j].width_m / 2, cap_style="round").intersection(shapely.Point(end).buffer(_JOIN_M + 1.0)))
        for (gp, bd), foot in by.items():
            if not foot:
                continue
            edge = shapely.union_all(foot).boundary
            road = road_of[gp] + joint[gp, bd]
            if road:
                edge = edge.difference(shapely.union_all(road))
            if above.get(gp) is not None:                     # a lower layer's outline lies under the higher layers
                edge = edge.difference(above[gp])
            if fr.get(gp) is not None:
                edge = edge.difference(fr[gp])
            beside = [q for (g2, b2), f2 in by.items() if g2 == gp and b2 != bd for q in f2]
            if beside:                                        # the same level at another position: one surface, no outline across the joint
                edge = edge.difference(shapely.union_all(beside))
            t = "bridge_edge" if bd == "bridge" and styles.get("bridge_edge") else "edge"
            parts = [q for q in getattr(shapely.line_merge(edge) if edge.geom_type == "MultiLineString" else edge, "geoms", [edge])
                     if q.length >= 0.5]
            if parts:
                out.append((t, bd, round(styles[t]["width_m"] * sec, 4),
                            parts[0] if len(parts) == 1 else shapely.MultiLineString(parts)))
    if ordered and (styles.get("edge") or styles.get("bridge_edge")):
        # The outline as a casing: each link's carriageway (a connector, a footway: its own surface) as one boundary line, at its casing position. roadstyle draws every casing of
        # a position under every fill of it, so two roads that share a node merge, a road over another covers its outline, and nothing is cut here.
        sec = 1 / math.cos(math.radians(float(lat.mean())))

        def where(r):
            cp = getattr(r, "pos_casing", None)
            return "bridge" if _level(r) == "bridge" else str(int(cp)) if cp is not None and cp == cp else "0"
        each = defaultdict(list)
        for i, r in enumerate(rows):
            if not zebra[i] and r.geometry is not None:
                each[r.link_id, where(r)].append(r.geometry.buffer(r.width_m / 2, cap_style="round"))
        if conn is not None and len(conn):
            for rc in conn.to_crs(g.crs).itertuples(index=False):
                if rc.geometry is not None and rc.geometry.geom_type == "LineString" and rc.geometry.length >= 0.5:
                    each[rc.lane_id, where(rc)].append(rc.geometry.buffer(rc.width_m / 2, cap_style="round"))
        for (_, lab), polys in each.items():
            t = "bridge_edge" if lab == "bridge" and styles.get("bridge_edge") else "edge"
            if styles.get(t):
                # the line is centred on the boundary and the lane's own fill covers its inner half: twice the width shows the full width outside
                out.append((t, lab, round(2 * styles[t]["width_m"] * sec, 4), shapely.union_all(polys).simplify(0.03).boundary))
    if frame_edges and styles.get("edge") and not ordered:               # the casing of a frame's gap (frames.py): where the verge itself meets the open
        import geopandas as gpd

        sec = 1 / math.cos(math.radians(float(lat.mean())))
        for (band, _), e in zip(frame_edges, gpd.GeoSeries([e for _, e in frame_edges], crs=4326).to_crs(g.crs), strict=True):
            parts = [q for q in getattr(shapely.line_merge(e) if e.geom_type == "MultiLineString" else e, "geoms", [e]) if q.length >= 0.3]
            if parts:
                out.append(("bridge_edge" if band == "bridge" and styles.get("bridge_edge") else "edge", band,
                            round(styles["edge"]["width_m"] * sec, 4), parts[0] if len(parts) == 1 else shapely.MultiLineString(parts)))
    if not out:
        return None
    import geopandas as gpd

    geo = gpd.GeoSeries([o[3] for o in out], crs=g.crs).to_crs(4326)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"t": t, "b": b, "k": k}, "geometry": _coords(gm)}
        for (t, b, k, _), gm in zip(out, geo)]}
