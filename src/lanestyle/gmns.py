"""The GMNS reader: a duckOSM GMNS database -> the lane table and turns render_lanes draws."""


def _cols(con, schema, table, db=None):
    q = "SELECT column_name FROM duckdb_columns() WHERE schema_name = ? AND table_name = ?"
    args = [schema, table]
    if db:
        q, args = q + " AND database_name = ?", args + [db]
    return {c for (c,) in con.execute(q, args).fetchall()}


def from_gmns(gmns_db, mode="driving", source_db=None):
    """Read ``gmns_<mode>.lane`` / ``.link`` / ``.movement`` into ``(lanes, turns)``.

    ``lanes``: a GeoDataFrame, one row per lane (EPSG:4326, each line in the direction of travel)
    with ``lane_id``, ``highway`` (the link's ``facility_type``), ``width_m`` (``lane.width``; null
    where untagged, render_lanes fills the default), ``use``, ``name`` (lane 1 only: one label per
    road), ``link_id``, ``lane_num``, ``turn`` and, when known, ``bridge`` / ``tunnel`` / ``layer``.

    Levels come from the GMNS ``link`` if it has those columns, else from ``source_db`` (the
    duckOSM database the GMNS file was made from: ``link_id`` = ``<mode>.edges.edge_id``), else
    every lane is at ground level (no level columns).

    ``turns``: a DataFrame ``from_lane``, ``to_lane``, ``type`` (the movement type; ``uturn`` is
    drawn in its own colour), from ``movement``: each lane of the inbound link in
    ``start_ib_lane``..``end_ib_lane`` to each lane of the outbound link in
    ``start_ob_lane``..``end_ob_lane`` (NULL = every lane). Empty without a movement table."""
    import duckdb
    import geopandas as gpd
    import pandas as pd

    g = f"gmns_{mode}"
    con = duckdb.connect(str(gmns_db), read_only=True)
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
        if not _cols(con, g, "lane"):
            raise ValueError(f"no '{g}.lane' in {gmns_db}: build a GMNS db first (duckOSM `duckosm gmns`)")
        lvl = ""
        if {"bridge", "tunnel", "layer"} <= _cols(con, g, "link"):
            lvl = ", k.bridge, k.tunnel, k.layer"
        elif source_db:
            con.execute(f"ATTACH '{str(source_db).replace(chr(39), chr(39) * 2)}' AS s (READ_ONLY)")
            if not {"edge_id", "bridge", "tunnel", "layer"} <= _cols(con, mode, "edges", db="s"):
                raise ValueError(f"no {mode}.edges with bridge / tunnel / layer in {source_db}")
            lvl = ", e.bridge, e.tunnel, e.layer"
        join = f"LEFT JOIN s.{mode}.edges e ON e.edge_id = l.link_id" if lvl.startswith(", e.") else ""
        df = con.execute(
            f"SELECT l.lane_id::VARCHAR AS lane_id, k.facility_type AS highway, l.width AS width_m, "
            f"  COALESCE(l.allowed_uses, 'auto') AS use, "
            f"  CASE WHEN l.lane_num = 1 THEN k.name END AS name, "
            f"  l.link_id, l.lane_num, l.turn{lvl}, ST_AsWKB(l.geom) AS geom "
            f"FROM {g}.lane l JOIN {g}.link k ON k.link_id = l.link_id {join} "
            f"WHERE l.geom IS NOT NULL ORDER BY l.link_id, l.lane_num").df()
        turns = pd.DataFrame({"from_lane": [], "to_lane": [], "type": []}, dtype=object)
        if _cols(con, g, "movement"):
            turns = con.execute(
                f"SELECT DISTINCT il.lane_id::VARCHAR AS from_lane, ol.lane_id::VARCHAR AS to_lane, m.type "
                f"FROM {g}.movement m "
                f"JOIN {g}.lane il ON il.link_id = m.ib_link_id AND (m.start_ib_lane IS NULL OR "
                f"  il.lane_num BETWEEN m.start_ib_lane AND COALESCE(m.end_ib_lane, m.start_ib_lane)) "
                f"JOIN {g}.lane ol ON ol.link_id = m.ob_link_id AND (m.start_ob_lane IS NULL OR "
                f"  ol.lane_num BETWEEN m.start_ob_lane AND COALESCE(m.end_ob_lane, m.start_ob_lane)) "
                f"ORDER BY 1, 2").df()
    finally:
        con.close()
    df["link_id"] = df["link_id"].astype("Int64")          # BIGINT hash ids: never float64
    geom = gpd.GeoSeries.from_wkb(df.pop("geom").map(bytes), crs=4326)
    return gpd.GeoDataFrame(df, geometry=geom, crs=4326), turns
