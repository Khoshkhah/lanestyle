"""The drawing order of the roads: roadstyle's casing and fill numbers of the links (docs/design/lanestyle_on_roadstyle_items.md).

A road is a link, a duckOSM edge (``edge_id`` = ``link_id``). Its numbers are read from ``visualization.edge_levels`` of the duckOSM file when it has them
(``duckosm levels``), else roadstyle computes them from the complete band and the class order. The items attached to a road (lanes, lines ...) take the fill number of their road.
"""
from __future__ import annotations

_SIDEWALK, _CROSSING = -1, 1
RING_TUNNEL_BOOST = 100                                         # a roundabout and a tunnel are over the roads they meet, whatever the classes
COLUMNS = ("casing_start", "casing_level", "casing_end", "fill_level")      # roadstyle's casing_start_col / casing_level_col / casing_end_col / fill_level_col


def tags_band(table):
    """The band of every row, complete (roadstyle's ``band_col`` replaces the level from the tags and a null is 0): the OSM ``layer`` if it is a number, else 1 for a bridge,
    -1 for a tunnel, else 0; except a mapped sidewalk (-1, under its street) and a crossing (1, over it). The same as duckOSM's and mapstyle's."""
    import numpy as np
    import pandas as pd

    def col(name):
        return table[name] if name in table else pd.Series([None] * len(table), index=table.index)

    def yes(s):
        return (s.notna() & ~s.astype(str).isin(["", "no", "None", "nan", "False", "false"])).to_numpy()
    layer = pd.to_numeric(col("layer"), errors="coerce").fillna(0).astype(int).to_numpy()
    tags = np.where(layer != 0, layer, np.where(yes(col("bridge")), 1, np.where(yes(col("tunnel")), -1, 0)))
    foot = col("footway").map({"sidewalk": _SIDEWALK, "crossing": _CROSSING}).fillna(0).astype(int).to_numpy()
    return np.where(foot != 0, foot, tags).astype(int)


def by_link(roads, link_ids):
    """The four numbers of ``roads`` (a table with ``edge_id`` and :data:`COLUMNS`) for each of ``link_ids`` (the link of a lane or a connector), as an array; NaN for a link that is not a road."""
    import numpy as np

    where = {int(e): k for k, e in enumerate(roads["edge_id"].to_numpy())}
    nums = roads[list(COLUMNS)].to_numpy(dtype=float)
    return np.array([nums[where[int(i)]] if int(i) in where else [np.nan] * len(COLUMNS) for i in link_ids])


def road_order(roads):
    """The order of every road, for roadstyle's ``order=`` column: where two roads of one band meet, the higher number has the later fill. It is roadstyle's class order (higher = on top), plus
    :data:`RING_TUNNEL_BOOST` for a roundabout (``roundabout``) and for a tunnel (the tunnel tag), whatever the class. A road with no class has none (NaN: no wish for it)."""
    import numpy as np
    import pandas as pd
    from roadstyle.levels import _class_order

    order = np.array([np.nan if pd.isna(h) else _class_order(h) for h in roads["highway"]], dtype=float)
    ring = roads["roundabout"].fillna(False).astype(bool).to_numpy() if "roundabout" in roads else np.zeros(len(roads), bool)
    tunnel = roads["tunnel"].notna() & ~roads["tunnel"].astype(str).isin(["", "no", "None", "nan", "False", "false"]) if "tunnel" in roads else pd.Series(False, index=roads.index)
    return order + RING_TUNNEL_BOOST * (ring | tunnel.to_numpy())


def stored_levels(roads, source_db):
    """The four numbers of ``visualization.edge_levels`` (``duckosm levels``) for each road, in the order of ``roads``, as the table has them for the road's ``edge_id`` (mapstyle reads
    the same rows, as they are); None when the file has no such table. An edge the table lacks is an error (the file was rebuilt): run ``duckosm levels`` again."""
    import duckdb
    import pandas as pd

    con = duckdb.connect(str(source_db), read_only=True)
    try:
        if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'visualization' AND table_name = 'edge_levels'").fetchone()[0]:
            return None
        table = con.execute(f"SELECT edge_id, {', '.join(COLUMNS)} FROM visualization.edge_levels").df().set_index("edge_id")
    finally:
        con.close()
    ids = roads["edge_id"].astype("int64")
    if not ids.isin(table.index).all():
        raise ValueError(f"{int((~ids.isin(table.index)).sum())} roads have no row in {source_db}'s visualization.edge_levels (first: {ids[~ids.isin(table.index)].iloc[:3].tolist()}); run `duckosm levels {source_db}` again")
    return pd.DataFrame(table.loc[ids, list(COLUMNS)].to_numpy(dtype=int), columns=list(COLUMNS))


def stored_head_m(source_db):
    """The head length (metres) the stored numbers were computed with (``visualization.edge_levels_meta``), or None: the page must cut the casing heads at the same length, or the numbers and the heads do not belong together."""
    import duckdb

    if not source_db:
        return None
    con = duckdb.connect(str(source_db), read_only=True)
    try:
        row = con.execute("SELECT head_m FROM visualization.edge_levels_meta").fetchone()
    except duckdb.Error:
        return None
    finally:
        con.close()
    return float(row[0]) if row and row[0] is not None else None


def own_levels(link_ids, source_db):
    """The four numbers of ``visualization.edge_levels`` for each of ``link_ids`` (the link of a lane), as an array; NaN for a link the table lacks (a connector's) and for a file with no table.
    A street's two directions are one road for drawing, but each link has its own row, the heads in its own direction: this is what the popup shows."""
    import duckdb
    import numpy as np

    out = np.full((len(link_ids), len(COLUMNS)), np.nan)
    if not source_db:
        return out
    con = duckdb.connect(str(source_db), read_only=True)
    try:
        if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'visualization' AND table_name = 'edge_levels'").fetchone()[0]:
            return out
        table = con.execute(f"SELECT edge_id, {', '.join(COLUMNS)} FROM visualization.edge_levels").df().set_index("edge_id")
    finally:
        con.close()
    where = {int(e): k for k, e in enumerate(table.index)}
    nums = table[list(COLUMNS)].to_numpy(dtype=float)
    for n, i in enumerate(link_ids):
        if int(i) in where:
            out[n] = nums[where[int(i)]]
    return out


def link_levels(roads, source_db=None, head_m=5.0):
    """roadstyle's four numbers for each road, as a table of :data:`COLUMNS` in the order of ``roads``: those of duckOSM's ``visualization.edge_levels`` (:func:`stored_levels`), the
    same numbers mapstyle draws; when ``source_db`` is None or has no such table, computed from the complete band (``roads["band"]``) and :func:`road_order`."""
    import roadstyle as rs

    stored = stored_levels(roads, source_db) if source_db else None
    if stored is not None:
        return stored
    frame = roads[["geometry", "highway", "band"]].copy()
    frame["order"] = road_order(roads)
    out = rs.compute_levels(frame, band_col="band", order="order", head_m=head_m)
    return out[list(COLUMNS)].astype(int).reset_index(drop=True)
