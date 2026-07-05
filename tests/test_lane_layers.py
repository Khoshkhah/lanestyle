"""Tests for lanestyle — lane polygon layers + route layer (reusing mapstyle)."""
import duckdb
import pytest

from lanestyle.core import lane_gdf, lane_layers, render_lane_debug, render_lane_map, route_layer


def _gmns_lane_db(path):
    """A minimal GMNS db: a gmns_driving.lane table with one auto + one bus lane."""
    con = duckdb.connect(str(path))
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("CREATE SCHEMA gmns_driving")
    con.execute("CREATE TABLE gmns_driving.lane(lane_id VARCHAR, link_id BIGINT, lane_num INTEGER, "
                "allowed_uses VARCHAR, width DOUBLE, geom GEOMETRY)")
    p = "ST_GeomFromText('LINESTRING(18.06 59.32, 18.07 59.32)')"
    con.execute(f"INSERT INTO gmns_driving.lane VALUES ('1_1',1,1,'auto',3.25,{p}),"
                f"('1_2',1,2,'bus',3.25,{p})")
    con.close()
    return path


def test_lane_layers(tmp_path):
    layers = lane_layers(str(_gmns_lane_db(tmp_path / "g.duckdb")))
    names = {L.name: L for L in layers}
    assert set(names) == {"lanes_auto", "lanes_bus"}          # one layer per present use
    assert all(L.kind == "polygon" for L in layers)
    assert names["lanes_auto"].color == "#8fa2b4" and names["lanes_bus"].color == "#e8944a"
    g = names["lanes_auto"].gdf
    assert (g.geometry.geom_type == "Polygon").all() and g.geometry.is_valid.all()   # real surfaces
    assert g.crs.to_epsg() == 4326


def test_route_layer(tmp_path):
    rj = tmp_path / "route.geojson"
    rj.write_text('{"type":"FeatureCollection","features":[{"type":"Feature",'
                  '"properties":{"maneuvers":["left turn"]},'
                  '"geometry":{"type":"LineString","coordinates":[[18.06,59.32],[18.07,59.32]]}}]}')
    L = route_layer(str(rj))
    assert L.kind == "line" and L.color == "#ffd400"
    assert "highway" in L.gdf.columns and "maneuvers" not in L.gdf.columns   # list prop dropped


def test_render_lane_map(tmp_path):
    out = tmp_path / "lanes.html"
    render_lane_map(str(_gmns_lane_db(tmp_path / "g.duckdb")), out)
    html = out.read_text()
    assert out.exists() and "lanes_auto" in html and "lanes_bus" in html      # both layers present


def test_lane_gdf(tmp_path):
    gdf = lane_gdf(str(_gmns_lane_db(tmp_path / "g.duckdb")))
    assert {"use", "lane", "edge_id", "width"}.issubset(gdf.columns)
    assert (gdf.geometry.geom_type == "Polygon").all() and gdf.crs.to_epsg() == 4326
    assert set(gdf["use"]) == {"auto", "bus"}


def test_render_lane_debug(tmp_path):
    out = tmp_path / "debug.html"
    render_lane_debug(str(_gmns_lane_db(tmp_path / "g.duckdb")), out)
    html = out.read_text()
    assert out.exists() and "edge_id" in html and "lanes_auto" in html    # tooltip field + toggle
    assert "GeoJsonTooltip" in html or "aliases" in html.replace(" ", "")  # per-lane inspection wired


def test_serve_py_written(tmp_path):
    out = tmp_path / "lanes.html"
    render_lane_map(str(_gmns_lane_db(tmp_path / "g.duckdb")), out)          # serve=True by default
    serve = tmp_path / "serve.py"
    assert serve.exists()
    src = serve.read_text()
    assert "lanes.html" in src and "http.server" in src                     # points to the map, static server
    compile(src, str(serve), "exec")                                        # valid Python


def test_bad_db_raises(tmp_path):
    bare = tmp_path / "bare.duckdb"
    duckdb.connect(str(bare)).close()
    with pytest.raises(ValueError, match="lane"):
        lane_layers(str(bare))
