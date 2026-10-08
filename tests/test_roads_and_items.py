"""The current design (docs/design/lanestyle_on_roadstyle_items.md): one road per carriageway, items attached to it by ``road_id``, the ends of roads that meet share one point."""
import json

import lanestyle as ls
from lanestyle import items
from test_lanestyle import _dbs


def _style(html):
    return json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])


def _lanes(tmp_path):
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    g = lanes[~lanes["connector"].fillna(False).astype(bool)] if "connector" in lanes else lanes
    g = g[g.geometry.notna()].reset_index(drop=True)
    g["width_m"] = g["width_m"].fillna(3.0)
    return lanes, turns, g


def test_a_road_is_a_carriageway_and_its_width_is_its_lanes_and_the_casing(tmp_path):
    _, _, g = _lanes(tmp_path)
    roads = items.link_roads(g, 0.14)
    road_of = roads.attrs["road_of"]
    assert set(road_of) == {int(k) for k in g["link_id"]} and set(road_of.values()) == {int(e) for e in roads["edge_id"]}
    for road, w in zip(roads["edge_id"], roads["width_m"], strict=True):
        links = [k for k, r in road_of.items() if r == road]
        assert abs(w - (float(g[g["link_id"].isin(links)]["width_m"].sum()) + 0.28)) < 1e-9       # the lanes of its links together + the casing on each side


def test_roads_that_meet_end_at_exactly_the_same_point(tmp_path):
    from shapely.geometry import LineString

    ends = items._snap_ends([LineString([(0, 0), (5, 0), (10, 0.0001)]), LineString([(10.0003, 0), (20, 5)])], [(1, 2), (2, 3)])
    assert ends[0].coords[-1] == ends[1].coords[0]                          # node 2: one point, the mean
    assert ends[0].coords[0] == (0.0, 0.0) and ends[0].coords[1] == (5.0, 0.0)  # nothing else moves
    assert abs(ends[0].coords[-1][0] - 10.00015) < 1e-9


def test_items_are_attached_to_their_road_and_keep_their_link(tmp_path):
    _, _, g = _lanes(tmp_path)
    roads = items.link_roads(g, 0.14)
    road_of = roads.attrs["road_of"]
    colours = g["highway"].map(lambda h: "#a3a3a3")
    fc = items.on_roads(items.lane_items(g, colours, "#e6e6e6", ["lane_id"], on_road=()), road_of)
    assert len(fc["features"]) == len(g)
    for f in fc["features"]:
        p = f["properties"]
        assert p["road_id"] == road_of[p["edge_id"]] and p["order"] == items.LANE and p["color"] == "#a3a3a3"
    assert items.on_roads(None, road_of) is None


def test_a_road_end_is_a_disc_under_everything_in_the_colour_of_its_lanes(tmp_path):
    _, _, g = _lanes(tmp_path)
    roads = items.link_roads(g, 0.14)
    colours = g["highway"].map(lambda h: "#a3a3a3")
    fc = items.end_caps(roads, g, colours, "#e6e6e6", 0.14)
    assert len(fc["features"]) == 2 * len(roads)                            # one disc at each end of every road
    assert {f["properties"]["order"] for f in fc["features"]} == {items.ROAD_END} and items.ROAD_END < items.CONNECTOR < items.LANE
    assert {f["properties"]["color"] for f in fc["features"]} == {"#a3a3a3"}


def test_the_page_draws_roads_without_fill_and_the_items_by_road_id(tmp_path):
    lanes, turns, g = _lanes(tmp_path)
    html = ls.render_lanes(lanes, turns).html
    style = _style(html)
    assert any(lyr["id"] == "roads-simple" for lyr in style["layers"])                  # roadstyle's simple mode: one road layer, casings and items in one order
    pieces = style["sources"]["simple"]["data"]["features"]
    lines = [f for f in pieces if f["properties"].get("__rs_k") == 5]                      # the lanes and the lane lines are items in it, each its own width in metres
    assert len(lines) >= len(g) and {f["properties"]["__rs_ic"] for f in lines} >= {"#f2f2f2"}
    roads = {str(f["properties"]["edge_id"]) for f in style["sources"]["roads"]["data"]["features"]}
    overlays = json.JSONDecoder().raw_decode(html.split("const OVERLAYS = ", 1)[1])[0]
    lanes_ov = next(o for o in overlays if o["label"] == "lanes")
    feats = style["sources"][lanes_ov["source"]]["data"]["features"]
    assert feats and {str(f["properties"]["road_id"]) for f in feats} <= roads          # every lane is on a road of the page
    assert all("edge_id" in f["properties"] and "lane_id" in f["properties"] for f in feats)


def test_the_casing_numbers_of_the_roads_are_passed_with_their_heads(tmp_path):
    lanes, turns, _ = _lanes(tmp_path)
    style = _style(ls.render_lanes(lanes, turns).html)
    props = style["sources"]["roads"]["data"]["features"][0]["properties"]
    assert all(k in props for k in ("__rs_cs", "__rs_cl", "__rs_ce", "__rs_fl"))      # start head, main part, end head, fill


def test_the_lanes_of_a_road_fill_its_band_side_by_side():
    """docs: the lanes are laid across the road's band, leftmost first, each as wide as its width: the casing around them is the same width all along."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    road = LineString([(0, 0), (50, 0), (100, 20)])
    widths = [3.5, 3.0, 2.5]
    top, shapes = sum(widths) / 2, []
    for w in widths:
        shapes.append(items._band(road, top - w, top))
        top -= w
    union = unary_union(shapes)
    band = road.buffer(sum(widths) / 2, cap_style="flat")
    assert union.symmetric_difference(band).area / band.area < 0.02          # no gap, no overlap beyond the joins
    assert all(abs(s.area - w * road.length) / (w * road.length) < 0.02 for s, w in zip(shapes, widths, strict=True))


def test_a_roundabout_and_a_tunnel_are_over_the_roads_they_meet():
    """docs: the order of a road is the class order, plus 100 for a roundabout and for a tunnel, whatever the class; a road with no class has none."""
    import numpy as np
    import pandas as pd

    from lanestyle.levels import RING_TUNNEL_BOOST, road_order

    roads = pd.DataFrame({"highway": ["primary", "residential", "residential", "residential", None],
                          "roundabout": [False, True, False, False, True], "tunnel": [None, None, "yes", "no", "yes"]})
    o = road_order(roads)
    assert o[1] == o[3] + RING_TUNNEL_BOOST and o[2] == o[3] + RING_TUNNEL_BOOST          # the ring and the tunnel are over the same class
    assert o[1] > o[0] and o[2] > o[0]                                                      # and over a primary road they meet
    assert np.isnan(o[4])


def test_a_roads_numbers_are_the_rows_of_duckosms_table_as_they_are(tmp_path):
    import duckdb
    import pandas as pd

    from lanestyle.levels import link_levels, stored_levels

    db = tmp_path / "src.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA driving; CREATE SCHEMA visualization")
    con.execute("CREATE TABLE driving.edges AS SELECT * FROM (VALUES (1, false), (2, true), (3, false)) t(edge_id, is_reverse)")
    con.execute("CREATE TABLE visualization.edge_levels AS SELECT * FROM (VALUES (1, -2, -1, -1, -1), (2, -2, -1, -1, -1), (3, 0, 0, 0, 0)) t(edge_id, casing_start, casing_level, casing_end, fill_level)")
    con.close()
    roads = pd.DataFrame({"edge_id": [2, 1]})
    assert stored_levels(roads, db).to_numpy().tolist() == [[-2, -1, -1, -1], [-2, -1, -1, -1]]       # each edge's row as stored (a reverse row too: mapstyle reads the same)
    assert link_levels(roads, db).to_numpy().tolist() == stored_levels(roads, db).to_numpy().tolist()
    try:
        stored_levels(pd.DataFrame({"edge_id": [9]}), db)
    except ValueError as e:
        assert "duckosm levels" in str(e)
    else:
        raise AssertionError("an edge the table lacks must be an error")


def test_the_popup_numbers_of_a_lane_are_its_own_links_not_its_roads(tmp_path):
    import duckdb

    from lanestyle.levels import own_levels

    db = tmp_path / "src.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA visualization")
    con.execute("CREATE TABLE visualization.edge_levels AS SELECT * FROM (VALUES (1, -2, -1, -1, -1), (2, -1, -1, -2, -1)) t(edge_id, casing_start, casing_level, casing_end, fill_level)")
    con.close()
    con = duckdb.connect(str(db)); con.execute("CREATE TABLE visualization.edge_levels_meta AS SELECT 25.0 AS head_m"); con.close()
    from lanestyle.levels import stored_head_m
    assert stored_head_m(db) == 25.0 and stored_head_m(None) is None            # the page cuts the heads at the length the numbers were computed with
    got = own_levels([1, 2, 9], db)
    assert got[0].tolist() == [-2, -1, -1, -1] and got[1].tolist() == [-1, -1, -2, -1]      # the two directions of a street keep their own heads
    assert all(x != x for x in got[2])                                                       # a link the table lacks: NaN
    assert all(x != x for x in own_levels([1], None)[0])


def test_the_widest_road_decides_where_roads_meet_and_a_narrower_one_gets_a_hook(tmp_path):
    from shapely.geometry import LineString

    ring_a = LineString([(0, 0), (10, 0)])
    ring_b = LineString([(10.2, 0.1), (20, 0)])                    # the ring goes on: its two ends are 0.22 m apart
    arm = LineString([(10, 5), (10, 1.6)])                         # an arm of a narrow road ends 1.6 m off the ring's line
    far = LineString([(10, 30), (10, 8)])                          # and one that ends 8 m off: no node of one road
    out = items._snap_ends([ring_a, ring_b, arm], [(1, 2), (2, 3), (4, 2)], [6.78, 6.78, 3.53])
    mid = (10.1, 0.05)
    assert out[0].coords[-1] == mid and out[1].coords[0] == mid                      # the wide roads meet at the mean of their own ends
    assert out[2].coords[-1] == mid and out[2].coords[-2] == (10.0, 1.6) and len(out[2].coords) == 3     # the arm keeps its line and gets the point as a hook
    assert out[0].coords[0] == (0.0, 0.0)                                              # nothing else moves
    arm_start = LineString([(10, 1.6), (10, 5)])                    # the same arm, drawn from the ring outwards: the hook is at its start
    start_out = items._snap_ends([ring_a, ring_b, arm_start], [(1, 2), (2, 3), (2, 4)], [6.78, 6.78, 3.53])
    assert start_out[2].coords[0] == mid and start_out[2].coords[1] == (10.0, 1.6) and start_out[2].coords[-1] == (10.0, 5.0)     # the point, then the old start: no fold
    far_out = items._snap_ends([ring_a, ring_b, far], [(1, 2), (2, 3), (4, 2)], [6.78, 6.78, 3.53])
    assert far_out[2].coords[-1] == far_out[0].coords[-1] and len(far_out[2].coords) == 2     # too far from the wide road: the old mean of all the ends


def test_a_two_way_road_with_unequal_lanes_is_drawn_where_its_lanes_are():
    """A road of 2 lanes one way and 1 the other: its line is the middle of the kerb lanes, so the lanes laid across its band cover their own GMNS lines (the inner lanes' middle was half a lane off)."""
    import geopandas as gpd
    from shapely.geometry import LineString

    m = 1 / 111320
    kx = 1 / (111320 * 0.5101)                                      # degrees of longitude per metre at 59.32 N
    line = lambda x0, x1, y: LineString([(18.0 + x0 * kx, 59.32 + y * m), (18.0 + x1 * kx, 59.32 + y * m)])       # noqa: E731
    g = gpd.GeoDataFrame({"link_id": [1, 1, 2], "reverse_link_id": [2, 2, 1], "lane_id": ["1_1", "1_2", "2_1"], "lane_num": [1, 2, 1], "width_m": [3.25] * 3,
                          "from_node_id": [10, 10, 20], "to_node_id": [20, 20, 10], "highway": ["secondary"] * 3, "use": ["auto"] * 3},
                         geometry=[line(0, 100, -1.625), line(0, 100, -4.875), line(100, 0, 1.625)], crs=4326)       # eastbound lanes on the south side, the westbound lane on the north
    roads = items.link_roads(g, 0.14)
    u = g.to_crs(g.estimate_utm_crs()).reset_index(drop=True)
    shapes = items.lane_shapes(u, roads.to_crs(u.crs), roads.attrs["road_of"])
    for k in u.index:
        ideal = u.geometry[k].buffer(3.25 / 2, cap_style="flat")
        assert ideal.difference(shapes[k]).area / ideal.area < 0.1, (u.lane_id[k], ideal.difference(shapes[k]).area / ideal.area)


def test_a_lane_click_reaches_the_street_view_panel(tmp_path):
    """roadstyle's Street View panel and window ignore overlay clicks, so lanestyle re-sends a lane click as a click on its road."""
    lanes, turns, _ = _lanes(tmp_path)
    assert "Number(d.properties.road_id)" in ls.render_lanes(lanes, turns).html
    assert "Number(d.properties.road_id)" in ls.render_lanes(lanes, turns, street_view=True).html


def test_lanes_and_lines_are_line_items_with_the_centre_line_between_the_directions():
    """Step 2b (Boulevard Charles III's layout): 2 car lanes one way, a bus/bike lane the other. A lane is its own line, its width; both directions move half the centre
    line to the right, the road is the lanes + the centre line + the casing; dashed (metre pieces) between the car lanes, a solid centre line on lane 1's left edge."""
    import geopandas as gpd
    from shapely.geometry import LineString

    m, kx = 1 / 111320, 1 / (111320 * 0.7225)                     # degrees per metre at 43.73 N
    line = lambda x0, x1, y: LineString([(7.4 + x0 * kx, 43.73 + y * m), (7.4 + x1 * kx, 43.73 + y * m)])       # noqa: E731
    g = gpd.GeoDataFrame({"link_id": [1, 1, 2], "reverse_link_id": [2, 2, 1], "lane_id": ["1_1", "1_2", "2_1"], "lane_num": [1, 2, 1], "width_m": [3.25] * 3,
                          "from_node_id": [10, 10, 20], "to_node_id": [20, 20, 10], "highway": ["primary"] * 3, "use": ["auto", "auto", "bus,bike"]},
                         geometry=[line(0, 100, -1.625), line(0, 100, -4.875), line(100, 0, 1.625)], crs=4326)
    roads = items.link_roads(g, 0.14, 0.15)
    assert abs(roads["width_m"].iloc[0] - (3 * 3.25 + 0.15 + 0.28)) < 1e-9
    lanes, lines = items.lane_strokes(g, g["use"].map(lambda u: "#aaa"), "#eee", ["lane_id"], roads.attrs["road_of"], 0.15,
                                      {"divider": True, "centre": True, "width_m": 0.15, "dash_m": 3, "gap_m": 9, "color": "#f2f2f2"}, 1.0)
    assert [(f["geometry"]["type"], f["properties"]["width_m"], f["properties"]["offset_m"]) for f in lanes["features"]] == [("LineString", 3.25, 0.075)] * 3
    by = {f["properties"]["t"]: f for f in lines["features"]}
    assert set(by) == {"divider", "centre"} and all(f["properties"]["order"] > items.LANE for f in lines["features"])
    assert by["divider"]["geometry"]["type"] == "MultiLineString" and len(by["divider"]["geometry"]["coordinates"]) == 8      # 98 m: a 3 m dash every 12 m
    assert by["centre"]["properties"]["width_m"] == 0.15 and by["centre"]["properties"]["offset_m"] == -1.625 and by["centre"]["properties"]["edge_id"] == 1


def test_an_outline_ends_flat_at_a_junction_and_round_where_its_road_goes_on():
    """Roads 1 and 2 meet at node 20 at a right angle (the road goes on: round outline, lanes drawn on over the bend); node 30 is a junction of three (flat), 10 a dead end (flat)."""
    from shapely.geometry import LineString

    lines = [LineString([(0, 0), (100, 0)]), LineString([(100, 0), (100, 100)]), LineString([(100, 100), (200, 100)]), LineString([(100, 100), (0, 100)])]
    cap0, cap1, ext = items._ends(lines, [(10, 20), (20, 30), (30, 40), (30, 50)], [8.0] * 4, [1, 2, 3, 4])
    assert cap0[:2] == [True, None] and cap1[:2] == [None, True]
    assert abs(ext[(1, 20)] - 4.0) < 1e-9 and abs(ext[(2, 20)] - 4.0) < 1e-9 and (2, 30) not in ext      # half the width x tan(45 degrees)


def test_the_level_editor_hook_puts_each_lane_on_its_edge_of_the_editor(tmp_path, monkeypatch, capsys):
    """lanestyle.editor.lane_items (roadstyle's level editor ``--items``): the lanes and lines of the GMNS file as items of the editor's edges (a link is a duckOSM
    edge: ``road_id`` = its ``edge_id``), no connectors, the edges at their lanes' width; a link that is no edge of the editor is left out and said."""
    import geopandas as gpd
    from shapely.geometry import LineString

    from lanestyle import editor
    gmns, src = _dbs(tmp_path)
    monkeypatch.setenv("LANESTYLE_GMNS", str(gmns))
    monkeypatch.setenv("LANESTYLE_SOURCE_DB", str(src))
    editor._strokes.cache_clear()
    lanes, _ = ls.from_gmns(gmns, source_db=src)
    links = sorted({str(k) for k in lanes[~lanes["connector"].fillna(False).astype(bool)]["link_id"]} if "connector" in lanes else {str(k) for k in lanes["link_id"]})
    drawn = gpd.GeoDataFrame({"edge": links[1:], "road": links[1:]}, geometry=[LineString([(0, 0), (1, 1)])] * (len(links) - 1), crs=4326)
    overlays, kw = editor.lane_items(drawn)
    assert kw == {"width_m_col": "width_m", "width_m_zoom": 0, "casing_m": 0.14, "road_fill": False, "arrows": False, "labels": False} and drawn["width_m"].notna().all()
    lanes_ov, lines_ov = overlays[:2]
    assert [o.label for o in overlays[2:]] in ([], ["lane marks"])           # the marks, as on the lane page
    feats = lanes_ov.data["features"]
    assert feats and all(f["properties"]["road_id"] == str(f["properties"]["edge_id"]) and f["properties"]["road_id"] in links[1:] for f in feats)
    assert {f["properties"]["road_id"] for f in feats} == set(links[1:]) and lanes_ov.select == "item" and lanes_ov.edge_col == "road_id"
    assert all(f["properties"]["road_id"] in links[1:] for f in lines_ov.data["features"])
    assert "left out" in capsys.readouterr().out
    editor._strokes.cache_clear()
