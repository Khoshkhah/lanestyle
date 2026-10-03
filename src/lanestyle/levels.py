"""The drawing order of each road as an interval (docs/design/interval_draw_order.md): mapstyle's ``node_levels`` -> roadstyle's
``casing_level_col`` / ``fill_level_col``."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)
SCALE = 2          # the positions are doubled, as mapstyle does: the odd ones stay free (a crossing sits between two roads' positions)


def link_intervals(source_db):
    """``({link_id: (casing, fill)}, cuts)``: the interval of every duckOSM edge of ``source_db`` that is not ``(0, 0)`` (anything missing is ``(0, 0)``), positions doubled,
    and ``{road id: {"bounds": [m...], "intervals": [(casing, fill)...], "edges": [link ids]}}`` for the roads that change level along themselves and must be drawn in pieces
    (piece i runs ``bounds[i]`` to ``bounds[i + 1]`` metres along the road's line; such a road is not in the first dict). ``({}, {})`` without mapstyle
    (``pip install -e ../mapstyle``) or when the database has no edges to order."""
    try:
        from mapstyle.node_levels import compute
    except ImportError:
        log.warning("mapstyle is not installed: roads are drawn without the per-edge drawing order (pip install -e ../mapstyle)")
        return {}, {}
    import duckdb

    try:
        levels = compute(source_db)
    except (ValueError, duckdb.Error) as e:             # no <mode>.edges in the database, or not a full duckOSM one (source / target / geometry)
        log.warning("drawing order skipped: %s", e)
        return {}, {}
    cuts = {r: {"bounds": c["bounds"], "intervals": [(SCALE * a, SCALE * b) for a, b in c["intervals"]], "edges": [int(e) for e in c["edges"]]} for r, c in levels.cuts.items()}
    return {int(e): (SCALE * a, SCALE * b) for e, (a, b) in levels.intervals.items()}, cuts


def cut_lanes(lanes, cuts):
    """The lanes of the cut roads in pieces (drawing only, the data is not touched): the row of a lane becomes its first piece, the other pieces are appended with ``piece`` True
    and the same ``lane_id``. A piece takes the fractions of the road's length given by ``cuts`` (the metres of the road's own line over its total), reversed for a lane that runs the
    other way than the road's first edge. Each piece has its interval."""
    import pandas as pd
    from shapely.ops import substring

    lanes = lanes.copy()
    lanes["piece"] = False
    extra = []
    for c in cuts.values():
        bounds, total = c["bounds"], c["bounds"][-1] or 1.0
        rep = None
        for e in c["edges"]:
            for i in lanes.index[lanes["link_id"] == e]:
                g = lanes.at[i, "geometry"]
                if g is None or g.geom_type != "LineString":
                    continue
                rep = rep or g
                same = (g.coords[0][0] - rep.coords[0][0]) ** 2 + (g.coords[0][1] - rep.coords[0][1]) ** 2 <= (g.coords[0][0] - rep.coords[-1][0]) ** 2 + (g.coords[0][1] - rep.coords[-1][1]) ** 2
                for n, (a, b) in enumerate(c["intervals"]):
                    lo, hi = (bounds[n], bounds[n + 1]) if same else (total - bounds[n + 1], total - bounds[n])
                    part = substring(g, lo / total, hi / total, normalized=True)
                    if part.is_empty or part.geom_type != "LineString":
                        continue
                    if n == 0:
                        lanes.at[i, "geometry"], lanes.at[i, "pos_casing"], lanes.at[i, "pos_fill"] = part, a, b
                    else:
                        row = lanes.loc[i].copy()
                        row["geometry"], row["pos_casing"], row["pos_fill"], row["piece"] = part, a, b, True
                        extra.append(row)
    if extra:
        import geopandas as gpd

        lanes = gpd.GeoDataFrame(pd.concat([lanes, pd.DataFrame(extra)], ignore_index=True), geometry="geometry", crs=lanes.crs)
    return lanes
