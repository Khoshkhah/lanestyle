"""The lanes in roadstyle's level editor: the editor draws each road as one line at its full width (both directions, in metres from the
lanes: roadstyle's look without lanes, one casing, one fill in the car lane colour, one round end), the bus and bike lanes, lane lines and
marks on it as the road's items, the car lanes as unseen items (picked and highlighted only) and the connectors as unseen, unpicked items
(2026-10-10).

    LANESTYLE_GMNS=monaco_gmns.duckdb LANESTYLE_SOURCE_DB=monaco.duckdb \\
        roadstyle-levels edit AREA --items lanestyle.editor:lane_items

The GMNS file and its duckOSM source come from those two environment variables (``link_id`` = duckOSM ``edge_id`` = the editor's edge ids).
"""
import os
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _strokes(gmns, source_db, connectors=False):
    """The lane table's lanes, lines and marks as items (lanestyle.items.lane_strokes, arrows.mark_strokes), each on its link (``edge_id``), and
    each link's width in metres and line.
    ``connectors``: also duckOSM's lane connectors (SUMO's paths through the junctions) as items of the link they leave."""
    import lanestyle as ls
    from lanestyle import items
    from lanestyle.arrows import mark_strokes
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
                                          dict(zip(g["lane_id"], g["width_m"])))
    if isconn is not None:                                # the lanes without the connectors
        g, base = g[~isconn.values], base[~isconn.values]
    colour_col, palette_colors, _ = _colour_groups(g, s)
    # the road (its casing) on the lanes' full lines, to the nodes, whatever is drawn: SUMO cuts a road's two directions at different
    # places, so the middle of their cut lines is skewed and short (2026-10-10, connectors on: casings and lanes did not match)
    roads = items.link_roads(base, float(s["casing_m"]), float(s["centre_line_m"]))
    road_of = roads.attrs["road_of"]
    lane_fc, line_fc = items.lane_strokes(g, g[colour_col].map(palette_colors), s["tunnel_body"], ["name", "lane_id", "lane_num", "use", "width_m", "link_id"],
                                          road_of, float(s["centre_line_m"]), s["lines"] or {"divider": False, "centre": False},
                                          float(s["junction_trim_m"]), ext=roads.attrs["ext"])   # no tunnel blend here: roadstyle's tunnel look colours the items (2026-10-10: twice)
    # each link drawn as its whole road (2026-10-10, the twin version without lanes): both directions one line, the road's full width
    road_w = dict(zip(roads["edge_id"].astype(int), roads["width_m"], strict=True))
    width = {str(lk): float(road_w[rd]) for lk, rd in road_of.items() if rd in road_w}
    # the casing's line, as the lane page: the middle of the carriageway (link_roads), the reverse link's backwards (GMNS moves a one-way
    # carriageway's lanes off its OSM line where an opposite one runs close by: on the OSM line the casing missed its lanes, 2026-10-10)
    from shapely.geometry import LineString
    line = dict(zip(roads["edge_id"].astype(int), roads.geometry, strict=True))
    lines = {str(lk): (line[rd] if lk == rd else LineString(list(line[rd].coords)[::-1])) for lk, rd in road_of.items() if rd in line}
    marks_fc = mark_strokes(g, turns, s.get("arrows"), items.lane_shifts(g.reset_index(drop=True), road_of, float(s["centre_line_m"])))   # as the lane page
    # the lanes drawn on the road: every bus, bike and bus + bike lane (the road itself is in the car lane colour, 2026-10-10)
    special = {str(i) for i, u in zip(g["lane_id"], g["use"].astype(str), strict=True) if u.startswith("bus") or u == "bike"}
    return lane_fc, line_fc, marks_fc, width, lines, conn_fc, special


def lane_items(roads):
    """The editor's hook (roadstyle.level_editor): each road one line at its full width (``width_m``, both directions; config
    ``single_line_classes``: every class) on the lanes' line, in the car lane colour, with roadstyle's street names; the road's own items
    (render ``items=``): every bus, bike and bus + bike lane drawn in its colour, the car lanes unseen (picked and highlighted only), the lane
    lines and marks, and with ``LANESTYLE_CONNECTORS=1`` the connectors unseen and unpicked; every item labelled with its road (``road``: one
    for both directions). The items of a link that is no edge of the editor's area are left out, and their count printed."""
    import roadstyle as rs

    gmns, src = os.environ.get("LANESTYLE_GMNS"), os.environ.get("LANESTYLE_SOURCE_DB")
    if not gmns:
        raise ValueError("lanestyle.editor.lane_items: set LANESTYLE_GMNS to the GMNS .duckdb (and LANESTYLE_SOURCE_DB to its duckOSM file)")
    on = os.environ.get("LANESTYLE_CONNECTORS") == "1"
    lane_fc, line_fc, marks_fc, width, lines, conn_fc, special = _strokes(gmns, src, on)
    road_of = dict(zip(roads["edge"].astype(str), roads["road"].astype(str)))

    def on_edges(fc, pick=False, seen=lambda f: True):   # on the editor's edges (``edge``), labelled with their road; unseen: a transparent colour
        fs = [{**f, "properties": {**f["properties"], "edge": str(f["properties"]["edge_id"]), "road": road_of.get(str(f["properties"]["edge_id"])),
                                   "pick": pick, **({} if seen(f) else {"color": "rgba(0,0,0,0)"})}} for f in (fc or {"features": []})["features"]]
        out = [f for f in fs if f["properties"]["road"] is not None]
        if len(out) < len(fs):
            print(f"lanestyle.editor: {len(fs) - len(out)} of {len(fs)} items are on links that are no edge of the area: left out", flush=True)
        return out

    # the road's width and line from its edge with lanes, whichever edge draws it (2026-10-09: a road drawn by its walking-only direction had
    # no lanes, so roadstyle's class width: 161748261#2r narrower than #1f, the same one car lane); the other direction runs the line backwards
    from shapely.geometry import LineString
    edges = roads["edge"].astype(str)
    own = {r: e for r, e in zip(roads["road"], edges, strict=True) if e in width}
    roads["width_m"] = [width.get(own.get(r), np.nan) for r in roads["road"]]
    roads.geometry = [lines[e] if e in lines else (LineString(list(lines[own[r]].coords)[::-1]) if own.get(r) in lines else g)
                      for e, r, g in zip(edges, roads["road"], roads.geometry, strict=True)]
    # the road's own items in roadstyle's one road layer (render items=, 2026-10-10): the car lanes unseen (picked and highlighted), every bus
    # and bike lane drawn on the road; the lane lines and marks on it; connectors unseen, not picked (route highlights)
    items = (on_edges(lane_fc, pick=True, seen=lambda f: f["properties"]["lane_id"] in special) + on_edges(line_fc) + on_edges(marks_fc)
             + on_edges(conn_fc, seen=lambda f: False))
    from lanestyle.render import lane_settings
    s = lane_settings()
    # metres at every zoom (width_m_zoom 0) and lanestyle's casing; roadstyle's street names, not its one-way chevrons (lanestyle's arrows instead);
    kw = {"width_m_col": "width_m", "width_m_zoom": 0, "casing_m": float(s["casing_m"]), "casing_min_px": float(s["casing_min_px"]), "arrows": False,
          "items": {"type": "FeatureCollection", "features": items},
          "items_popup": ["road", "name", "lane_id", "lane_num", "use", "width_m", "link_id"]}
    test = os.environ.get("LANESTYLE_CASING_COLOR")       # a casing colour of its own for inspecting (2026-10-10)
    pal = {c: {**v, "fill": s["colors"]["auto"], **({"casing": test} if test else {})} for c, v in rs.palette_to_dict("amber").items()}   # the road in the car lane colour
    # street names with a halo, growing with the zoom as the roads in metres do (2026-10-10)
    # a two-way road one line at its full width (single_line_classes: every class drawn), as the twin version without lanes: one casing, one
    # fill, one round end; its lanes, lines and marks at their own places on it
    cfg = {"single_line_classes": sorted(set(roads["highway"].dropna().astype(str))), "labels": {"color": "#333333", "halo_color": "#ffffff", "halo_width": 1.5,
                                              "size": [[15, 10], [17, 12], [19, 15], [21, 20], [22, 24]]}}
    kw.update(palette="lanestyle_editor", settings={"palettes": {"lanestyle_editor": pal}, "config": cfg})
    if test:
        cfg["bridge_casing_color"] = test
        tun = os.environ.get("LANESTYLE_TUNNEL_CASING")     # "dash,gap": a tunnel casing's two colours
        if tun:
            cfg.update(tunnel_palettes={"lanestyle_test": tun.split(",")}, tunnel_palette="lanestyle_test")
    # a road cars do not use (no driving edge) in lanestyle's colour for who uses it, as the lane page colours a lane by the networks
    # that have its link (colors.groups: walking, cycling, walking+cycling; 2026-10-09); every other road in the car lane colour
    order = ("walking", "cycling")
    if "modes" not in roads:
        raise ValueError("lanestyle.editor.lane_items: the area's roads have no per-edge modes (who uses each road): make the area again")
    who = {}
    for r, m in zip(roads["road"], roads["modes"].fillna(""), strict=True):
        who.setdefault(r, set()).update(x.strip().removesuffix(" (private)") for x in str(m).split("+"))     # a private road: its modes "(private)"
    groups = s["colors"]["groups"]
    colour = {r: s["colors"]["auto"] if "driving" in w or not (w & set(order)) else groups["+".join(x for x in order if x in w)] for r, w in who.items()}
    kw.update(color_table={e: colour[r] for e, r in zip(roads["edge"].astype(str), roads["road"], strict=True)}, color_key="edge")
    return [], kw
