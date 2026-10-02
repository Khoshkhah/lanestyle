import pytest
"""lanestyle: the GMNS reader (from_gmns) and the roadstyle engine (render_lanes)."""
import json
import sys

import duckdb
import pandas as pd

import lanestyle as ls


def test_no_mapstyle_dependency():
    assert "mapstyle" not in sys.modules


def _dbs(tmp_path):
    """A GMNS db: link 1 A->B (2 lanes, lane 2 bus), link 2 B->C (a bridge in the source db),
    link 3 B->A; movements 1->2 thru from every lane, 1->3 a U-turn from lane 1 only."""
    gmns, src = tmp_path / "g.duckdb", tmp_path / "s.duckdb"
    con = duckdb.connect(str(gmns))
    con.execute("INSTALL spatial; LOAD spatial; CREATE SCHEMA gmns_driving")
    ln = lambda y: f"ST_GeomFromText('LINESTRING(18.00 {y}, 18.01 {y})')"
    con.execute("CREATE TABLE gmns_driving.link(link_id BIGINT, name VARCHAR, facility_type VARCHAR, "
                "from_node_id BIGINT, to_node_id BIGINT)")
    con.execute("INSERT INTO gmns_driving.link VALUES (8121729169906061189,'Main St','secondary',10,11),"
                "(2,'Bridge Rd','tertiary',11,12),(3,'Main St','secondary',11,10)")
    con.execute("CREATE TABLE gmns_driving.lane(lane_id VARCHAR, link_id BIGINT, lane_num BIGINT, "
                "allowed_uses VARCHAR, width DOUBLE, turn VARCHAR, geom GEOMETRY)")
    con.execute(f"INSERT INTO gmns_driving.lane VALUES "
                f"('1_1',8121729169906061189,1,'auto',NULL,'left',{ln(59.30)}),"
                f"('1_2',8121729169906061189,2,'bus',3.5,NULL,{ln(59.30003)}),"
                f"('2_1',2,1,'auto',NULL,NULL,{ln(59.31)}),('3_1',3,1,'auto',NULL,NULL,{ln(59.32)})")
    con.execute("CREATE TABLE gmns_driving.movement(ib_link_id BIGINT, start_ib_lane BIGINT, "
                "end_ib_lane BIGINT, ob_link_id BIGINT, start_ob_lane INTEGER, end_ob_lane INTEGER, type VARCHAR)")
    con.execute("INSERT INTO gmns_driving.movement VALUES (8121729169906061189,NULL,NULL,2,NULL,NULL,'thru'),"
                "(8121729169906061189,1,1,3,NULL,NULL,'uturn')")
    con.close()
    con = duckdb.connect(str(src))
    con.execute("CREATE SCHEMA driving; CREATE TABLE driving.edges(edge_id BIGINT, bridge VARCHAR, "
                "tunnel VARCHAR, layer VARCHAR)")
    con.execute("INSERT INTO driving.edges VALUES (8121729169906061189,NULL,NULL,NULL),(2,'yes',NULL,'1'),"
                "(3,NULL,NULL,NULL)")
    con.close()
    return gmns, src


def test_from_gmns_lane_table_and_turns(tmp_path):
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    r = lanes.set_index("lane_id")
    assert r.loc["1_1", "highway"] == "secondary" and r.loc["1_2", "use"] == "bus"
    assert r.loc["1_1", "name"] == "Main St" and pd.isna(r.loc["1_2", "name"])        # lane 1 only
    assert r.loc["1_1", "link_id"] == 8121729169906061189                           # exact, not float
    assert r.loc["2_1", "bridge"] == "yes" and r.loc["2_1", "layer"] == "1"         # from source_db
    got = set(map(tuple, turns[["from_lane", "to_lane", "type"]].values))
    assert got == {("1_1", "2_1", "thru"), ("1_2", "2_1", "thru"), ("1_1", "3_1", "uturn")}
    # without source_db: every lane at ground level
    assert "bridge" not in ls.from_gmns(gmns)[0].columns


def test_from_gmns_levels_from_link_columns_need_no_source_db(tmp_path):
    """duckOSM writes bridge / tunnel / layer into `link`: one file is enough."""
    gmns, _ = _dbs(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("ALTER TABLE gmns_driving.link ADD COLUMN bridge VARCHAR; "
                "ALTER TABLE gmns_driving.link ADD COLUMN tunnel VARCHAR; "
                "ALTER TABLE gmns_driving.link ADD COLUMN layer VARCHAR; "
                "UPDATE gmns_driving.link SET bridge = 'yes', layer = '1' WHERE link_id = 2")
    con.close()
    r = ls.from_gmns(gmns)[0].set_index("lane_id")
    assert r.loc["2_1", "bridge"] == "yes" and r.loc["2_1", "layer"] == "1"
    assert pd.isna(r.loc["1_1", "bridge"])


def test_render_lanes_metre_widths_uses_and_click(tmp_path):
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    assert '"__rs_wm"' in html                                    # widths in metres (roadstyle 0.10)
    assert "Lane use" in html and "#d6336c" in html and "#1c7ed6" not in html   # cars and a bus lane: no bike
    # every lane is coloured by its mode group: a row each in the Roads box (cars first), no dropdown
    assert '[["car lanes", "#a3a3a3"], ["bus lanes", "#d6336c"]]' in html and ".co-ctrl,.co-lg{display:none" in html
    t = json.loads(html.split("const T = ", 1)[1].split(", C = ", 1)[0])
    assert t["1_1"] == [["2_1"], ["3_1"]] and t["1_2"] == [["2_1"], []]


def test_settings_override_the_roadstyle_way(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lanestyle.json").write_text('{"lanes": {"casing_m": 0.1}}')
    s = ls.lane_settings({"lanes": {"colors": {"bus": "#123456"}}})
    assert s["casing_m"] == 0.1 and s["colors"]["bus"] == "#123456" and s["colors"]["bike"] == "#1c7ed6"


def test_write_serve_index_html_does_not_loop(tmp_path):
    src = ls.write_serve(tmp_path / "index.html").read_text()
    assert 'self.path != "/index.html"' in src and '"Cache-Control", "no-store"' in src


def test_lane_lines_types(tmp_path):
    """Link 1 (2 lanes) and link 3 are one two-way road: one divider, one centre line (drawn by the
    smaller id, link 3), edges on the outside; link 2 is a one-way bridge: its edges are `bridge_edge`."""
    from lanestyle.lines import lane_lines

    gmns, src = _dbs(tmp_path)
    lanes, _ = ls.from_gmns(gmns, source_db=src)
    lanes["width_m"] = lanes["width_m"].fillna(3.25)
    fc = lane_lines(lanes, ls.lane_settings())
    kinds = [f["properties"]["t"] for f in fc["features"]]
    assert sorted(kinds) == ["bridge_edge", "bridge_edge", "centre", "divider", "edge", "edge"]
    assert {f["properties"]["b"] for f in fc["features"]} == {"ground", "bridge"}   # link 2 is a bridge


def test_lane_lines_stop_short_of_a_junction():
    """Three roads meet at node 0 (link 1 from the south, 2 north, 3 east): link 1's east edge runs
    into link 3's surface (3.25 m wide) and stops junction_trim_m (1 m) short of it: cut 1.625 + 1 m.
    Link 2 goes straight on from link 1 (its lane starts where link 1's ends, same heading), so it
    is the same road and never cuts link 1's lines: the west edge keeps its full 100 m."""
    import geopandas as gpd
    from shapely.geometry import LineString
    from lanestyle.lines import lane_lines

    d = 100 / 111_320                                        # 100 m of latitude
    lanes = gpd.GeoDataFrame(
        {"link_id": [1, 2, 3], "lane_num": [1, 1, 1], "width_m": [3.25] * 3,
         "from_node_id": [1, 0, 0], "to_node_id": [0, 2, 3]},
        geometry=[LineString([(18.0, 59.3 - d), (18.0, 59.3)]), LineString([(18.0, 59.3), (18.0, 59.3 + d)]),
                  LineString([(18.0, 59.3), (18.002, 59.3)])], crs=4326)
    fc = lane_lines(lanes, ls.lane_settings({"lanes": {"lines": {"edge": {"dash_m": None}}}}))
    g = gpd.GeoDataFrame.from_features(fc["features"], crs=4326)
    one = sorted(g.to_crs(lanes.estimate_utm_crs()).length[:2])   # link 1's two edge lines, 100 m
    assert abs(one[0] - 97.375) < 0.3 and abs(one[1] - 100.0) < 0.3


def test_lines_off_and_without_link_columns(tmp_path):
    from lanestyle.lines import lane_lines

    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    assert "lane-lines" in ls.render_lanes(lanes, turns=turns).html
    assert "lane-lines" not in ls.render_lanes(lanes, settings={"lanes": {"lines": False}}).html
    assert lane_lines(lanes.drop(columns=["lane_num"]).assign(width_m=3.25), ls.lane_settings()) is None
    page = ls.render_lanes(lanes, turns=turns).html
    feats = json.loads(page.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])["sources"]["roads"]["data"]["features"]
    p = {f["properties"]["lane_id"]: f["properties"] for f in feats}["1_1"]
    assert p["highway"] == "secondary" and p["turns_out"] == 2 and p["turns_in"] == 0


def test_lines_at_a_sharp_bend_meet_instead_of_crossing():
    """Two one-way links continue each other at node 0 with a 150° turn (not a junction): neither
    link's lines may run into the other's surface (they crossed in an X, Monaco 662188420997239233)."""
    import geopandas as gpd
    from shapely.geometry import LineString
    from lanestyle.lines import lane_lines

    d = 30 / 111_320
    lanes = gpd.GeoDataFrame(
        {"link_id": [1, 2], "lane_num": [1, 1], "width_m": [3.25] * 2, "from_node_id": [1, 0], "to_node_id": [0, 2]},
        geometry=[LineString([(7.42, 43.73 - d), (7.42, 43.73)]),
                  LineString([(7.42, 43.73), (7.42 + 0.7 * d, 43.73 - 0.9 * d)])], crs=4326)
    fc = lane_lines(lanes, ls.lane_settings())
    crs = lanes.estimate_utm_crs()
    g = gpd.GeoDataFrame.from_features(fc["features"], crs=4326).to_crs(crs)
    surf = lanes.to_crs(crs).buffer(1.625, cap_style="flat")
    assert g.geometry[:2].intersection(surf[1].buffer(-0.01)).length.max() < 0.01   # link 1's lines
    assert g.geometry[2:].intersection(surf[0].buffer(-0.01)).length.max() < 0.01   # link 2's lines


def test_loop_halves_are_not_a_two_way_pair(tmp_path):
    """A one-way loop split in two (A->B, B->A, different geometry, Monaco way 120113154) is not a
    reverse pair: no reverse_link_id, so no centre line, and roadstyle doesn't pair them either."""
    gmns = tmp_path / "loop.duckdb"
    con = duckdb.connect(str(gmns))
    con.execute("INSTALL spatial; LOAD spatial; CREATE SCHEMA gmns_driving")
    con.execute("CREATE TABLE gmns_driving.link(link_id BIGINT, name VARCHAR, facility_type VARCHAR, "
                "from_node_id BIGINT, to_node_id BIGINT, geom GEOMETRY)")
    con.execute("CREATE TABLE gmns_driving.lane(lane_id VARCHAR, link_id BIGINT, lane_num BIGINT, "
                "allowed_uses VARCHAR, width DOUBLE, turn VARCHAR, geom GEOMETRY)")
    north = "ST_GeomFromText('LINESTRING(7.418 43.738, 7.4185 43.7384, 7.419 43.738)')"
    south = "ST_GeomFromText('LINESTRING(7.419 43.738, 7.4185 43.7376, 7.418 43.738)')"
    con.execute(f"INSERT INTO gmns_driving.link VALUES (1,NULL,'service',10,11,{north}),(2,NULL,'service',11,10,{south})")
    con.execute(f"INSERT INTO gmns_driving.lane VALUES ('1_1',1,1,'auto',NULL,NULL,{north}),('2_1',2,1,'auto',NULL,NULL,{south})")
    con.close()
    lanes, _ = ls.from_gmns(gmns)
    assert lanes["reverse_link_id"].isna().all()
    html = ls.render_lanes(lanes).html
    feats = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])["sources"]["roads"]["data"]["features"]
    assert not any(f["properties"].get("__rs_twoway") for f in feats)


def test_paired_one_way_roads_share_one_centre_line():
    """A road mapped as two one-way ways, placed side by side by duckOSM: the lane 1 left edges lie
    on each other, so they make one centre line (white), not two edge lines (Tunnel Dorsale)."""
    import geopandas as gpd
    from shapely.geometry import LineString
    from lanestyle.lines import lane_lines

    m = 1 / 111_320
    y = lambda off: 43.73 + off * m                           # metres north of the midline
    lanes = gpd.GeoDataFrame(
        {"link_id": [1, 1, 2, 2], "lane_num": [1, 2, 1, 2], "width_m": [3.25] * 4},
        geometry=[LineString([(7.42, y(-1.625)), (7.423, y(-1.625))]),   # east, south of the midline
                  LineString([(7.42, y(-4.875)), (7.423, y(-4.875))]),
                  LineString([(7.423, y(1.625)), (7.42, y(1.625))]),     # west, north of it
                  LineString([(7.423, y(4.875)), (7.42, y(4.875))])], crs=4326)
    kinds = sorted(f["properties"]["t"] for f in lane_lines(lanes, ls.lane_settings())["features"])
    assert kinds == ["centre", "divider", "divider", "edge", "edge"]


def test_turns_pair_movement_lanes_in_order(tmp_path):
    """A movement's lane ranges pair in order (duckOSM / osm2gmns): link 1's lane 2 into link 2's
    lane 1 only, not lane 1 as well."""
    gmns, src = _dbs(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("UPDATE gmns_driving.movement SET start_ib_lane=2, end_ib_lane=2, start_ob_lane=1, end_ob_lane=1 "
                "WHERE type='thru'")
    con.close()
    _, turns = ls.from_gmns(gmns)
    assert set(map(tuple, turns[turns["type"] == "thru"][["from_lane", "to_lane"]].values)) == {("1_2", "2_1")}


def test_lane_type_labels(tmp_path):
    """Each lane carries what it's for (the turns leaving it, 'end' where none does, the use first for a bus
    lane) in its popup data; the labels along the lanes are off unless ``type_label_zoom`` is set."""
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    feats = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])["sources"]["roads"]["data"]["features"]
    t = {f["properties"]["lane_id"]: f["properties"]["lane_type"] for f in feats}
    assert t == {"1_1": "U-turn + thru", "1_2": "bus · thru", "2_1": "end", "3_1": "end"}      # in the popup's data
    assert "lane-type-labels" not in html                         # but not drawn along the lanes by default
    assert '"lane-type-labels"' in ls.render_lanes(lanes, turns=turns, settings={"lanes": {"type_label_zoom": 18}}).html


def test_lane_connectors_drawn_and_coloured(tmp_path):
    """duckOSM's lane_connector rows become drawn connectors: the leaving lane's road class, no arrows,
    no type label, and coloured with the lane they lead into when a lane is clicked."""
    gmns, src = _dbs(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("LOAD spatial; CREATE TABLE gmns_driving.lane_connector(connector_id VARCHAR, mvmt_id VARCHAR, "
                "from_lane_id VARCHAR, to_lane_id VARCHAR, width DOUBLE, geom GEOMETRY)")
    con.execute("INSERT INTO gmns_driving.lane_connector VALUES ('1_1>2_1', 'm', '1_1', '2_1', 3.25, "
                "ST_GeomFromText('LINESTRING(18.01 59.30, 18.011 59.305, 18.00 59.31)'))")
    con.close()
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    c = lanes.set_index("lane_id").loc["1_1>2_1"]
    assert bool(c["connector"]) and c["highway"] == "secondary" and c["from_lane"] == "1_1"
    html = ls.render_lanes(lanes, turns=turns).html
    feats = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])["sources"]["roads"]["data"]["features"]
    p = {f["properties"]["lane_id"]: f["properties"] for f in feats}
    assert p["1_1>2_1"]["oneway"] is False and p["1_1"]["oneway"] is True
    assert p["1_1>2_1"]["lane_type"] == "connector · thru"
    assert p["1_1>2_1"]["connects"] == "lane 1 of Main St → lane 1 of Bridge Rd"
    t = json.loads(html.split("const T = ", 1)[1].split(", C = ", 1)[0])
    assert "1_1>2_1" in t["1_1"][0]
    assert "line-cap" not in html.split("</body>")[0].split("const T = ")[-1]   # lane ends stay round, tunnels too


def test_read_boundary(tmp_path):
    """The area's boundary from a duckOSM db (main.boundary), None without one; drawn as an outline."""
    gmns, src = _dbs(tmp_path)
    assert ls.read_boundary(src) is None
    con = duckdb.connect(str(src))
    con.execute("INSTALL spatial; LOAD spatial; CREATE TABLE main.boundary(name VARCHAR, geom GEOMETRY)")
    con.execute("INSERT INTO main.boundary VALUES ('x', ST_GeomFromText('POLYGON((17.99 59.29, 18.02 59.29, 18.02 59.33, 17.99 59.33, 17.99 59.29))'))")
    con.close()
    b = ls.read_boundary(src)
    assert b is not None and b.geom_type == "Polygon"
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    st = json.loads(ls.render_lanes(lanes, turns=turns, boundary=b).html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])
    assert "boundary" in st["sources"] and any(l["id"] == "boundary" for l in st["layers"])


def _with_walking(tmp_path):
    """_dbs plus a walking schema: footway link 5 (lane 5_1, use walk), the road link 2 walked on (lane 2_1, use walk),
    and a movement from the footway onto the road."""
    gmns, src = _dbs(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("INSTALL spatial; LOAD spatial; CREATE SCHEMA gmns_walking")
    ln = lambda y: f"ST_GeomFromText('LINESTRING(18.00 {y}, 18.01 {y})')"
    con.execute("CREATE TABLE gmns_walking.link(link_id BIGINT, name VARCHAR, facility_type VARCHAR, "
                "from_node_id BIGINT, to_node_id BIGINT)")
    con.execute("INSERT INTO gmns_walking.link VALUES (2,'Bridge Rd','tertiary',11,12),(5,NULL,'footway',13,11)")
    con.execute("CREATE TABLE gmns_walking.lane(lane_id VARCHAR, link_id BIGINT, lane_num BIGINT, allowed_uses VARCHAR, "
                "width DOUBLE, turn VARCHAR, geom GEOMETRY)")
    con.execute(f"INSERT INTO gmns_walking.lane VALUES ('2_1',2,1,'walk',NULL,NULL,{ln(59.31)}),"
                f"('5_1',5,1,'walk',NULL,NULL,{ln(59.335)})")
    con.execute("CREATE TABLE gmns_walking.movement(ib_link_id BIGINT, start_ib_lane BIGINT, end_ib_lane BIGINT, "
                "ob_link_id BIGINT, start_ob_lane INTEGER, end_ob_lane INTEGER, type VARCHAR)")
    con.execute("INSERT INTO gmns_walking.movement VALUES (5,NULL,NULL,2,NULL,NULL,'thru')")
    con.close()
    return gmns, src


def test_modes_add_only_the_footpaths_not_the_roads_walked_on(tmp_path):
    gmns, src = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    assert set(lanes.lane_id) == {"1_1", "1_2", "2_1", "3_1", "5_1"}        # the road's own walk lane is not added
    r = lanes.set_index("lane_id")
    assert r.loc["5_1", "use"] == "walk" and r.loc["1_2", "use"] == "bus" and r.loc["2_1", "use"] == "auto"
    assert lanes["link_id"].dtype == "Int64"
    assert ("5_1", "2_1") in set(zip(turns["from_lane"], turns["to_lane"]))   # the footway leads onto the road
    assert set(turns["from_lane"]) | set(turns["to_lane"]) <= set(lanes.lane_id)
    only, _ = ls.from_gmns(gmns, mode="walking")                             # one mode: unchanged
    assert set(only.lane_id) == {"2_1", "5_1"}
    assert set(ls.from_gmns(gmns)[0].lane_id) == {"1_1", "1_2", "2_1", "3_1"}


def test_modes_skip_the_other_direction_of_a_road_walked_on(tmp_path):
    """The walking network has a link for the way a one-way road is not driven (here 6, the reverse of road 2): the same
    OSM way as the driving link, so not a footpath of its own."""
    gmns, _ = _with_walking(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("LOAD spatial")
    for sch in ("driving", "walking"):
        con.execute(f"ALTER TABLE gmns_{sch}.link ADD COLUMN osm_id BIGINT")
    con.execute("UPDATE gmns_driving.link SET osm_id = link_id + 900; UPDATE gmns_walking.link SET osm_id = link_id + 900")
    con.execute("INSERT INTO gmns_walking.link VALUES (6,'Bridge Rd','tertiary',12,11,902)")
    con.execute("INSERT INTO gmns_walking.lane VALUES ('6_1',6,1,'walk',NULL,NULL,ST_GeomFromText('LINESTRING(18.01 59.311, 18.00 59.311)'))")
    con.close()
    lanes, _ = ls.from_gmns(gmns, modes=("driving", "walking"))
    assert "6_1" not in set(lanes.lane_id) and "5_1" in set(lanes.lane_id)


def test_footpaths_are_one_surface_with_one_outline_and_no_lines_inside():
    """Two footpaths crossing (each a strip, one per direction, on top of each other): no centre or divider line, no
    edge line through the crossing, just the outline of the union; a road's surface cuts it."""
    import geopandas as gpd
    from shapely.geometry import LineString

    from lanestyle.lines import lane_lines

    lines = [("w1", 1, "walk", [(18.000, 59.3), (18.001, 59.3)]), ("w2", 2, "walk", [(18.001, 59.3), (18.000, 59.3)]),
             ("w3", 3, "walk", [(18.0005, 59.2999), (18.0005, 59.3001)])]
    lanes = gpd.GeoDataFrame({"lane_id": [l[0] for l in lines], "link_id": [l[1] for l in lines], "lane_num": 1, "use": "walk",
                              "width_m": 2.0}, geometry=[LineString(l[3]) for l in lines], crs=4326)
    fc = lane_lines(lanes, ls.lane_settings())
    assert {f["properties"]["t"] for f in fc["features"]} == {"edge"}                 # no centre line, no divider
    assert len(fc["features"]) == 1                                                   # the outline of the union is one line
    lanes.loc[2, "use"] = "auto"                                                      # as a road, the same strip cuts the outline
    assert {f["properties"]["t"] for f in lane_lines(lanes, ls.lane_settings())["features"]} >= {"edge"}


def test_the_popup_always_says_the_level(tmp_path):
    """A ground lane would otherwise show nothing about bridges (null fields are hidden): `level` says ground / bridge."""
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    assert '"level"' in html and '"bridge"' in html and '"ground"' in html     # link 2 is a bridge, the others ground


def test_the_popup_names_the_twin_of_a_link(tmp_path):
    """Links 1 and 3 are one two-way road: each says the other is its twin; the one-way bridge (link 2) has none."""
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    assert "(reverse: the same line)" in html and '"twin"' in html


def _crossing(lane_id="2_1", painted=True, to_left=True, start=200.0, end=203.0):
    """A crossing table row for road 2 (east-west at y = 59.31): the zebra's rectangle, 3 m along the road, 6.5 m across it."""
    import pandas as pd

    x = 18.0 + (start + end) / 2 / 56700
    dx, dy = 1.5 / 56700, 3.25 / 111320
    rect = f"POLYGON (({x + dx} {59.31 - dy}, {x + dx} {59.31 + dy}, {x - dx} {59.31 + dy}, {x - dx} {59.31 - dy}, {x + dx} {59.31 - dy}))"
    return pd.DataFrame({"crossing_id": ["w1"], "lane_id": [lane_id], "start_lr": [start], "end_lr": [end], "across_from": [1.6],
                         "across_to": [4.85], "to_left": [to_left], "painted": [painted], "length": [6.5],
                         "crossing_type": ["marked"], "source": ["way"], "cgeom": [rect]})


def test_a_zebra_is_one_rectangle_cut_into_stripes_parallel_to_the_lanes(tmp_path):
    """The crossing's rectangle (3 m along the road, 6.5 m across) cut into stripes, each long along the road (x) and stripe_m thin
    across it (y), then clipped to the lane the table names (3.25 m wide): the stripes are the same as the rectangle's, only those on the lane."""
    from lanestyle.render import _zebra_stripes

    gmns, _ = _with_walking(tmp_path)
    lanes, _t = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["width_m"] = lanes["width_m"].fillna(3.25)
    st = ls.lane_settings()["zebra"]
    rings, foot = _zebra_stripes(lanes, _crossing(), st)
    assert len(rings) == 3                                         # 6.5 m across: stripes 0.5 m every 1.0 m; the lane (3.25 m, across 1.6 .. 4.85) keeps the middle three
    for ring in rings:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        assert (max(xs) - min(xs)) * 56700 == pytest.approx(3.0, abs=0.05)         # as long as the zebra is wide, whatever the lane's ends
        assert (max(ys) - min(ys)) * 111320 == pytest.approx(0.5, abs=0.05)        # one stripe across it
    ys = sorted(sum(p[1] for p in r) / len(r) for r in rings)
    assert all(abs((ys[i + 1] - ys[i]) * 111320 - 1.0) < 0.05 for i in range(2))     # equally spaced: cut from one rectangle
    assert foot is not None and foot.geom_type == "Polygon"
    assert _zebra_stripes(lanes, _crossing(painted=False), st) == ([], None)       # unpainted: none


def test_a_painted_crossing_adds_the_zebra_layer_and_the_crossing_way_stays_under_the_road(tmp_path):
    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["footway"] = None
    lanes.loc[lanes["lane_id"] == "5_1", "footway"] = "crossing"
    html = ls.render_lanes(lanes, turns=turns, crossings=_crossing()).html
    assert 'map.addSource("zebra"' in html and '"band_col"' not in html and "draw_band" not in html
    assert 'map.addSource("zebra"' not in ls.render_lanes(lanes, turns=turns, crossings=_crossing(painted=False)).html
    assert 'map.addSource("zebra"' not in ls.render_lanes(lanes, turns=turns).html


def test_no_lane_line_under_a_zebra_crossing():
    """The zebra's stripes are the road's marking there: the lane lines (dashes, centre, edges) stop at its stretch."""
    import geopandas as gpd
    from shapely.geometry import LineString, box

    from lanestyle.lines import lane_lines

    rows = [("a1", 1, 1, [(18.000, 59.3), (18.001, 59.3)]), ("a2", 1, 2, [(18.000, 59.29997), (18.001, 59.29997)])]
    lanes = gpd.GeoDataFrame({"lane_id": [r[0] for r in rows], "link_id": [r[1] for r in rows], "lane_num": [r[2] for r in rows],
                              "use": "auto", "width_m": 3.25}, geometry=[LineString(r[3]) for r in rows], crs=4326)
    avoid = box(18.0004, 59.2998, 18.0006, 59.3002)                      # a 2e-4 deg zebra square over both lanes
    xs = [x for f in lane_lines(lanes, ls.lane_settings(), avoid=avoid)["features"]
          for line in ([f["geometry"]["coordinates"]] if f["geometry"]["type"] == "LineString" else f["geometry"]["coordinates"]) for x, _ in line]
    assert xs and not any(18.0004 < x < 18.0006 for x in xs)


def test_a_link_with_no_road_class_is_not_drawn(tmp_path):
    """A ferry in the walking network has no road class (highway null): it is no lane."""
    from lanestyle.render import _roads_only

    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes.loc[lanes["lane_id"] == "5_1", "highway"] = None
    kept = set(_roads_only(lanes)["lane_id"])
    assert "5_1" not in kept and "1_1" in kept and len(kept) == len(lanes) - 1
    ls.render_lanes(lanes, turns=turns)                                       # and the map still renders


def test_the_popup_says_what_a_footway_is(tmp_path):
    """highway=footway + footway=crossing is a crosswalk, not "a footway": a `kind` row says so (and sidewalk for a sidewalk)."""
    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["footway"] = None
    lanes["crossing"] = None
    lanes.loc[lanes["lane_id"] == "5_1", ["footway", "crossing"]] = ["crossing", "marked"]
    html = ls.render_lanes(lanes, turns=turns, settings={"lanes": {"crossing_max_m": 0}}).html     # (a crossing off every road is demoted: next test)
    assert '"kind"' in html and "crosswalk (marked)" in html


def test_a_crossing_that_is_mostly_off_the_road_is_drawn_as_a_footway(tmp_path):
    """OSM tags a whole 173 m way footway=crossing where only its end crosses (1342546079): a long link with almost nothing on a road is a footway."""
    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["footway"] = None
    lanes["crossing"] = None
    lanes.loc[lanes["lane_id"] == "5_1", ["footway", "crossing"]] = ["crossing", "marked"]
    from lanestyle.render import _demote_crossings
    g = lanes.copy()
    g["demoted"] = None
    _demote_crossings(g, {"crossing_max_m": 0.1, "crossing_min_on": 0.2})                # any length counts as long here
    assert g.loc[g["lane_id"] == "5_1", "footway"].isna().all() and "OSM tags it a crossing" in g.loc[g["lane_id"] == "5_1", "demoted"].iloc[0]
    g = lanes.copy()
    g["demoted"] = None
    _demote_crossings(g, {"crossing_max_m": 1e6, "crossing_min_on": 0.2})                # a short one stays a crosswalk
    assert (g.loc[g["lane_id"] == "5_1", "footway"] == "crossing").all()


def test_footways_of_two_levels_meeting_at_a_node_each_keep_their_own_outline():
    """Steps down into a tunnel (layer -1) meet a ground footway at node 2. A tunnel differs in colour and pattern only: each level keeps its own outline all along,
    and only where the other footway's surface lies by the shared node is it cut (no cap over the neighbour)."""
    import geopandas as gpd
    from shapely.geometry import LineString

    from lanestyle.lines import lane_lines

    rows = [("g", 1, 1, 2, None, [(18.000, 59.3), (18.0005, 59.3)]), ("t", 2, 2, 3, "-1", [(18.0005, 59.3), (18.0015, 59.3)])]
    lanes = gpd.GeoDataFrame({"lane_id": [r[0] for r in rows], "link_id": [r[1] for r in rows], "lane_num": 1, "use": "walk", "width_m": 2.0,
                              "from_node_id": [r[2] for r in rows], "to_node_id": [r[3] for r in rows],
                              "layer": [r[4] for r in rows]}, geometry=[LineString(r[5]) for r in rows], crs=4326)
    fc = lane_lines(lanes, ls.lane_settings())

    def xs(band):
        return [x for f in fc["features"] if f["properties"]["b"] == band
                for line in ([f["geometry"]["coordinates"]] if f["geometry"]["type"] == "LineString" else f["geometry"]["coordinates"]) for x, _ in line]
    ground, low = xs("ground"), xs("low")
    assert ground and low                                           # both levels are outlined
    assert max(ground) < 18.0005 + 1.5 / 56700                      # the ground outline stops at its own end: it does not run on over the steps
    assert max(low) > 18.0015 - 1.5 / 56700                         # the tunnel's outline runs along it to its far end ...
    assert min(low) < 18.0005 + 3.0 / 56700                         # ... and starts by the node: no seam, no stretch left without a line


def test_default_widths_by_use():
    import pandas as pd
    from lanestyle.render import _widths, lane_settings
    g = pd.DataFrame({"use": ["auto", "walk", "bike", "bike", "bike", "walk"],
                      "lane_num": [1, 1, 2, 1, 1, 1], "lanes": [2, None, 1, 2, None, 1],
                      "width_m": [None, None, None, None, None, 2.5]})
    # auto 3.25; walk 2.0; a bike lane beyond the 1 motor lane 1.5; a bike lane that is one of 2 motor lanes 3.25;
    # a bike lane on a cycleway (no motor lanes) 1.5; a tagged width is kept
    assert _widths(g, lane_settings()).tolist() == [3.25, 2.0, 1.5, 3.25, 1.5, 2.5]
    assert _widths(g, lane_settings({"lanes": {"width_m_by_use": {"walk": 1.2}}})).tolist()[1] == 1.2
    # without lane_num / lanes the bike rule cannot tell, so a bike lane keeps the default
    assert _widths(g.drop(columns=["lane_num", "lanes"]), lane_settings()).tolist()[2] == 3.25


def test_several_modes_colour_a_lane_by_the_set_of_modes_that_can_use_it(tmp_path):
    """A street cars and pedestrians share, a car-only road and a pedestrian-only footway are three colours, each with a
    Roads-box row; a bus lane keeps its own. One mode: the lane's use, as before."""
    gmns, src = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    r = lanes.set_index("lane_id")
    assert r.loc["2_1", "modes"] == "driving,walking" and r.loc["5_1", "modes"] == "walking"   # link 2 is in both networks
    assert r.loc["1_1", "modes"] == "driving"
    html = ls.render_lanes(lanes, turns=turns).html
    for row in ("cars only", "cars + pedestrians", "pedestrians only", "bus lanes"):
        assert row in html, row
    assert "#7fb7a8" in html and "#f0cb8c" in html                          # the shared street, the footway
    feats = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])["sources"]["roads"]["data"]["features"]
    g = {f["properties"]["lane_id"]: f["properties"]["mode_group"] for f in feats}
    assert g == {"1_1": "driving", "1_2": "bus", "2_1": "driving+walking", "3_1": "driving", "5_1": "walking"}
    single = ls.render_lanes(*ls.from_gmns(gmns)).html                      # one mode: by use, no groups
    assert "cars + pedestrians" not in single and "mode_group" not in single and "car lanes" in single


def test_a_tunnel_is_one_whole_lane_in_its_band_and_a_bridge_keeps_its_look(tmp_path):
    """roadstyle's levels and looks: the level alone decides the band, so a tunnel lane is drawn whole, under the
    ground lanes, with its own look (no stretches to hide its arrows and lane lines); a bridge keeps its deck look."""
    gmns, src = _dbs(tmp_path)
    html = ls.render_lanes(*ls.from_gmns(gmns, source_db=src)).html
    style = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])
    p = {f["properties"]["lane_id"]: f["properties"] for f in style["sources"]["roads"]["data"]["features"]}
    assert p["2_1"]["lvl"] == 1 and p["2_1"]["__rs_bridge"] and not p["2_1"]["__rs_tunnel"]    # the bridge: its look
    assert "tpieces" not in style["sources"]                       # nothing cut into stretches
    assert "moveLayer" not in html.split("const T = ")[-1]         # and no arrow workaround


def test_every_lane_is_coloured_by_its_mode_group(tmp_path):
    gmns, src = _dbs(tmp_path)
    html = ls.render_lanes(*ls.from_gmns(gmns, source_db=src)).html
    assert '"Lane use"' in html and '"#a3a3a3"' in html           # cars have their own colour, not the class's
    assert '"color_active"' in html or "_coActive = 1" in html     # and it is the colouring the page opens with


def test_a_footpath_has_no_arrow_and_a_tunnel_is_as_opaque_as_a_road(tmp_path):
    gmns, src = _with_walking(tmp_path)
    html = ls.render_lanes(*ls.from_gmns(gmns, modes=("driving", "walking"))).html
    feats = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])["sources"]["roads"]["data"]["features"]
    arrow = {f["properties"]["lane_id"]: f["properties"]["oneway"] for f in feats}
    assert arrow["5_1"] in (0, False) and arrow["1_1"] in (1, True) and arrow["2_1"] in (1, True)   # walk: none; roads: yes


def test_join_footways_only_at_a_shared_node():
    import geopandas as gpd
    from shapely.geometry import LineString
    from lanestyle.gmns import _join_footways

    def lane(i, use, a, b, line):
        return dict(lane_id=i, use=use, from_node_id=a, to_node_id=b, connector=False, width_m=3.0 if use == "auto" else None, geometry=line)

    road = lane("r", "auto", 1, 2, LineString([(7.0, 43.0), (7.0001, 43.00002)]))      # ends 2 m beside node 2
    foot = lane("f", "walk", 2, 3, LineString([(7.0001, 43.0), (7.0002, 43.0)]))      # starts on node 2
    lanes = _join_footways(gpd.GeoDataFrame([road, foot], crs=4326))
    c = lanes[lanes["connector"]]
    assert len(c) == 1 and c.iloc[0]["from_lane"] == "r" and c.iloc[0]["to_lane"] == "f"
    foot["from_node_id"] = 9                                                          # no shared node: nothing is added
    assert not _join_footways(gpd.GeoDataFrame([road, foot], crs=4326))["connector"].any()


def test_a_tunnel_differs_from_ground_in_look_only(tmp_path):
    """Kaveh (2026-10-02, said several times): the only difference of a tunnel is its colour and pattern. The same lane table at ground level and as a tunnel
    (every lane layer -1, tunnel yes) gives the same outlines, lane lines and gap fills, the same footpaths drawn above roads and the same draw order: only the level label differs."""
    from lanestyle.frames import frames
    from lanestyle.lines import lane_lines
    from lanestyle.render import _footpaths_on_roads, _widths

    gmns, _ = _with_walking(tmp_path)
    s = ls.lane_settings()
    ground, _ = ls.from_gmns(gmns, modes=("driving", "walking"))
    ground["use"] = ground["use"].fillna("auto")
    ground["width_m"] = _widths(ground, s)
    tunnel = ground.copy()
    tunnel["layer"], tunnel["tunnel"] = "-1", "yes"

    def shape(fc):                                                   # the lines without their level label
        return sorted((f["properties"]["t"], str(f["geometry"])) for f in (fc or {"features": []})["features"])
    assert {f["properties"]["b"] for f in lane_lines(ground, s)["features"]} <= {"ground"}
    assert {f["properties"]["b"] for f in lane_lines(tunnel, s)["features"]} == {"low"}
    assert shape(lane_lines(ground, s)) == shape(lane_lines(tunnel, s))
    gg, _, _ = frames(ground, s)
    gt, _, _ = frames(tunnel, s)
    assert [f["geometry"] for f in (gg or {"features": []})["features"]] == [f["geometry"] for f in (gt or {"features": []})["features"]]
    assert _footpaths_on_roads(ground) == _footpaths_on_roads(tunnel)


def test_tunnels_on_different_layers_do_not_touch():
    """Kaveh (2026-10-02): a footway on layer -1 and a road on layer -2 are on different levels and shouldn't be connected. roadstyle draws every layer below ground in one band,
    but nothing is cut, merged or matched across layers: the footway's outline is the same with the road there or not."""
    import geopandas as gpd
    from shapely.geometry import LineString

    from lanestyle.lines import lane_lines

    def table(road_layer):
        rows = [("f", 1, "walk", "-1", [(18.000, 59.3), (18.002, 59.3)], 2.0)]
        if road_layer is not None:
            rows.append(("r", 2, "auto", road_layer, [(18.001, 59.2999), (18.001, 59.3001)], 3.25))      # crosses the footway, no shared node
        return gpd.GeoDataFrame({"lane_id": [r[0] for r in rows], "link_id": [r[1] for r in rows], "lane_num": 1, "use": [r[2] for r in rows],
                                 "width_m": [r[5] for r in rows], "from_node_id": [10 * r[1] for r in rows], "to_node_id": [10 * r[1] + 1 for r in rows],
                                 "layer": [r[3] for r in rows], "tunnel": "yes"}, geometry=[LineString(r[4]) for r in rows], crs=4326)

    def foot_edge_len(fc):                                           # the edge lines that run along the footway (y within its width), whatever the road does
        n = 0
        for f in fc["features"]:
            if f["properties"]["t"] != "edge":
                continue
            lines = [f["geometry"]["coordinates"]] if f["geometry"]["type"] == "LineString" else f["geometry"]["coordinates"]
            n += sum(abs(b[0] - a[0]) for line in lines for a, b in zip(line, line[1:]) if abs(a[1] - 59.3) < 2e-5 and abs(b[1] - 59.3) < 2e-5)
        return round(n, 7)
    s = ls.lane_settings()
    alone = foot_edge_len(lane_lines(table(None), s))
    assert alone > 0
    assert foot_edge_len(lane_lines(table("-2"), s)) == alone        # a road on another layer cuts nothing of it ...
    assert foot_edge_len(lane_lines(table("-1"), s)) < alone         # ... one on its own layer does (the footway's outline stops at the road)


def test_a_road_connector_ranks_over_a_footway_and_a_walk_one_stays_below():
    """A footway ending on a road must not show over the road's connector fill (Boulevard Rainier III, Monaco): a connector cars use
    ranks just under its road class, above footway (1) and under the lanes of its class; a walking-only connector stays at the bottom."""
    from lanestyle.render import _connector_order
    assert _connector_order(False, "residential", "driving,walking", -300, -250) == 3.5 > 1      # over a footway (z 1), under residential lanes (4)
    assert _connector_order(True, "residential", "driving", -300, -250) == 3.4
    assert _connector_order(False, "residential", "walking", -300, -250) == -250                  # a footway's own connector
    assert _connector_order(False, "residential", "", -30, -20) > 1                               # no mode data: a road's
