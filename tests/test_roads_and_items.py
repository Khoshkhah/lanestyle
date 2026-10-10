"""The current design (docs/design/lanestyle_on_roadstyle_items.md): one road per carriageway, items attached to it by ``road_id``, the ends of roads that meet share one point."""
import json

from test_lanestyle import _dbs

import lanestyle as ls
from lanestyle import items


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
    """lanestyle.editor.lane_items (roadstyle's level editor ``--items``): each road one line at its full width (single_line_classes), in the
    car lane colour; the lanes, lines and marks of the GMNS file as the road's own items (render items=, no overlay; a link is a duckOSM edge:
    ``edge`` = its ``edge_id``), each labelled with its road, the lanes picked, the bus and bike lanes drawn, the car lanes unseen, no
    connectors; a link that is no edge of the editor is left out and said (2026-10-10)."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString

    from lanestyle import editor
    gmns, src = _dbs(tmp_path)
    monkeypatch.setenv("LANESTYLE_GMNS", str(gmns))
    monkeypatch.setenv("LANESTYLE_SOURCE_DB", str(src))
    editor._strokes.cache_clear()
    lanes, _ = ls.from_gmns(gmns, source_db=src)
    links = sorted({str(k) for k in lanes[~lanes["connector"].fillna(False).astype(bool)]["link_id"]} if "connector" in lanes else {str(k) for k in lanes["link_id"]})
    monkeypatch.delenv("LANESTYLE_CASING_COLOR", raising=False)
    monkeypatch.delenv("LANESTYLE_CONNECTORS", raising=False)
    drawn = gpd.GeoDataFrame({"edge": links[1:], "road": ["r" + x for x in links[1:]], "highway": "residential", "modes": "driving + walking"},
                             geometry=[LineString([(0, 0), (1, 1)])] * (len(links) - 1), crs=4326)
    foot = gpd.GeoDataFrame({"edge": ["999"], "road": ["foot"], "highway": ["footway"], "modes": ["walking (private)"]}, geometry=[LineString([(0, 0), (1, 0)])], crs=4326)
    drawn = gpd.GeoDataFrame(pd.concat([drawn, foot], ignore_index=True), crs=4326)
    overlays, kw = editor.lane_items(drawn)
    # a road cars do not use in lanestyle's colour for who uses it (colors.groups), every other one in the car lane colour (2026-10-09)
    table = kw.pop("color_table")
    assert kw.pop("color_key") == "edge" and table["999"] == "#f0cb8c" and {table[e] for e in links[1:]} == {"#a3a3a3"}
    drawn = drawn[drawn["road"] != "foot"]
    st, items, popup = kw.pop("settings"), kw.pop("items")["features"], kw.pop("items_popup")
    assert overlays == [] and kw == {"width_m_col": "width_m", "width_m_zoom": 0, "casing_m": 0.14, "casing_min_px": 1.0, "arrows": False,
                                     "palette": "lanestyle_editor"}
    assert set(drawn["highway"]) <= set(st["config"]["single_line_classes"]) and st["config"]["labels"]["halo_width"] > 0 and "lane_id" in popup
    assert {v["fill"] for v in st["palettes"]["lanestyle_editor"].values()} == {"#a3a3a3"}      # the road in the car lane colour
    assert drawn["width_m"].notna().all()
    feats = [f for f in items if f["properties"]["pick"]]                    # the lanes: picked; lines and marks: not
    assert feats and all(f["properties"]["edge"] == str(f["properties"]["edge_id"]) and f["properties"]["edge"] in links[1:] for f in feats)
    assert {f["properties"]["edge"] for f in feats} == set(links[1:]) and all("lane_num" in f["properties"] for f in feats)
    assert any(not f["properties"]["pick"] for f in items)
    *_, special = editor._strokes(str(gmns), str(src), False)
    assert all(f["properties"]["road"] == "r" + f["properties"]["edge"] for f in items)
    # a bus or bike lane drawn on the road, a car lane unseen
    assert all((f["properties"]["color"] == "rgba(0,0,0,0)") == (f["properties"]["lane_id"] not in special) for f in feats)
    assert all(f["properties"]["lane_id"] in special for f in feats if f["properties"]["use"] in ("bus", "bike", "bus,bike"))
    assert any(f["properties"]["color"] == "rgba(0,0,0,0)" for f in feats)
    assert "left out" in capsys.readouterr().out
    # the casing's line is the lane page's (the middle of the carriageway), not the editor's: every edge left its dummy line
    assert all(g.coords[0] != (0.0, 0.0) for g in drawn.geometry)
    editor._strokes.cache_clear()


def test_the_road_line_is_the_middle_of_the_carriageway_whatever_its_kerb_lanes_widths():
    """A one-way link with a 1.5 m bike lane (lane -1, left) and a 3.25 m car lane: the road line (the casing's) is the middle of the outer
    edges (+1.5 and -3.25 m: -0.875 m), not the middle of the two lane centres (-0.44 m; 2026-10-10: the casing hidden on one side)."""
    import geopandas as gpd
    from shapely.geometry import LineString

    m = 1 / 111320.0
    y0 = 43.73
    lane = lambda dy: LineString([(7.42, y0 + dy * m), (7.4205, y0 + dy * m)])      # east; + dy = north = left of travel
    g = gpd.GeoDataFrame({"link_id": [1, 1], "lane_num": [-1, 1], "width_m": [1.5, 3.25], "from_node_id": [10, 10], "to_node_id": [20, 20]},
                         geometry=[lane(0.75), lane(-1.625)], crs=4326)
    roads = items.link_roads(g, 0.14, 0.15)
    ys = [(c[1] - y0) / m for c in roads.geometry.iloc[0].coords]
    assert abs(sum(ys) / len(ys) - (-0.875)) < 0.05          # edges +1.5 and -3.25: their middle


def test_the_lane_page_is_the_editors_drawing_without_its_panel(tmp_path):
    """lanestyle.lane_page (2026-10-10): the roads of a level area as the editor draws them (one line at the lanes' width, its levels), the
    lanes, lines and marks as the roads' own items (render items=), a road popup and no editor panel."""
    import geopandas as gpd
    import pytest
    pytest.importorskip("scipy")
    from roadstyle.level_area import make_area
    from shapely.geometry import LineString

    import lanestyle as ls
    gmns, src = _dbs(tmp_path)
    a, b, c = (18.00, 59.30), (18.01, 59.30), (18.02, 59.30)
    edges = gpd.GeoDataFrame({"edge_id": [8121729169906061189, 2, 3], "highway": ["secondary", "tertiary", "secondary"],
                              "name": ["Main St", "Bridge Rd", "Main St"], "oneway": [True, True, True], "driving": [True] * 3,
                              "cycling": [False] * 3, "lanes": [2, 1, 1], "modes": ["driving"] * 3},
                             geometry=[LineString([a, b]), LineString([b, c]), LineString([b, a])], crs=4326)
    make_area(edges, tmp_path / "area", id_col="edge_id")
    html = ls.lane_page(tmp_path / "area", str(gmns), str(src)).html
    assert "roads-simple" in html and '"lane_id"' in html and "1_2" in html         # the one road layer, its lane items
    assert "lv-apply" not in html and "Lanes" in html                               # no editor panel; the page's own name
