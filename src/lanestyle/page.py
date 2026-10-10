"""The lane page (2026-10-10): the level editor's drawing without its panel. roadstyle draws every road (one line at the full width of its
lanes, its outline, ends, levels, tunnels, bridges, names, hover and click) from the level area's roads and levels, as the editor does;
lanestyle only adds the road's own items (lanes, lane lines, arrows, BUS and bike marks) through the editor's hook,
:func:`lanestyle.editor.lane_items`. One drawing, one rule: what the editor shows is what the page shows.

    import lanestyle as ls
    ls.lane_page("monaco.levels", "monaco_gmns.duckdb", "monaco.duckdb").save("lanes.html")
"""


def lane_page(area, gmns, source_db, connectors=False, **kw):
    """The lanes of ``gmns`` (duckOSM's GMNS file, its ``source_db``) on the roads of the level ``area`` (a folder made by ``duckosm levels`` /
    ``roadstyle.level_area``, with your edits): a roadstyle map. ``connectors``: also the lane connectors through the junctions, unseen
    (route highlights). ``kw`` go to :func:`roadstyle.render_edges` (e.g. ``name=``; ``basemap=`` / ``filter_control=True`` / ``tunnel_control=True`` for a base map,
    the Roads box, the Tunnels slider: by default the page is blank, just the lanes)."""
    import roadstyle as rs
    from roadstyle.level_editor import Area

    from lanestyle.editor import lane_items

    draw = Area(area).draw.copy()            # the editor's roads, one row per edge, with the levels and ends it draws
    overlays, extra = lane_items(draw, gmns=gmns, source_db=source_db, connectors=connectors)
    page = {"road_popup": [c for c in ("name", "highway", "edge_ref", "lanes", "modes", "bus_lines") if c in draw.columns],
            "name": f"Lanes · {draw.attrs.get('area', '') or 'map'}",
            "basemap": "blank", "filter_control": False}      # just the lanes (2026-10-10): no base map, no Roads box, no Tunnels slider
    return rs.render_edges(draw, edge_id_col="edge", directed_col="directed", driving_col="driving", overlays=overlays,
                           casing_start_col="casing_start", casing_level_col="casing_level", casing_end_col="casing_end",
                           fill_level_col="fill_level", cap_start_col="cap_start", cap_end_col="cap_end",
                           head_start_m_col="head_start_m", head_end_m_col="head_end_m", **{**page, **extra, **kw})
