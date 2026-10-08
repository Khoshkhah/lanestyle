"""The lanes in roadstyle's level editor: the editor draws its roads, this puts the lanes and lane lines on them as items (no connectors).

    LANESTYLE_GMNS=monaco_gmns.duckdb LANESTYLE_SOURCE_DB=monaco.duckdb \\
        roadstyle-levels edit AREA --items lanestyle.editor:lane_items

The GMNS file and its duckOSM source come from those two environment variables (``link_id`` = duckOSM ``edge_id`` = the editor's edge ids).
"""
import os
from collections import Counter
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _strokes(gmns, source_db):
    """The lane table's lanes and lines as items (lanestyle.items.lane_strokes), each on its link (``edge_id``), and each link's width in metres."""
    import lanestyle as ls
    from lanestyle import items
    from lanestyle.lines import _level
    from lanestyle.arrows import mark_strokes
    from lanestyle.render import _colour_groups, _roads_only, _widths, full_lanes, lane_settings

    s = lane_settings()
    lanes, turns = ls.from_gmns(gmns, source_db=source_db)
    g = full_lanes(_roads_only(lanes), {**s, "connectors": False}).copy()       # the editor shows no connectors: the lanes to their nodes
    g["use"] = g["use"].fillna("auto") if "use" in g else "auto"
    g["width_m"] = _widths(g, s)
    if "connector" in g:                                  # the editor shows the roads: no connectors
        g = g[~g["connector"].fillna(False).astype(bool)]
    colour_col, palette_colors, _ = _colour_groups(g, s)
    roads = items.link_roads(g, float(s["casing_m"]), float(s["centre_line_m"]))
    road_of = roads.attrs["road_of"]
    lane_fc, line_fc = items.lane_strokes(g, g[colour_col].map(palette_colors), s["tunnel_body"], ["name", "lane_id", "lane_num", "use", "width_m", "link_id"],
                                          road_of, float(s["centre_line_m"]), s["lines"] or {"divider": False, "centre": False},
                                          float(s["junction_trim_m"]), level_of=_level, ext=roads.attrs["ext"])
    marks_fc = mark_strokes(g, turns, s.get("arrows"), items.lane_shifts(g.reset_index(drop=True), road_of, float(s["centre_line_m"])))   # as the lane page
    two = items.two_way_links(road_of)
    width = {str(lk): float(w) + 2 * float(s["casing_m"]) + (float(s["centre_line_m"]) / 2 if int(lk) in two else 0.0)
             for lk, w in g.groupby("link_id")["width_m"].sum().items()}
    return lane_fc, line_fc, marks_fc, width


def lane_items(roads):
    """The editor's hook (roadstyle.level_editor): the lanes and lane lines of ``LANESTYLE_GMNS`` as items of the editor's edges (``roads["edge"]``), and
    each edge with lanes at their width (``width_m``). The lanes of a link that is no edge of the editor's area are left out, and their count printed."""
    import roadstyle as rs

    gmns, src = os.environ.get("LANESTYLE_GMNS"), os.environ.get("LANESTYLE_SOURCE_DB")
    if not gmns:
        raise ValueError("lanestyle.editor.lane_items: set LANESTYLE_GMNS to the GMNS .duckdb (and LANESTYLE_SOURCE_DB to its duckOSM file)")
    lane_fc, line_fc, marks_fc, width = _strokes(gmns, src)
    edges = set(roads["edge"].astype(str))

    def on_edges(fc):
        fs = [{**f, "properties": {**f["properties"], "road_id": str(f["properties"]["edge_id"])}} for f in fc["features"]]
        out = [f for f in fs if f["properties"]["road_id"] in edges]
        if len(out) < len(fs):
            print(f"lanestyle.editor: {len(fs) - len(out)} of {len(fs)} items are on links that are no edge of the area: left out", flush=True)
        return {"type": "FeatureCollection", "features": out}

    roads["width_m"] = [width.get(e, np.nan) for e in roads["edge"].astype(str)]
    m = dict(edge_col="road_id", order_col="order", color_col="color", width_m_col="width_m", offset_m_col="offset_m")
    overlays = [rs.Overlay(on_edges(lane_fc), label="lanes", popup=["name", "lane_id", "lane_num", "use", "width_m", "link_id"], select="item", **m),
                rs.Overlay(on_edges(line_fc), label="lane lines", popup=[], **m)]
    if marks_fc:
        overlays.append(rs.Overlay(on_edges(marks_fc), label="lane marks", popup=[], **m))
    # as the lane page: no road fill (the lanes are the surface), no roadstyle one-way chevrons or street names (lanestyle draws its own marks)
    from lanestyle.render import lane_settings
    # metres at every zoom (width_m_zoom 0) and lanestyle's casing, as the lane page
    kw = {"width_m_col": "width_m", "width_m_zoom": 0, "casing_m": float(lane_settings()["casing_m"]), "road_fill": False, "arrows": False, "labels": False}
    test = os.environ.get("LANESTYLE_CASING_COLOR")       # a casing colour of its own for inspecting (2026-10-10: grey lanes, grey casings)
    if test:
        pal = {c: {**v, "casing": test} for c, v in rs.palette_to_dict("amber").items()}
        cfg = {"bridge_casing_color": test}
        tun = os.environ.get("LANESTYLE_TUNNEL_CASING")     # "dash,gap": a tunnel casing's two colours
        if tun:
            cfg.update(tunnel_palettes={"lanestyle_test": tun.split(",")}, tunnel_palette="lanestyle_test")
        kw.update(palette="lanestyle_test", settings={"palettes": {"lanestyle_test": pal}, "config": cfg})
    return overlays, kw
