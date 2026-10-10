"""The GMNS reader: a duckOSM GMNS database -> the lane table and turns render_lanes draws."""


def _cols(con, schema, table, db=None):
    q = "SELECT column_name FROM duckdb_columns() WHERE schema_name = ? AND table_name = ?"
    args = [schema, table]
    if db:
        q, args = q + " AND database_name = ?", args + [db]
    return {c for (c,) in con.execute(q, args).fetchall()}


def _ring_links(source_db, mode):
    """The link ids (duckOSM edge ids) of a roundabout's ring: the OSM ``junction`` tag, read from ``source_db``'s edges; none without a source database."""
    if not source_db:
        return []
    import duckdb

    con = duckdb.connect(str(source_db), read_only=True)
    try:
        if "junction" not in _cols(con, mode, "edges") or "edge_id" not in _cols(con, mode, "edges"):
            return []
        return [r[0] for r in con.execute(f"SELECT edge_id FROM {mode}.edges WHERE junction IN ('roundabout', 'circular')").fetchall()]
    finally:
        con.close()


def read_crossings(gmns_db):
    """duckOSM's ``gmns_driving.crossing`` / ``lane_crossing`` as one table, a row per crossing per lane it covers (``crossing_id``,
    ``lane_id``, ``start_lr``, ``end_lr``, ``across_from``, ``across_to``, ``to_left``, ``painted``, ``length``, ``crossing_type``,
    ``source``, ``cgeom``: the crossing's rectangle, lon/lat WKT); None where the file has none (older duckOSM, no driving mode). ``from_gmns`` puts it in ``lanes.attrs["crossings"]``,
    where ``render_lanes`` takes it from."""
    import duckdb

    con = duckdb.connect(str(gmns_db), read_only=True)
    try:
        if not (_cols(con, "gmns_driving", "crossing") and _cols(con, "gmns_driving", "lane_crossing")):
            return None
        return con.execute("""SELECT lc.crossing_id, lc.lane_id, lc.start_lr, lc.end_lr, lc.across_from, lc.across_to, lc.to_left,
                                     c.painted, c.length, c.crossing_type, c.source, ST_AsText(c.geom) AS cgeom
                              FROM gmns_driving.lane_crossing lc JOIN gmns_driving.crossing c USING (crossing_id)""").df()
    finally:
        con.close()


def from_gmns(gmns_db, mode="driving", source_db=None, modes=None):
    """:func:`_from_gmns` plus the crossings in ``lanes.attrs["crossings"]`` (see :func:`read_crossings`). The drawing order (roadstyle's casing and fill numbers) is computed
    by ``render_lanes`` from the lane table: ``visualization.edge_levels`` of the database is not used (docs/design/lanestyle_on_roadstyle_levels.md)."""
    lanes, turns = _from_gmns(gmns_db, mode, source_db, modes)
    lanes.attrs["crossings"] = read_crossings(gmns_db) if "driving" in (modes or [mode]) else None
    lanes.attrs["source_db"] = str(source_db) if source_db else None            # where roadstyle's numbers of the roads are read from (visualization.edge_levels), if the file has them
    return lanes, turns


def _from_gmns(gmns_db, mode="driving", source_db=None, modes=None):
    """Read ``gmns_<mode>`` into ``(lanes, turns)``; the columns are described on :func:`_from_gmns_mode` below.

    ``modes`` reads several modes into one table, e.g. ``("driving", "walking")``: the first is read as it is, each
    later one adds only the lanes of links the earlier ones do not have (a footpath, not the road you also walk
    on: nor that road's other direction, the walking network's link of a one-way road, which has its OSM way, ``osm_id``,
    in common with the earlier mode's link), and only the turns between lanes that are kept. A ``modes`` column says which of them have the link
    (``"driving,walking"``: a street cars and pedestrians share), which ``render_lanes`` colours by. ``modes`` wins
    over ``mode``. Cycling counts only where bikes are ridden: a link duckOSM marks ``dismount`` (bikes pushed, a footway) is
    walked, a walking link (2026-10-09), so reading cycling takes ``source_db``, where that mark is (GMNS has none)."""
    if not modes:
        return _from_gmns_mode(gmns_db, mode, source_db)
    import geopandas as gpd
    import pandas as pd

    pushed = set()
    if "cycling" in modes:
        if not source_db:
            raise ValueError("from_gmns(modes=... 'cycling' ...): pass source_db, the duckOSM file: its cycling.edges.dismount says where bikes are pushed, not ridden")
        import duckdb
        con = duckdb.connect(str(source_db), read_only=True)
        try:
            pushed = {r[0] for r in con.execute("SELECT edge_id FROM cycling.edges WHERE dismount").fetchall()}
        finally:
            con.close()

    tables, turn_tables, seen, seen_ways, modes_of, way_of = [], [], set(), set(), {}, {}
    earlier = set()                                      # the lanes of the modes read before
    for i, m in enumerate(modes):
        lanes, turns = _from_gmns_mode(gmns_db, m, source_db)
        # a later mode's movement that starts on an earlier mode's lane is that mode's walkers stepping off the road onto a footpath: it stays in the table (the footway join
        # between the two is a connector, labelled and ordered by it) but is flagged ``walkers``, and is no turn of the car lane (it would give the lane a left / right arrow
        # towards a footway): lane types, arrows, counts and click highlights leave the flagged rows out
        turns = turns.assign(walkers=turns["from_lane"].astype(str).isin(earlier)) if i else turns.assign(walkers=False)
        for link in set(lanes["link_id"].dropna()):      # every mode whose network has the link, kept or not (cycling: where ridden)
            mm = "walking" if m == "cycling" and link in pushed else m       # bikes pushed: walked
            if mm not in modes_of.get(link, []):
                modes_of.setdefault(link, []).append(mm)
        if "osm_id" in lanes:
            way_of.update(zip(lanes["link_id"], lanes["osm_id"]))
        if i:
            lanes = _keep_joins(lanes, [t["lane_id"] for t in tables], seen, seen_ways)
        seen |= set(lanes["link_id"].dropna())
        if "osm_id" in lanes:
            seen_ways |= set(lanes["osm_id"].dropna())
        tables.append(lanes)
        earlier |= set(lanes["lane_id"].astype(str))
        turn_tables.append(turns)
    lanes = gpd.GeoDataFrame(pd.concat(tables, ignore_index=True), crs=4326)
    lanes["modes"] = lanes["link_id"].map(lambda l: ",".join(modes_of.get(l, [])))    # e.g. "driving,walking"
    if "from_lane" in lanes and "to_lane" in lanes and lanes["connector"].any():
        # a connector joins two lanes: it is a street of the modes both have, not of the lane it leaves (a car-only ring's
        # connector from a street cars and pedestrians share is a car connector)
        mode_of = dict(zip(lanes["lane_id"], lanes["modes"]))
        both = lambda a, b: ",".join(m for m in mode_of.get(a, "").split(",") if m and m in mode_of.get(b, "").split(","))   # noqa: E731
        lanes["modes"] = [both(a, b) or mo if c else mo for c, a, b, mo in zip(lanes["connector"], lanes["from_lane"], lanes["to_lane"], lanes["modes"])]
    if "along_link_id" in lanes and "osm_id" in lanes:   # a sidewalk's road whose link was dropped above (its other direction is kept): the same way
        kept = dict(zip(lanes["osm_id"], lanes["link_id"]))
        links = set(lanes["link_id"].dropna())
        lanes["along_link_id"] = [a if pd.isna(a) or a in links else kept.get(way_of.get(a), a) for a in lanes["along_link_id"]]
        lanes["along_link_id"] = lanes["along_link_id"].astype("Int64")
        if "along_links" in lanes:
            lanes["along_links"] = [[a if a in links else kept.get(way_of.get(a), a) for a in rs] if isinstance(rs, list) else rs
                                    for rs in lanes["along_links"]]
    turns = pd.concat(turn_tables, ignore_index=True)
    keep = set(lanes["lane_id"])
    return lanes, turns[turns["from_lane"].isin(keep) & turns["to_lane"].isin(keep)].reset_index(drop=True)


def _keep_joins(lanes, earlier, seen, seen_ways):
    """A later mode's lanes without the links an earlier mode has (and its other direction, the same OSM way). Its connectors stay when both
    their lanes are kept: a footway's join to a road lane of an earlier mode (duckOSM's ``lane_connector`` in ``gmns_walking``, docs/design/gmns_walk_joins.md);
    the road lane is the earlier mode's, the connector takes the footway's place in the table (its class, use, level and link)."""
    import pandas as pd

    conn = lanes["connector"].fillna(False).astype(bool) if "connector" in lanes else None
    rest = lanes if conn is None else lanes[~conn]
    rest = rest[~rest["link_id"].isin(seen)]
    if "osm_id" in rest:
        rest = rest[~rest["osm_id"].isin(seen_ways)]
    if conn is None or not conn.any():
        return rest
    from_ids = {x for t in earlier for x in t}
    foot = rest.set_index("lane_id")
    joins = lanes[conn]
    joins = joins[joins["from_lane"].isin(from_ids) & joins["to_lane"].isin(foot.index)].copy()
    for c in [c for c in rest.columns if c not in ("lane_id", "width_m", "geometry", "connector", "from_lane", "to_lane")]:
        joins[c] = joins["to_lane"].map(foot[c])
    return pd.concat([rest, joins], ignore_index=True) if len(joins) else rest


def _from_gmns_mode(gmns_db, mode, source_db):
    """Read ``gmns_<mode>.lane`` / ``.link`` / ``.movement`` into ``(lanes, turns)``.

    ``lanes``: a GeoDataFrame, one row per lane (EPSG:4326, each line in the direction of travel)
    with ``lane_id``, ``highway`` (the link's ``facility_type``), ``width_m`` (``lane.width``; null
    where untagged, render_lanes fills the default), ``use``, ``name`` (lane 1 only: one label per
    road), ``link_id``, ``lane_num``, ``turn``, ``from_node_id`` / ``to_node_id`` and
    ``reverse_link_id`` (the same road the other way: same nodes swapped and the same geometry, so
    the two halves of a one-way loop are not a pair; null on a one-way road),
    for the lane lines, ``lanes`` (the link's lane count) and, from ``source_db``, ``bridge`` /
    ``tunnel`` / ``layer``, the OSM way ``osm_id`` and, from duckOSM's GMNS, ``edge_ref``.

    Levels come from the GMNS ``link`` if it has those columns, else from ``source_db`` (the
    duckOSM database the GMNS file was made from: ``link_id`` = ``<mode>.edges.edge_id``), else
    every lane is at ground level (no level columns).

    With duckOSM's ``lane_connector`` table, each lane-to-lane connector is a row too
    (``connector`` True, ``from_lane`` / ``to_lane``; its level and road class from the lane it leaves).

    ``turns``: a DataFrame ``from_lane``, ``to_lane``, ``type`` (the movement type; ``turn``: ``left`` / ``thru`` / ``right`` from the code of a ``diverge`` movement, else None; ``uturn`` is
    drawn in its own colour), from ``movement``: each lane of the inbound link in
    ``start_ib_lane``..``end_ib_lane`` into the outbound lane at the same place in
    ``start_ob_lane``..``end_ob_lane`` (equal-length ranges paired in order, as osm2gmns and duckOSM
    write them; NULL = every lane). Empty without a movement table."""
    import uuid

    import duckdb
    import geopandas as gpd
    import pandas as pd

    g = f"gmns_{mode}"
    lvl = ""
    con = duckdb.connect(str(gmns_db), read_only=True)
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
        if not _cols(con, g, "lane"):
            raise ValueError(f"no '{g}.lane' in {gmns_db}: build a GMNS db first (duckOSM `duckosm gmns`)")
        link_cols = _cols(con, g, "link")
        same = " AND ST_Equals(r.geom, k.geom)" if "geom" in link_cols else ""
        nlanes = "k.lanes, " if "lanes" in link_cols else ""
        src = f"lanestyle_src_{uuid.uuid4().hex[:8]}"   # one db instance per file per process:
        # a caller's own connection to gmns_db may already hold an attachment, so never reuse a name
        if {"bridge", "tunnel", "layer"} <= link_cols:
            lvl = ", k.bridge, k.tunnel, k.layer"
        elif source_db:
            con.execute(f"ATTACH '{str(source_db).replace(chr(39), chr(39) * 2)}' AS {src} (READ_ONLY)")
            src_cols = _cols(con, mode, "edges", db=src)
            if not {"edge_id", "bridge", "tunnel", "layer"} <= src_cols:
                raise ValueError(f"no {mode}.edges with bridge / tunnel / layer in {source_db}")
            lvl = ", e.bridge, e.tunnel, e.layer" + (", e.osm_id" if "osm_id" in src_cols else "")
        if "osm_id" in link_cols and "osm_id" not in lvl:
            lvl += ", k.osm_id"
        for c in ("footway", "crossing", "crossing_markings"):   # the OSM tags: a crossing is drawn over the road it crosses, a marked one as a zebra
            if c in link_cols:
                lvl += f", k.{c}"
        if "along_link_id" in link_cols:             # a sidewalk's road (docs/design/lanestyle_on_roadstyle.md: frames)
            lvl += ", k.along_link_id" + (", k.along_kind" if "along_kind" in link_cols else "")
        if "edge_ref" in link_cols:                  # duckOSM's readable id, <osm_id>#<n><f|r>: the same way and number = twins
            lvl += ", k.edge_ref"
        join = f"LEFT JOIN {src}.{mode}.edges e ON e.edge_id = l.link_id" if lvl.startswith(", e.") else ""
        cols_ = _cols(con, g, "lane")
        # duckOSM's lane lines: geom to the nodes and geom_cut where SUMO ends the lane at its junction (the connectors meet it); a file
        # of the morning of 2026-10-10 had geom cut and geom_full to the nodes
        full = (", ST_AsWKB(l.geom_cut) AS geom_cut" if "geom_cut" in cols_ else "") + (", ST_AsWKB(l.geom_full) AS geom_full" if "geom_full" in cols_ else "")
        df = con.execute(
            f"SELECT l.lane_id::VARCHAR AS lane_id, k.facility_type AS highway, l.width AS width_m, "
            f"  COALESCE(l.allowed_uses, 'auto') AS use, "
            f"  CASE WHEN l.lane_num = 1 THEN k.name END AS name, "
            f"  l.link_id, l.lane_num, {nlanes}l.turn, k.from_node_id, k.to_node_id, "
            f"  (SELECT min(r.link_id) FROM {g}.link r WHERE r.from_node_id = k.to_node_id "
            f"     AND r.to_node_id = k.from_node_id AND r.link_id <> k.link_id{same}) AS reverse_link_id"
            f"  {lvl}, ST_AsWKB(l.geom) AS geom{full} "
            f"FROM {g}.lane l JOIN {g}.link k ON k.link_id = l.link_id {join} "
            f"WHERE l.geom IS NOT NULL ORDER BY l.link_id, l.lane_num").df()
        conn = None                    # duckOSM's lane connectors (docs/design/gmns_lane_connectors.md)
        if _cols(con, g, "lane_connector"):
            conn = con.execute(f"SELECT connector_id::VARCHAR AS lane_id, from_lane_id::VARCHAR AS from_lane, "
                               f"to_lane_id::VARCHAR AS to_lane, width AS width_m, ST_AsWKB(geom) AS geom "
                               f"FROM {g}.lane_connector WHERE geom IS NOT NULL").df()
        route = None                   # every road a footpath runs along (duckOSM's link_along), not only the one with the longest stretch
        if _cols(con, g, "link_along"):
            route = dict(con.execute(f"SELECT link_id, list(along_link_id) FROM {g}.link_along GROUP BY 1").fetchall())
        turns = pd.DataFrame({"from_lane": [], "to_lane": [], "type": []}, dtype=object)
        if _cols(con, g, "movement"):
            letter = "substr(m.mvmt_code, 3, 1)" if "mvmt_code" in _cols(con, g, "movement") else "NULL"      # the turn letter (L, T, R) of the GMNS movement code
            turns = con.execute(
                f"SELECT DISTINCT il.lane_id::VARCHAR AS from_lane, ol.lane_id::VARCHAR AS to_lane, m.type, {letter} AS code "
                f"FROM {g}.movement m "
                f"JOIN {g}.lane il ON il.link_id = m.ib_link_id AND (m.start_ib_lane IS NULL OR "
                f"  il.lane_num BETWEEN m.start_ib_lane AND COALESCE(m.end_ib_lane, m.start_ib_lane)) "
                f"JOIN {g}.lane ol ON ol.link_id = m.ob_link_id AND (m.start_ob_lane IS NULL OR "
                f"  m.start_ib_lane IS NULL OR ol.lane_num = m.start_ob_lane + il.lane_num - m.start_ib_lane) "
                f"ORDER BY 1, 2").df()
    finally:
        if lvl.startswith(", e."):
            con.execute(f"DETACH {src}")
        con.close()
    if "code" in turns:                          # a fork's branch says which way it goes in the code of its movement (duckOSM, docs/design/gmns_fork_letters.md): the arrow of its lane
        turns["turn"] = [{"L": "left", "T": "thru", "R": "right"}.get(c) if t == "diverge" else None for c, t in zip(turns["code"], turns["type"])]
        turns = turns.drop(columns="code")
    for c in [c for c in ("link_id", "reverse_link_id", "from_node_id", "to_node_id", "osm_id", "along_link_id") if c in df]:
        df[c] = df[c].astype("Int64")                       # BIGINT hash ids: never float64
    df["roundabout"] = df["link_id"].isin(_ring_links(source_db, mode))
    if route:
        df["along_links"] = df["link_id"].map(route)
    df["connector"] = False
    if conn is not None and len(conn):           # a connector looks like the lane it leaves
        lane_cols = [c for c in df.columns if c not in ("lane_id", "width_m", "name", "lane_num", "turn", "geom", "geom_cut", "geom_full",
                                                         "connector")]      # not its lane's lines: a connector has its own (2026-10-10: drawn on its lane's)
        conn = conn.merge(df[["lane_id"] + lane_cols].rename(columns={"lane_id": "from_lane"}), on="from_lane", how="left")
        conn["connector"] = True
        df = pd.concat([df, conn], ignore_index=True)
    for c in [c for c in ("link_id", "reverse_link_id", "from_node_id", "to_node_id", "osm_id", "along_link_id") if c in df]:
        df[c] = df[c].astype("Int64")
    for col, name in (("geom_full", "full_geometry"), ("geom_cut", "cut_geometry")):   # the other line of each lane (see above); a connector has none
        if col in df:
            df[name] = gpd.GeoSeries.from_wkb(df.pop(col).map(lambda b: bytes(b) if b is not None and b == b else None), crs=4326).values
    geom = gpd.GeoSeries.from_wkb(df.pop("geom").map(bytes), crs=4326)
    return gpd.GeoDataFrame(df, geometry=geom, crs=4326), turns


def read_boundary(db):
    """The area's boundary from a duckOSM database (``main.boundary``, written when the area was built
    with one) as a shapely geometry, or None. Pass it on: ``render_lanes(..., boundary=geom)``."""
    import duckdb
    from shapely import wkb

    con = duckdb.connect(str(db), read_only=True)
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
        if "geom" not in _cols(con, "main", "boundary"):
            return None
        row = con.execute("SELECT ST_AsWKB(ST_Union_Agg(geom)) FROM main.boundary").fetchone()
    finally:
        con.close()
    return wkb.loads(bytes(row[0])) if row and row[0] is not None else None


def boundary_from_geojson(path):
    """A GeoJSON file's geometries as one shapely geometry (plain json + shapely, no GDAL)."""
    import json

    import shapely
    from shapely.geometry import shape

    gj = json.loads(open(path, encoding="utf-8").read())
    feats = gj.get("features", [gj] if gj.get("type") == "Feature" else [{"geometry": gj}])
    return shapely.union_all([shape(f["geometry"]) for f in feats if f.get("geometry")])
