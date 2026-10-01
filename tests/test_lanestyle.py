"""lanestyle: the GMNS reader (from_gmns) and the roadstyle engine (render_lanes)."""
import json
import sys

import duckdb

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
    assert r.loc["1_1", "name"] == "Main St" and r.loc["1_2", "name"] != r.loc["1_2", "name"]   # NaN: lane 1 only
    assert r.loc["1_1", "link_id"] == 8121729169906061189                           # exact, not float
    assert r.loc["2_1", "bridge"] == "yes" and r.loc["2_1", "layer"] == "1"         # from source_db
    got = set(map(tuple, turns[["from_lane", "to_lane", "type"]].values))
    assert got == {("1_1", "2_1", "thru"), ("1_2", "2_1", "thru"), ("1_1", "3_1", "uturn")}
    # without source_db: every lane at ground level
    assert "bridge" not in ls.from_gmns(gmns)[0].columns


def test_render_lanes_metre_widths_uses_and_click(tmp_path):
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    assert '"__rs_wm"' in html                                    # widths in metres (roadstyle 0.10)
    assert "Lane use" in html and "#c9783a" in html and "#3f8fc9" not in html   # bus only: no bike
    t = json.loads(html.split("const T = ", 1)[1].split(", C = ", 1)[0])
    assert t["1_1"] == [["2_1"], ["3_1"]] and t["1_2"] == [["2_1"], []]


def test_settings_override_the_roadstyle_way(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lanestyle.json").write_text('{"lanes": {"casing_m": 0.1}}')
    s = ls.lane_settings({"lanes": {"colors": {"bus": "#123456"}}})
    assert s["casing_m"] == 0.1 and s["colors"]["bus"] == "#123456" and s["colors"]["bike"] == "#3f8fc9"


def test_write_serve_index_html_does_not_loop(tmp_path):
    src = ls.write_serve(tmp_path / "index.html").read_text()
    assert 'self.path != "/index.html"' in src


def test_lane_lines_types(tmp_path):
    """Link 1 (2 lanes) and link 3 are one two-way road: one divider, one centre line (drawn by the
    smaller id, link 3), edges on the outside; link 2 is one-way: edges on both sides."""
    from lanestyle.lines import lane_lines

    gmns, src = _dbs(tmp_path)
    lanes, _ = ls.from_gmns(gmns, source_db=src)
    lanes["width_m"] = lanes["width_m"].fillna(3.25)
    fc = lane_lines(lanes, ls.lane_settings())
    kinds = [f["properties"]["t"] for f in fc["features"]]
    assert sorted(kinds) == ["centre", "divider", "edge", "edge", "edge", "edge"]
    assert {f["properties"]["b"] for f in fc["features"]} == {"ground", "bridge"}   # link 2 is a bridge


def test_lane_lines_stop_short_of_a_junction():
    """Three roads meet at node 0 (link 1 from the south, 2 north, 3 east): link 1's lines stop
    junction_trim_m (1 m) short of the other roads' surface, so its east edge, which runs into
    link 3 (3.25 m wide), is cut 1.625 + 1 m short, its west edge 1 m (link 2 starts at the node)."""
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
    assert abs(one[0] - 97.375) < 0.3 and abs(one[1] - 99.0) < 0.3


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
    """Each lane is labelled with what it's for: the turns leaving it, 'end' where none does, the
    use first for a bus lane; the labels layer is added to the page."""
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    feats = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])["sources"]["roads"]["data"]["features"]
    t = {f["properties"]["lane_id"]: f["properties"]["lane_type"] for f in feats}
    assert t == {"1_1": "U-turn + thru", "1_2": "bus · thru", "2_1": "end", "3_1": "end"}
    assert '"lane-type-labels"' in html
    assert "lane-type-labels" not in ls.render_lanes(lanes, turns=turns, settings={"lanes": {"type_label_zoom": None}}).html
