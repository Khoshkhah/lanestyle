"""
lanestyle — **standalone** lane-level maps from a duckOSM **GMNS** db. No dependency on mapstyle (or
any renderer beyond folium). Reads ``gmns_<mode>.lane`` (drive-side offset centerline + width), buffers
each lane into a surface polygon coloured by use, and draws it on an interactive folium map with a
base-layer selector, click-to-inspect, street names and one-way arrows. An optional lane route (from
duckOSM's ``route-lanes``) is drawn on top.

    from lanestyle import render_lane_map, render_lane_debug
    render_lane_map("../duckOSM/data/db/tartu_gmns.duckdb", "lanes.html")
    render_lane_debug("../duckOSM/data/db/tartu_gmns.duckdb", "lanes_debug.html", route_geojson="route.geojson")
"""
_LANE_W = 3.25
_USE_COLOR = {"auto": "#8fa2b4", "bus": "#e8944a", "bike": "#5ab0e6"}     # lane fill by allowed use
_ROUTE_COLOR = "#ffd400"

_SERVE_PY = '''#!/usr/bin/env python3
"""Static server for this lanestyle render.
   python serve.py [port]   ->  http://localhost:8080/__INDEX__"""
import sys, http.server, socketserver
from functools import partial
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):          # so the root URL just opens the map
            self.send_response(302)
            self.send_header("Location", "/__INDEX__")
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


socketserver.TCPServer.allow_reuse_address = True
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
here = str(Path(__file__).resolve().parent)
for p in range(port, port + 20):                       # 8080 busy? hop to the next free port
    try:
        httpd = socketserver.TCPServer(("", p), partial(Handler, directory=here))
    except OSError:
        continue
    if p != port:
        print(f"port {port} busy -> using {p}")
    print(f"serving {here}")
    print(f"  open:    http://localhost:{p}/   (-> __INDEX__)")
    print(f"  REMOTE:  forward port {p}  (VS Code auto-forwards it in the Ports panel; "
          f"or `ssh -L {p}:localhost:{p} <host>`), then open the URL above")
    httpd.serve_forever()
    break
else:
    sys.exit(f"no free port in {port}..{port + 19}")
'''


def write_serve(out_html):
    """Drop a ``serve.py`` next to ``out_html`` — ``python serve.py [port]`` serves that folder (auto-hops
    off a busy port) and prints the map URL. Returns the serve.py path."""
    from pathlib import Path

    out_html = Path(out_html)
    serve = out_html.parent / "serve.py"
    serve.write_text(_SERVE_PY.replace("__INDEX__", out_html.name))
    return serve


def lane_gdf(gmns_db, mode="driving"):
    """All lanes of ``gmns_<mode>.lane`` as one GeoDataFrame of **surface polygons** (offset centerline
    buffered by ½·width, metric → WGS84) with ``use`` / ``lane`` / ``edge_id`` / ``width`` columns."""
    import duckdb
    import geopandas as gpd
    import shapely.wkt as wkt

    g = f"gmns_{mode}"
    con = duckdb.connect(str(gmns_db), read_only=True)
    con.execute("INSTALL spatial; LOAD spatial;")
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE schema_name=? AND table_name='lane'",
                   [g]).fetchone()[0] == 0:
        con.close()
        raise ValueError(f"no '{g}.lane' in {gmns_db} — build a GMNS db first (duckOSM `duckosm gmns`)")
    rows = con.execute(
        f"SELECT allowed_uses, lane_num, link_id, COALESCE(width, {_LANE_W}) AS w, "
        f"ST_AsText(ST_Transform(ST_Buffer("
        f"  ST_Transform(geom, 'EPSG:4326', 'EPSG:3006', always_xy := true), COALESCE(width, {_LANE_W})/2.0), "
        f"  'EPSG:3006', 'EPSG:4326', always_xy := true)) "
        f"FROM {g}.lane WHERE geom IS NOT NULL").fetchall()
    con.close()
    rows = [r for r in rows if r[4] and r[4].startswith(("POLYGON", "MULTIPOLYGON"))]
    return gpd.GeoDataFrame(
        {"use": [r[0] for r in rows], "lane": [r[1] for r in rows], "edge_id": [str(r[2]) for r in rows],
         "width": [round(float(r[3]), 2) for r in rows]},
        geometry=[wkt.loads(r[4]) for r in rows], crs="EPSG:4326")


def road_gdf(gmns_db, mode="driving"):
    """Roads (``gmns_<mode>.link`` centerlines) with ``name`` + ``oneway`` — for street-name labels and
    one-way arrows. ``oneway`` = the link has no reverse pair (a two-way road is two links)."""
    import duckdb
    import geopandas as gpd
    import shapely.wkt as wkt

    g = f"gmns_{mode}"
    con = duckdb.connect(str(gmns_db), read_only=True)
    con.execute("INSTALL spatial; LOAD spatial;")
    rows = con.execute(
        f"WITH tw AS (SELECT a.link_id FROM {g}.link a JOIN {g}.link b "
        f"            ON a.from_node_id=b.to_node_id AND a.to_node_id=b.from_node_id) "
        f"SELECT COALESCE(name, '') AS nm, (link_id NOT IN (SELECT link_id FROM tw)) AS oneway, "
        f"ST_AsText(geom) FROM {g}.link WHERE geom IS NOT NULL").fetchall()
    con.close()
    rows = [r for r in rows if r[2] and r[2].startswith("LINESTRING")]
    return gpd.GeoDataFrame(
        {"name": [r[0] for r in rows], "oneway": [bool(r[1]) for r in rows]},
        geometry=[wkt.loads(r[2]) for r in rows], crs="EPSG:4326")


def _base_tiles(m):
    """Add selectable base layers (the OSM standard = osm-carto, plus dark / light / satellite)."""
    import folium

    folium.TileLayer("OpenStreetMap", name="OSM · osm-carto").add_to(m)              # the osm-carto base
    folium.TileLayer("CartoDB positron", name="Carto Light").add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Carto Dark").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite").add_to(m)


def _lane_layers(m, gdf, popup=False):
    """Add the per-use lane polygon layers to ``m`` (hover tooltip; click popup when ``popup``)."""
    import folium

    for use, color in _USE_COLOR.items():
        sub = gdf[gdf["use"] == use]
        if not len(sub):
            continue
        fields = ["use", "lane", "edge_id", "width"]
        aliases = ["use", "lane #", "edge_id", "width (m)"]
        folium.GeoJson(
            sub, name=f"lanes_{use} ({len(sub)})",
            style_function=lambda f, c=color: {"fillColor": c, "color": c, "weight": 0.4, "fillOpacity": 0.7},
            highlight_function=lambda f: {"weight": 2.5, "color": "#ffffff", "fillOpacity": 0.9},
            tooltip=folium.GeoJsonTooltip(fields=fields, aliases=aliases, sticky=True),
            popup=(folium.GeoJsonPopup(fields=fields, aliases=aliases) if popup else None),
        ).add_to(m)


def _route(m, route_geojson):
    import folium
    import geopandas as gpd

    rgdf = gpd.read_file(str(route_geojson))
    props = rgdf.drop(columns="geometry").iloc[0].to_dict() if len(rgdf) else {}
    tip = f"route · {props.get('lanes', '?')} lanes · cost {round(float(props.get('cost', 0) or 0))}"
    folium.GeoJson(rgdf[["geometry"]], name="route",
                   style_function=lambda f: {"color": _ROUTE_COLOR, "weight": 4, "opacity": 0.95},
                   tooltip=tip).add_to(m)


def _labels(m, gmns_db, mode, names=True, arrows=True):
    """Street-name labels + one-way arrows along the road centerlines (toggleable layers)."""
    import folium
    from folium.plugins import PolyLineTextPath

    roads = road_gdf(gmns_db, mode=mode)
    name_grp = folium.FeatureGroup(name="street names", show=names)
    arrow_grp = folium.FeatureGroup(name="one-way arrows", show=arrows)
    for nm, oneway, geom in zip(roads["name"], roads["oneway"], roads.geometry):
        latlon = [[y, x] for x, y in geom.coords]
        if names and nm:
            pl = folium.PolyLine(latlon, weight=0, opacity=0)
            pl.add_to(name_grp)
            PolyLineTextPath(pl, "  " + nm + "  ", repeat=True, offset=4, center=True,
                             attributes={"fill": "#3a3a3a", "font-size": "11", "font-weight": "500"}).add_to(name_grp)
        if arrows and oneway:
            pl = folium.PolyLine(latlon, weight=0, opacity=0)
            pl.add_to(arrow_grp)
            PolyLineTextPath(pl, " ▶ ", repeat=True, offset=3, center=True,
                             attributes={"fill": "#8a8a8a", "font-size": "13"}).add_to(arrow_grp)
    name_grp.add_to(m)
    arrow_grp.add_to(m)


def _map(gdf, zoom_start):
    import folium

    minx, miny, maxx, maxy = gdf.total_bounds
    m = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=zoom_start, tiles=None)
    _base_tiles(m)
    return m, (minx, miny, maxx, maxy)


def render_lane_map(gmns_db, out, mode="driving", route_geojson=None, zoom_start=14, serve=True):
    """Render a standalone lane-level map (lanes coloured by use + base-layer selector; optional route)."""
    import folium

    gdf = lane_gdf(gmns_db, mode=mode)
    m, (minx, miny, maxx, maxy) = _map(gdf, zoom_start)
    _lane_layers(m, gdf, popup=False)
    if route_geojson:
        _route(m, route_geojson)
    folium.LayerControl(collapsed=True).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    m.save(str(out))
    if serve:
        write_serve(out)
    return out


def render_lane_debug(gmns_db, out, mode="driving", route_geojson=None, zoom_start=15,
                      names=True, arrows=True, serve=True):
    """A **debug** lane map (QA): click a lane to see its ``use`` / lane # / ``edge_id`` / width (also on
    hover), toggle each use, switch **base layers** (osm-carto / dark / light / satellite), and show
    **street names** + **one-way arrows**. Optional route overlay. Standalone folium. Returns ``out``."""
    import folium

    gdf = lane_gdf(gmns_db, mode=mode)
    m, (minx, miny, maxx, maxy) = _map(gdf, zoom_start)
    if names or arrows:
        _labels(m, gmns_db, mode, names=names, arrows=arrows)
    _lane_layers(m, gdf, popup=True)
    if route_geojson:
        _route(m, route_geojson)
    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    m.save(str(out))
    if serve:
        write_serve(out)
    return out
