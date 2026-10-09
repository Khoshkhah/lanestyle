"""The lanes in roadstyle's level editor: the editor draws its roads, this puts the lanes and lane lines on them as items (no connectors).

    LANESTYLE_GMNS=monaco_gmns.duckdb LANESTYLE_SOURCE_DB=monaco.duckdb \\
        roadstyle-levels edit AREA --items lanestyle.editor:lane_items

The GMNS file and its duckOSM source come from those two environment variables (``link_id`` = duckOSM ``edge_id`` = the editor's edge ids).
"""
import os
from collections import Counter
from functools import lru_cache

import numpy as np


def _junction_plan(lanes, turns):
    """The junction rule with connectors on (2026-10-10): a lane runs on to its node at an end where traffic goes STRAIGHT into the
    same lane number (straight, a merge, a fork's straight branch), else it stops where SUMO cut it; a connector is drawn for a turn
    (left, right, a fork's side branch) and for straight on into another lane number (SUMO's short S-curve), never for a U-turn or plain
    straight on. ``lanes``: the lane table (lanes and connectors, ``from_lane`` / ``to_lane``), ``turns``: from_gmns' (``type``, ``turn``).
    Returns ``(runs_out, runs_in, drawn)``: the lanes that run on at their end / start, the connector ids drawn."""
    num = {k: n for k, n, c in zip(lanes["lane_id"], lanes.get("lane_num", [None] * len(lanes)), lanes.get("connector", [False] * len(lanes))) if not c}
    kind = {}
    for a, b, t, tn in zip(turns["from_lane"], turns["to_lane"], turns["type"], turns["turn"] if "turn" in turns else [None] * len(turns)):
        straight = t in ("thru", "merge") or (t == "diverge" and tn == "thru")
        kind[(str(a), str(b))] = "uturn" if t == "uturn" else ("straight" if straight else "turn")
    runs_out, runs_in = set(), set()
    for (a, b), k in kind.items():
        if k == "straight" and num.get(a) is not None and num.get(a) == num.get(b):
            runs_out.add(a)
            runs_in.add(b)
    drawn = set()
    if "connector" in lanes:
        for cid, a, b in lanes.loc[lanes["connector"].fillna(False).astype(bool), ["lane_id", "from_lane", "to_lane"]].itertuples(index=False):
            k = kind.get((str(a), str(b)), "turn")
            if k == "turn" or (k == "straight" and num.get(str(a)) != num.get(str(b))):
                drawn.add(cid)
    return runs_out, runs_in, drawn


def _trim_to_plan(g, runs_out, runs_in):
    """Each lane on its full line, cut at an end only where it does not run on (where SUMO cut it: ``cut_geometry``'s end, projected on the line)."""
    from shapely.geometry import Point
    from shapely.ops import substring
    g = g.copy()
    out = []
    for lid, full, cut in zip(g["lane_id"], g.geometry, g["cut_geometry"] if "cut_geometry" in g else [None] * len(g)):
        if cut is None or full is None or (lid in runs_out and lid in runs_in) or cut != cut:
            out.append(full)
            continue
        a = 0.0 if lid in runs_in else full.project(Point(cut.coords[0]))
        b = full.length if lid in runs_out else full.project(Point(cut.coords[-1]))
        out.append(substring(full, a, b) if b > a else full)
    g["geometry"] = out
    return g


@lru_cache(maxsize=1)
def _strokes(gmns, source_db, connectors=False):
    """The lane table's lanes and lines as items (lanestyle.items.lane_strokes), each on its link (``edge_id``), and each link's width in metres.
    ``connectors``: the lanes on their lines where the junction begins and duckOSM's lane connectors (SUMO's paths through the junction) as items
    of the link they leave; else the lanes to their nodes and no connectors."""
    import lanestyle as ls
    from lanestyle import items
    from lanestyle.lines import _level
    from lanestyle.arrows import mark_strokes
    from lanestyle.render import _colour_groups, _roads_only, _widths, full_lanes, lane_settings

    s = lane_settings()
    lanes, turns = ls.from_gmns(gmns, source_db=source_db)
    base = _roads_only(lanes).copy()                      # every lane on its line to its nodes
    base["use"] = base["use"].fillna("auto") if "use" in base else "auto"
    base["width_m"] = _widths(base, s)
    isconn = base["connector"].fillna(False).astype(bool) if "connector" in base else None
    g, conn_fc = base, None
    if connectors and isconn is not None and isconn.any():
        runs_out, runs_in, drawn = _junction_plan(base, turns)
        g = _trim_to_plan(base, runs_out, runs_in)          # a lane runs on to its node where traffic goes straight on into its lane number
        keep = isconn & g["lane_id"].isin(drawn)
        cc, cp, _ = _colour_groups(g, s)
        conn_fc = items.connector_strokes(g[keep], g.loc[keep, cc].map(cp), s["tunnel_body"], ["lane_id"], dict(zip(g["lane_id"], g["width_m"])), level_of=_level)
        conn_fc = _with_casing(conn_fc, g[keep], float(s["casing_m"]))
    if isconn is not None:                                # the lanes and their lines without the connectors
        g, base = g[~isconn.values], base[~isconn.values]
    colour_col, palette_colors, _ = _colour_groups(g, s)
    # the road (its casing) on the lanes' full lines, to the nodes, whatever is drawn: SUMO cuts a road's two directions at different
    # places, so the middle of their cut lines is skewed and short (2026-10-10, connectors on: casings and lanes did not match)
    roads = items.link_roads(base, float(s["casing_m"]), float(s["centre_line_m"]))
    road_of = roads.attrs["road_of"]
    lane_fc, line_fc = items.lane_strokes(g, g[colour_col].map(palette_colors), s["tunnel_body"], ["name", "lane_id", "lane_num", "use", "width_m", "link_id"],
                                          road_of, float(s["centre_line_m"]), s["lines"] or {"divider": False, "centre": False},
                                          float(s["junction_trim_m"]), level_of=_level, ext=roads.attrs["ext"])
    marks_fc = mark_strokes(g, turns, s.get("arrows"), items.lane_shifts(g.reset_index(drop=True), road_of, float(s["centre_line_m"])))   # as the lane page
    two = items.two_way_links(road_of)
    width = {str(lk): float(w) + 2 * float(s["casing_m"]) + (float(s["centre_line_m"]) / 2 if int(lk) in two else 0.0)
             for lk, w in g.groupby("link_id")["width_m"].sum().items()}
    # the casing's line, as the lane page: the middle of the carriageway (link_roads), the reverse link's backwards (GMNS moves a one-way
    # carriageway's lanes off its OSM line where an opposite one runs close by: on the OSM line the casing missed its lanes, 2026-10-10)
    from shapely.geometry import LineString
    line = dict(zip(roads["edge_id"].astype(int), roads.geometry, strict=True))
    lines = {str(lk): (line[rd] if lk == rd else LineString(list(line[rd].coords)[::-1])) for lk, rd in road_of.items() if rd in line}
    return lane_fc, line_fc, marks_fc, width, lines, conn_fc


def _with_casing(fc, conn, casing_m):
    """Each connector with a casing of its own: the same line, ``2 * casing_m`` wider, in the casing colour of its road's class (the editor's
    palette, or ``LANESTYLE_CASING_COLOR``), flagged ``casing``: drawn with the road casings (rs.Overlay casing=True), under every lane."""
    import roadstyle as rs
    from lanestyle.items import ROAD_END
    if not fc:
        return fc
    test = os.environ.get("LANESTYLE_CASING_COLOR")
    from roadstyle.palettes import DEFAULT_PALETTE
    pal = rs.palette_to_dict(DEFAULT_PALETTE)
    cls_of = dict(zip(conn["lane_id"], conn["highway"].astype(str).str.removesuffix("_link")))
    missing = sorted({c for c in cls_of.values() if c not in pal}) if not test else []
    if missing:
        raise ValueError(f"lanestyle.editor: no casing colour for the road class(es) {missing} in roadstyle's palette")
    under = [{**f, "properties": {**f["properties"], "order": ROAD_END, "casing": True, "color": test or pal[cls_of[f["properties"]["lane_id"]]]["casing"],
                                    "width_m": f["properties"]["width_m"] + 2 * casing_m}} for f in fc["features"]]
    return {"type": "FeatureCollection", "features": under + fc["features"]}


def lane_items(roads):
    """The editor's hook (roadstyle.level_editor): the lanes and lane lines of ``LANESTYLE_GMNS`` as items of the editor's edges (``roads["edge"]``), and
    each edge with lanes at their width (``width_m``). The lanes of a link that is no edge of the editor's area are left out, and their count printed."""
    import roadstyle as rs

    gmns, src = os.environ.get("LANESTYLE_GMNS"), os.environ.get("LANESTYLE_SOURCE_DB")
    if not gmns:
        raise ValueError("lanestyle.editor.lane_items: set LANESTYLE_GMNS to the GMNS .duckdb (and LANESTYLE_SOURCE_DB to its duckOSM file)")
    on = os.environ.get("LANESTYLE_CONNECTORS") == "1"    # SUMO's paths through the junctions, the lanes cut where the junction begins
    lane_fc, line_fc, marks_fc, width, lines, conn_fc = _strokes(gmns, src, on)
    edges = set(roads["edge"].astype(str))

    def on_edges(fc):
        fs = [{**f, "properties": {**f["properties"], "road_id": str(f["properties"]["edge_id"])}} for f in fc["features"]]
        out = [f for f in fs if f["properties"]["road_id"] in edges]
        if len(out) < len(fs):
            print(f"lanestyle.editor: {len(fs) - len(out)} of {len(fs)} items are on links that are no edge of the area: left out", flush=True)
        return {"type": "FeatureCollection", "features": out}

    roads["width_m"] = [width.get(e, np.nan) for e in roads["edge"].astype(str)]
    roads.geometry = [lines.get(e, g) for e, g in zip(roads["edge"].astype(str), roads.geometry, strict=True)]
    m = dict(edge_col="road_id", order_col="order", color_col="color", width_m_col="width_m", offset_m_col="offset_m")
    overlays = [rs.Overlay(on_edges(lane_fc), label="lanes", popup=["name", "lane_id", "lane_num", "use", "width_m", "link_id"], select="item", **m),
                rs.Overlay(on_edges(line_fc), label="lane lines", popup=[], **m)]
    if marks_fc:
        overlays.append(rs.Overlay(on_edges(marks_fc), label="lane marks", popup=[], **m))
    if conn_fc:
        under = [f for f in conn_fc["features"] if f["properties"].get("casing")]
        over = [f for f in conn_fc["features"] if not f["properties"].get("casing")]
        overlays.append(rs.Overlay(on_edges({"type": "FeatureCollection", "features": under}), label="connector casing", popup=[], casing=True, **m))
        overlays.append(rs.Overlay(on_edges({"type": "FeatureCollection", "features": over}), label="connectors", popup=[], **m))
    # as the lane page: no road fill (the lanes are the surface), no roadstyle one-way chevrons or street names (lanestyle draws its own marks)
    from lanestyle.render import lane_settings
    # metres at every zoom (width_m_zoom 0) and lanestyle's casing, as the lane page
    kw = {"width_m_col": "width_m", "width_m_zoom": 0, "casing_m": float(lane_settings()["casing_m"]), "casing_min_px": float(lane_settings()["casing_min_px"]), "road_fill": False, "arrows": False, "labels": False}
    test = os.environ.get("LANESTYLE_CASING_COLOR")       # a casing colour of its own for inspecting (2026-10-10: grey lanes, grey casings)
    if test:
        pal = {c: {**v, "casing": test} for c, v in rs.palette_to_dict("amber").items()}
        cfg = {"bridge_casing_color": test}
        tun = os.environ.get("LANESTYLE_TUNNEL_CASING")     # "dash,gap": a tunnel casing's two colours
        if tun:
            cfg.update(tunnel_palettes={"lanestyle_test": tun.split(",")}, tunnel_palette="lanestyle_test")
        kw.update(palette="lanestyle_test", settings={"palettes": {"lanestyle_test": pal}, "config": cfg})
    return overlays, kw
