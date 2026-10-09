"""The lanes in roadstyle's level editor: the editor draws its roads as roadstyle's twin version (each direction its own casing and fill, in
metres from the lanes), and the lanes and connectors are items UNDER them, not seen: for picking a lane and showing a route (2026-10-10).

    LANESTYLE_GMNS=monaco_gmns.duckdb LANESTYLE_SOURCE_DB=monaco.duckdb \\
        roadstyle-levels edit AREA --items lanestyle.editor:lane_items

The GMNS file and its duckOSM source come from those two environment variables (``link_id`` = duckOSM ``edge_id`` = the editor's edge ids).
"""
import os
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _strokes(gmns, source_db, connectors=False):
    """The lane table's lanes as items (lanestyle.items.lane_strokes), each on its link (``edge_id``), and each link's width in metres and line.
    ``connectors``: also duckOSM's lane connectors (SUMO's paths through the junctions) as items of the link they leave."""
    import lanestyle as ls
    from lanestyle import items
    from lanestyle.lines import _level
    from lanestyle.render import _colour_groups, _roads_only, _widths, lane_settings

    s = lane_settings()
    lanes, turns = ls.from_gmns(gmns, source_db=source_db)
    base = _roads_only(lanes).copy()                      # every lane on its line to its nodes
    base["use"] = base["use"].fillna("auto") if "use" in base else "auto"
    base["width_m"] = _widths(base, s)
    isconn = base["connector"].fillna(False).astype(bool) if "connector" in base else None
    g, conn_fc = base, None
    if connectors and isconn is not None and isconn.any():
        cc, cp, _ = _colour_groups(g, s)
        conn_fc = items.connector_strokes(g[isconn], g.loc[isconn, cc].map(cp), s["tunnel_body"], ["lane_id", "from_lane", "to_lane"],
                                          dict(zip(g["lane_id"], g["width_m"])), level_of=_level)
    if isconn is not None:                                # the lanes without the connectors
        g, base = g[~isconn.values], base[~isconn.values]
    colour_col, palette_colors, _ = _colour_groups(g, s)
    # the road (its casing) on the lanes' full lines, to the nodes, whatever is drawn: SUMO cuts a road's two directions at different
    # places, so the middle of their cut lines is skewed and short (2026-10-10, connectors on: casings and lanes did not match)
    roads = items.link_roads(base, float(s["casing_m"]), float(s["centre_line_m"]))
    road_of = roads.attrs["road_of"]
    lane_fc, _ = items.lane_strokes(g, g[colour_col].map(palette_colors), s["tunnel_body"], ["name", "lane_id", "lane_num", "use", "width_m", "link_id"],
                                          road_of, float(s["centre_line_m"]), s["lines"] or {"divider": False, "centre": False},
                                          float(s["junction_trim_m"]), level_of=_level, ext=roads.attrs["ext"])
    two = items.two_way_links(road_of)
    width = {str(lk): float(w) + 2 * float(s["casing_m"]) + (float(s["centre_line_m"]) / 2 if int(lk) in two else 0.0)
             for lk, w in g.groupby("link_id")["width_m"].sum().items()}
    # the casing's line, as the lane page: the middle of the carriageway (link_roads), the reverse link's backwards (GMNS moves a one-way
    # carriageway's lanes off its OSM line where an opposite one runs close by: on the OSM line the casing missed its lanes, 2026-10-10)
    from shapely.geometry import LineString
    line = dict(zip(roads["edge_id"].astype(int), roads.geometry, strict=True))
    lines = {str(lk): (line[rd] if lk == rd else LineString(list(line[rd].coords)[::-1])) for lk, rd in road_of.items() if rd in line}
    return lane_fc, width, lines, conn_fc


def lane_items(roads):
    """The editor's hook (roadstyle.level_editor): the roads as roadstyle's twin version in metres (each direction its own casing and fill,
    ``twin_casing`` "each"), at their lanes' width (``width_m``) on the lanes' line; the lanes of ``LANESTYLE_GMNS`` (and with
    ``LANESTYLE_CONNECTORS=1`` its connectors) as items of the editor's edges under them, unseen, for picking and route highlights, each
    labelled with its road (``road``: one for both directions). The lanes of a link that is no edge of the editor's area are left out, and
    their count printed."""
    import roadstyle as rs

    gmns, src = os.environ.get("LANESTYLE_GMNS"), os.environ.get("LANESTYLE_SOURCE_DB")
    if not gmns:
        raise ValueError("lanestyle.editor.lane_items: set LANESTYLE_GMNS to the GMNS .duckdb (and LANESTYLE_SOURCE_DB to its duckOSM file)")
    on = os.environ.get("LANESTYLE_CONNECTORS") == "1"
    lane_fc, width, lines, conn_fc = _strokes(gmns, src, on)
    road_of = dict(zip(roads["edge"].astype(str), roads["road"].astype(str)))

    def under(fc):          # on the editor's edges, labelled with their road, unseen (a transparent colour): picked and highlighted only
        fs = [{**f, "properties": {**f["properties"], "road_id": str(f["properties"]["edge_id"]), "road": road_of.get(str(f["properties"]["edge_id"])),
                                   "color": "rgba(0,0,0,0)"}} for f in fc["features"]]
        out = [f for f in fs if f["properties"]["road"] is not None]
        if len(out) < len(fs):
            print(f"lanestyle.editor: {len(fs) - len(out)} of {len(fs)} items are on links that are no edge of the area: left out", flush=True)
        return {"type": "FeatureCollection", "features": out}

    roads["width_m"] = [width.get(e, np.nan) for e in roads["edge"].astype(str)]
    roads.geometry = [lines.get(e, g) for e, g in zip(roads["edge"].astype(str), roads.geometry, strict=True)]
    m = dict(edge_col="road_id", order_col="order", color_col="color", width_m_col="width_m", offset_m_col="offset_m", select="item")
    overlays = [rs.Overlay(under(lane_fc), label="lanes", popup=["road", "name", "lane_id", "lane_num", "use", "width_m", "link_id"], **m)]
    if conn_fc:
        overlays.append(rs.Overlay(under(conn_fc), label="connectors", popup=["road", "lane_id", "from_lane", "to_lane"], **m))
    from lanestyle.render import lane_settings
    s = lane_settings()
    # metres at every zoom (width_m_zoom 0) and lanestyle's casing; no roadstyle one-way chevrons or street names
    kw = {"width_m_col": "width_m", "width_m_zoom": 0, "casing_m": float(s["casing_m"]), "casing_min_px": float(s["casing_min_px"]), "arrows": False,
          "labels": False, "settings": {"config": {"twin_casing": "each"}}}
    test = os.environ.get("LANESTYLE_CASING_COLOR")       # a casing colour of its own for inspecting (2026-10-10)
    if test:
        pal = {c: {**v, "casing": test} for c, v in rs.palette_to_dict("amber").items()}
        cfg = {"twin_casing": "each", "bridge_casing_color": test}
        tun = os.environ.get("LANESTYLE_TUNNEL_CASING")     # "dash,gap": a tunnel casing's two colours
        if tun:
            cfg.update(tunnel_palettes={"lanestyle_test": tun.split(",")}, tunnel_palette="lanestyle_test")
        kw.update(palette="lanestyle_test", settings={"palettes": {"lanestyle_test": pal}, "config": cfg})
    return overlays, kw
