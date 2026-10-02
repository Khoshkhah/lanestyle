"""The GMNS reader: a duckOSM GMNS database -> the lane table and turns render_lanes draws."""


def _cols(con, schema, table, db=None):
    q = "SELECT column_name FROM duckdb_columns() WHERE schema_name = ? AND table_name = ?"
    args = [schema, table]
    if db:
        q, args = q + " AND database_name = ?", args + [db]
    return {c for (c,) in con.execute(q, args).fetchall()}


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
    """:func:`_from_gmns` plus the crossings in ``lanes.attrs["crossings"]`` (see :func:`read_crossings`)."""
    lanes, turns = _from_gmns(gmns_db, mode, source_db, modes)
    lanes.attrs["crossings"] = read_crossings(gmns_db) if "driving" in (modes or [mode]) else None
    return lanes, turns


def _from_gmns(gmns_db, mode="driving", source_db=None, modes=None):
    """Read ``gmns_<mode>`` into ``(lanes, turns)``; the columns are described on :func:`_from_gmns_mode` below.

    ``modes`` reads several modes into one table, e.g. ``("driving", "walking")``: the first is read as it is, each
    later one adds only the lanes of links the earlier ones do not have (a footpath, not the road you also walk
    on: nor that road's other direction, the walking network's link of a one-way road, which has its OSM way, ``osm_id``,
    in common with the earlier mode's link), and only the turns between lanes that are kept. A ``modes`` column says which of them have the link
    (``"driving,walking"``: a street cars and pedestrians share), which ``render_lanes`` colours by. ``modes`` wins
    over ``mode``."""
    if not modes:
        return _from_gmns_mode(gmns_db, mode, source_db)
    import geopandas as gpd
    import pandas as pd

    tables, turn_tables, seen, seen_ways, modes_of, way_of = [], [], set(), set(), {}, {}
    for i, m in enumerate(modes):
        lanes, turns = _from_gmns_mode(gmns_db, m, source_db)
        for link in set(lanes["link_id"].dropna()):      # every mode whose network has the link, kept or not
            modes_of.setdefault(link, []).append(m)
        if "osm_id" in lanes:
            way_of.update(zip(lanes["link_id"], lanes["osm_id"]))
        if i:
            lanes = lanes[~lanes["link_id"].isin(seen)]
            if "osm_id" in lanes:
                lanes = lanes[~lanes["osm_id"].isin(seen_ways)]
        seen |= set(lanes["link_id"].dropna())
        if "osm_id" in lanes:
            seen_ways |= set(lanes["osm_id"].dropna())
        tables.append(lanes)
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
    lanes = _join_footways(lanes)
    turns = pd.concat(turn_tables, ignore_index=True)
    keep = set(lanes["lane_id"])
    return lanes, turns[turns["from_lane"].isin(keep) & turns["to_lane"].isin(keep)].reset_index(drop=True)


def _join_footways(lanes, max_gap_m=6.0, min_gap_m=0.3):
    """A short connector where a footway and a road meet at a node of the data but their lanes don't: a road lane sits
    beside its link's line, a footway lane on it, so the two ends are up to a lane width apart. Only at a node both links
    share (never a link OSM does not map), one per footway end, to the nearest road lane end; the connector is a lane of
    the footway's kind (``connector`` True, ``from_lane`` the road lane, ``to_lane`` the footway)."""
    import math

    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString, Point

    need = {"from_node_id", "to_node_id", "use", "connector"}
    if not need <= set(lanes.columns) or "walk" not in set(lanes["use"]):
        return lanes
    kx = math.cos(math.radians(lanes.geometry.iloc[0].coords[0][1])) * 111320.0
    ends = {}                                        # node -> [(lane index, is_walk, end point)]
    for i, (g, a, b, use, conn) in enumerate(zip(lanes.geometry, lanes["from_node_id"], lanes["to_node_id"],
                                                 lanes["use"], lanes["connector"])):
        if conn or g is None or g.geom_type != "LineString":
            continue
        for node, pt in ((a, Point(g.coords[0])), (b, Point(g.coords[-1]))):
            if pd.notna(node):
                ends.setdefault(node, []).append((i, use == "walk", pt))
    dist = lambda p, q: math.hypot((p.x - q.x) * kx, (p.y - q.y) * 111320.0)       # noqa: E731
    rows, seen = [], set()
    for node, es in ends.items():
        for i, walk, pt in es:
            if not walk:
                continue
            roads = [(dist(pt, q), j, q) for j, w, q in es if not w]
            if not roads:
                continue
            d, j, q = min(roads, key=lambda r: r[0])
            key = (round(pt.x, 7), round(pt.y, 7), round(q.x, 7), round(q.y, 7))
            if min_gap_m < d <= max_gap_m and key not in seen:
                seen.add(key)
                row = lanes.iloc[i].copy()
                row["from_lane"], row["to_lane"] = lanes.iloc[j]["lane_id"], lanes.iloc[i]["lane_id"]
                row["lane_id"] = f"{row['from_lane']}>{row['to_lane']}"
                row["connector"], row["geometry"] = True, LineString([q, pt])
                row["width_m"] = float("nan")             # the footway's width, by use
                rows.append(row)
    if not rows:
        return lanes
    new = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs=lanes.crs)
    return pd.concat([lanes, new], ignore_index=True)


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

    ``turns``: a DataFrame ``from_lane``, ``to_lane``, ``type`` (the movement type; ``uturn`` is
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
        df = con.execute(
            f"SELECT l.lane_id::VARCHAR AS lane_id, k.facility_type AS highway, l.width AS width_m, "
            f"  COALESCE(l.allowed_uses, 'auto') AS use, "
            f"  CASE WHEN l.lane_num = 1 THEN k.name END AS name, "
            f"  l.link_id, l.lane_num, {nlanes}l.turn, k.from_node_id, k.to_node_id, "
            f"  (SELECT min(r.link_id) FROM {g}.link r WHERE r.from_node_id = k.to_node_id "
            f"     AND r.to_node_id = k.from_node_id AND r.link_id <> k.link_id{same}) AS reverse_link_id"
            f"  {lvl}, ST_AsWKB(l.geom) AS geom "
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
            turns = con.execute(
                f"SELECT DISTINCT il.lane_id::VARCHAR AS from_lane, ol.lane_id::VARCHAR AS to_lane, m.type "
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
    for c in [c for c in ("link_id", "reverse_link_id", "from_node_id", "to_node_id", "osm_id", "along_link_id") if c in df]:
        df[c] = df[c].astype("Int64")                       # BIGINT hash ids: never float64
    if route:
        df["along_links"] = df["link_id"].map(route)
    df["connector"] = False
    if conn is not None and len(conn):           # a connector looks like the lane it leaves
        lane_cols = [c for c in df.columns if c not in ("lane_id", "width_m", "name", "lane_num", "turn", "geom",
                                                         "connector")]
        conn = conn.merge(df[["lane_id"] + lane_cols].rename(columns={"lane_id": "from_lane"}), on="from_lane", how="left")
        conn["connector"] = True
        df = pd.concat([df, conn], ignore_index=True)
    for c in [c for c in ("link_id", "reverse_link_id", "from_node_id", "to_node_id", "osm_id", "along_link_id") if c in df]:
        df[c] = df[c].astype("Int64")
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
