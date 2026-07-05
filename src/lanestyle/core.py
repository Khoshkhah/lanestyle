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
        f"SELECT lane_id, allowed_uses, lane_num, link_id, COALESCE(width, {_LANE_W}) AS w, "
        f"ST_AsText(ST_Transform(ST_Buffer("
        f"  ST_Transform(geom, 'EPSG:4326', 'EPSG:3006', always_xy := true), COALESCE(width, {_LANE_W})/2.0, 2), "
        f"  'EPSG:3006', 'EPSG:4326', always_xy := true)) "
        f"FROM {g}.lane WHERE geom IS NOT NULL").fetchall()
    con.close()
    rows = [r for r in rows if r[5] and r[5].startswith(("POLYGON", "MULTIPOLYGON"))]
    return gpd.GeoDataFrame(
        {"lane_id": [str(r[0]) for r in rows], "use": [r[1] for r in rows], "lane": [r[2] for r in rows],
         "edge_id": [str(r[3]) for r in rows], "width": [round(float(r[4]), 2) for r in rows]},
        geometry=[wkt.loads(r[5]) for r in rows], crs="EPSG:4326")


def road_gdf(gmns_db, mode="driving"):
    """Roads (``gmns_<mode>.link`` centerlines) with ``name`` + ``oneway`` — for street-name labels and
    one-way arrows. ``oneway`` = the link has no reverse pair (a two-way road is two links)."""
    import duckdb
    import geopandas as gpd
    import shapely.wkt as wkt

    g = f"gmns_{mode}"
    con = duckdb.connect(str(gmns_db), read_only=True)
    con.execute("INSTALL spatial; LOAD spatial;")
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE schema_name=? AND table_name='link'",
                   [g]).fetchone()[0] == 0:
        con.close()
        return gpd.GeoDataFrame({"name": [], "oneway": []}, geometry=[], crs="EPSG:4326")
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


def lane_adjacency(gmns_db, mode="driving", uturns=False):
    """Lane connectivity per the **GMNS** movement model. ``{lane_id: [outgoing lane_ids]}`` where each
    lane can go next: **turns** (movement ``type`` left/right/thru — inbound lane → outbound lane, over
    the GMNS ``start_ib_lane``/``end_ib_lane`` range) + **lane-changes** (adjacent lanes on the link).
    **U-turns** (``type='uturn'``, a valid GMNS movement type) are kept separate: with ``uturns=True``
    returns ``(outgoing, uturn_outgoing)`` — two maps — so a viewer can colour them distinctly. Empty
    if the db has no ``movement`` table. (GMNS ``start_ob_lane``/``end_ob_lane`` are unset in duckOSM →
    per GMNS "blank = single outbound lane"; we connect to the ob-link lanes.)"""
    import duckdb
    from collections import defaultdict

    g = f"gmns_{mode}"
    con = duckdb.connect(str(gmns_db), read_only=True)
    con.execute("INSTALL spatial; LOAD spatial;")
    adj, uadj = defaultdict(set), defaultdict(set)
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE schema_name=? AND table_name='movement'",
                   [g]).fetchone()[0]:
        for a, b, t in con.execute(
                f"SELECT il.lane_id, ol.lane_id, m.type FROM {g}.movement m "
                f"JOIN {g}.lane il ON il.link_id = m.ib_link_id "
                f"  AND (m.start_ib_lane IS NULL OR il.lane_num BETWEEN m.start_ib_lane AND m.end_ib_lane) "
                f"JOIN {g}.lane ol ON ol.link_id = m.ob_link_id "
                f"  AND (m.start_ob_lane IS NULL OR ol.lane_num BETWEEN m.start_ob_lane AND m.end_ob_lane) "
                f"WHERE m.ib_link_id IS NOT NULL AND m.ob_link_id IS NOT NULL").fetchall():
            (uadj if t == "uturn" else adj)[str(a)].add(str(b))
    for a, b in con.execute(
            f"SELECT a.lane_id, b.lane_id FROM {g}.lane a JOIN {g}.lane b "
            f"ON a.link_id = b.link_id AND abs(a.lane_num - b.lane_num) = 1").fetchall():
        adj[str(a)].add(str(b))
    con.close()
    out = {k: sorted(v) for k, v in adj.items()}
    return (out, {k: sorted(v) for k, v in uadj.items()}) if uturns else out


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


def _folium_map(gmns_db, out, mode="driving", route_geojson=None, zoom_start=14, serve=True):
    """folium backend for the lane map (crisp at neighbourhood scale; heavy for a whole city)."""
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


def _folium_debug(gmns_db, out, mode="driving", route_geojson=None, zoom_start=15,
                  names=True, arrows=True, serve=True):
    """folium backend for the debug lane map (neighbourhood scale)."""
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


# ---------------------------------------------------------------------------------------------------
# WebGL backend (deck.gl + maplibre, self-contained via CDN) — scales to a whole city, small HTML.
# ---------------------------------------------------------------------------------------------------

def _fc(gdf, cols):
    """gdf -> compact GeoJSON dict with coords rounded to 6 dp (~0.1 m) so the embedded JSON stays small."""
    import shapely.geometry as sg

    def r(c):
        return [r(x) for x in c] if c and isinstance(c[0], (list, tuple)) else [round(c[0], 6), round(c[1], 6)]

    feats = []
    for geom, *vals in zip(gdf.geometry, *[gdf[c] for c in cols]):
        if geom is None or geom.is_empty:
            continue
        gm = sg.mapping(geom)
        gm["coordinates"] = r(gm["coordinates"])
        feats.append({"type": "Feature", "geometry": gm, "properties": dict(zip(cols, vals))})
    return {"type": "FeatureCollection", "features": feats}


def _label_points(gmns_db, mode):
    """(name points, arrow points) as GeoJSON — road-name at each named road's midpoint (angled to the
    road), one-way arrows sampled along one-way roads (angled to travel direction)."""
    import math

    roads = road_gdf(gmns_db, mode=mode)
    names, arrows = [], []
    for nm, oneway, geom in zip(roads["name"], roads["oneway"], roads.geometry):
        cs = list(geom.coords)
        if len(cs) < 2:
            continue

        def ang(a, b):
            lat = math.radians((a[1] + b[1]) / 2)
            return round(math.degrees(math.atan2(b[1] - a[1], (b[0] - a[0]) * math.cos(lat))), 1)
        length_m = geom.length * 111320
        if nm and length_m > 40:                          # skip tiny link segments — declutter names
            i = len(cs) // 2
            a, b = cs[i - 1], cs[i]
            names.append({"type": "Feature", "properties": {"name": nm, "ang": ang(a, b)},
                          "geometry": {"type": "Point",
                                       "coordinates": [round((a[0] + b[0]) / 2, 6), round((a[1] + b[1]) / 2, 6)]}})
        if oneway:
            step = max(1, (len(cs) - 1) // 2)
            for i in range(0, len(cs) - 1, step):
                a, b = cs[i], cs[i + 1]
                arrows.append({"type": "Feature", "properties": {"ang": ang(a, b)},
                               "geometry": {"type": "Point",
                                            "coordinates": [round((a[0] + b[0]) / 2, 6), round((a[1] + b[1]) / 2, 6)]}})
    return ({"type": "FeatureCollection", "features": names},
            {"type": "FeatureCollection", "features": arrows})


def render_lane_webgl(gmns_db, out, mode="driving", route_geojson=None, debug=True,
                      names=True, arrows=True, serve=True):
    """WebGL (deck.gl + maplibre) lane viewer — scales to a whole city in a small, fast, self-contained
    HTML. Lanes coloured by use (click a lane for its use / lane # / edge_id / width), a base-layer
    selector (osm-carto / light / dark / satellite), per-use toggles, street names, one-way arrows, and
    an optional route. Standalone (CDN deck.gl/maplibre; no mapstyle). Returns ``out``."""
    import json
    from pathlib import Path

    gdf = lane_gdf(gmns_db, mode=mode)
    minx, miny, maxx, maxy = gdf.total_bounds
    data = {"center": [round((minx + maxx) / 2, 6), round((miny + maxy) / 2, 6)], "zoom": 14,
            "lanes": _fc(gdf, ["lane_id", "use", "lane", "edge_id", "width"])}
    if debug:
        data["adj"], data["uturn"] = lane_adjacency(gmns_db, mode, uturns=True)   # outgoing + U-turn (GMNS)
        if names or arrows:
            nfc, afc = _label_points(gmns_db, mode)
            data["names"], data["arrows"] = nfc, afc
    if route_geojson:
        import geopandas as gpd
        data["route"] = json.loads(gpd.read_file(str(route_geojson))[["geometry"]].to_json())
    html = (_WEBGL_TEMPLATE
            .replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
            .replace("__DEBUG__", "true" if debug else "false")
            .replace("__NAMES__", "true" if (debug and names) else "false")
            .replace("__ARROWS__", "true" if (debug and arrows) else "false"))
    Path(out).write_text(html, encoding="utf-8")
    if serve:
        write_serve(out)
    return out


def render_lane_map(gmns_db, out, mode="driving", route_geojson=None, backend="webgl", serve=True):
    """Lane-level map. ``backend="webgl"`` (default, deck.gl — scales to a city) or ``"folium"``."""
    if backend == "folium":
        return _folium_map(gmns_db, out, mode=mode, route_geojson=route_geojson, serve=serve)
    return render_lane_webgl(gmns_db, out, mode=mode, route_geojson=route_geojson, debug=False, serve=serve)


def render_lane_debug(gmns_db, out, mode="driving", route_geojson=None, backend="webgl",
                      names=True, arrows=True, serve=True):
    """Debug lane map (click-inspect + base selector + names + arrows). ``backend="webgl"`` (default) or
    ``"folium"``."""
    if backend == "folium":
        return _folium_debug(gmns_db, out, mode=mode, route_geojson=route_geojson, names=names,
                             arrows=arrows, serve=serve)
    return render_lane_webgl(gmns_db, out, mode=mode, route_geojson=route_geojson, debug=True,
                             names=names, arrows=arrows, serve=serve)


_WEBGL_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lanestyle · lane map</title>
<link href="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css" rel="stylesheet"/>
<script src="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9/dist.min.js"></script>
<style>
html,body,#map{margin:0;height:100%;width:100%}
#panel{position:absolute;top:10px;right:10px;background:rgba(18,22,28,.92);color:#e6edf3;
  font:12px/1.45 system-ui,sans-serif;border-radius:10px;padding:10px 12px;max-width:250px;z-index:2;
  box-shadow:0 6px 20px rgba(0,0,0,.4)}
#panel h3{margin:0 0 6px;font-size:13px;font-weight:600}
#bases{margin-bottom:7px}#bases button{margin:1px 2px 1px 0;padding:2px 7px;border:1px solid #3a4656;
  background:#222a35;color:#bcd;border-radius:6px;cursor:pointer;font:11px system-ui}
#bases button.on{background:#2f7fd6;color:#fff;border-color:#2f7fd6}
#toggles label{display:block;margin:2px 0;cursor:pointer}
.sw{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:-1px;margin-right:5px}
#info{margin-top:8px;border-top:1px solid #33404f;padding-top:7px;display:none}
#info b{color:#7fd0ff}
</style></head><body>
<div id="map"></div>
<div id="panel"><h3>lanestyle</h3><div id="bases"></div><div id="toggles"></div><div id="info"></div></div>
<script>
const D=/*__DATA__*/null, DEBUG=__DEBUG__;
const USE={auto:[143,162,180],bus:[232,148,74],bike:[90,176,230]};
const SEL=[255,64,64], OUT=[40,200,255], UT=[190,110,240];   // selected red · outgoing cyan · U-turn purple
let selLane=null, outSet=new Set(), utSet=new Set();
const BASES={
 "osm-carto":{t:["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"],a:"© OpenStreetMap"},
 "light":{t:["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],a:"© CARTO"},
 "dark":{t:["https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],a:"© CARTO"},
 "satellite":{t:["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],a:"© Esri"}};
let curBase="osm-carto";
const bid=n=>"bs_"+n.replace(/[^a-z]/g,"");
function style(){const sources={},layers=[];for(const n in BASES){const b=BASES[n];
  sources[bid(n)]={type:"raster",tiles:b.t,tileSize:256,attribution:b.a};
  layers.push({id:bid(n),type:"raster",source:bid(n),layout:{visibility:n===curBase?"visible":"none"}});}
  return{version:8,sources,layers};}
const map=new maplibregl.Map({container:"map",style:style(),center:D.center,zoom:D.zoom});
const S={lanes_auto:true,lanes_bus:true,lanes_bike:true,names:__NAMES__,arrows:__ARROWS__,route:true};
const laneFeats={};for(const u in USE)laneFeats[u]={type:"FeatureCollection",
  features:(D.lanes.features||[]).filter(f=>f.properties.use===u)};
function layers(){const z=map.getZoom(),L=[];
  for(const u in USE){if(!S["lanes_"+u]||!laneFeats[u].features.length)continue;
    L.push(new deck.GeoJsonLayer({id:"lanes_"+u,data:laneFeats[u],filled:true,stroked:true,
      getFillColor:f=>{const id=f.properties.lane_id;
        return id===selLane?SEL:(utSet.has(id)?UT:(outSet.has(id)?OUT:USE[u]));},
      updateTriggers:{getFillColor:[selLane]},
      getLineColor:[12,14,18,170],lineWidthUnits:"pixels",getLineWidth:0.4,
      lineWidthMinPixels:0.3,pickable:true,autoHighlight:true,highlightColor:[255,255,255,120]}));}
  if(D.route&&S.route)L.push(new deck.GeoJsonLayer({id:"route",data:D.route,stroked:true,filled:false,
    getLineColor:[255,212,0],lineWidthUnits:"pixels",getLineWidth:4,lineWidthMinPixels:2}));
  if(DEBUG&&S.arrows&&D.arrows&&z>=15)L.push(new deck.TextLayer({id:"arrows",data:D.arrows.features,
    getPosition:f=>f.geometry.coordinates,getText:()=>"▶",getAngle:f=>f.properties.ang,
    getSize:15,getColor:[130,130,130],characterSet:"auto",billboard:false}));
  if(DEBUG&&S.names&&D.names&&z>=15)L.push(new deck.TextLayer({id:"names",data:D.names.features,
    getPosition:f=>f.geometry.coordinates,getText:f=>f.properties.name,getAngle:f=>f.properties.ang,
    getSize:12,getColor:[35,35,40],characterSet:"auto",billboard:false,fontWeight:600,
    background:true,getBackgroundColor:[255,255,255,190],backgroundPadding:[2,1]}));
  return L;}
const overlay=new deck.MapboxOverlay({interleaved:false,layers:[],
  onClick:info=>{const o=info&&info.object;
    if(o&&o.properties&&o.properties.lane_id!=null){selLane=o.properties.lane_id;
      outSet=new Set((D.adj&&D.adj[selLane])||[]);utSet=new Set((D.uturn&&D.uturn[selLane])||[]);}
    else{selLane=null;outSet=new Set();utSet=new Set();}
    refresh();showInfo(o,outSet.size,utSet.size);}});
map.addControl(overlay);
function refresh(){overlay.setProps({layers:layers()});}
map.on("load",refresh);map.on("zoom",refresh);
const $=i=>document.getElementById(i);
const bd=$("bases");
for(const n in BASES){const b=document.createElement("button");b.textContent=n;
  if(n===curBase)b.className="on";
  b.onclick=()=>{curBase=n;for(const m in BASES)map.setLayoutProperty(bid(m),"visibility",m===n?"visible":"none");
    [...bd.children].forEach(c=>c.className=c.textContent===n?"on":"");};bd.appendChild(b);}
const td=$("toggles"),rows=[["lanes_auto","auto",USE.auto],["lanes_bus","bus",USE.bus],
  ["lanes_bike","bike",USE.bike]];
if(DEBUG){rows.push(["names","street names"],["arrows","one-way arrows"]);}
if(D.route)rows.push(["route","route"]);
for(const[k,lab,col]of rows){const l=document.createElement("label");
  l.innerHTML=(col?`<span class="sw" style="background:rgb(${col.join(",")})"></span>`:"")+
    `<input type="checkbox" ${S[k]?"checked":""}> ${lab}`;
  l.querySelector("input").onchange=e=>{S[k]=e.target.checked;refresh();};td.appendChild(l);}
function showInfo(o,nout,nut){const p=$("info");if(!o){p.style.display="none";return;}const t=o.properties;
  p.style.display="block";p.innerHTML=`<b>lane</b><br>use: ${t.use}<br>lane #: ${t.lane}`+
    `<br>edge_id: ${t.edge_id}<br>width: ${t.width} m`+
    (nout!=null?`<br><span style="color:rgb(40,200,255)">▶ ${nout} outgoing</span>`+
      (nut?` · <span style="color:rgb(190,110,240)">${nut} U-turn</span>`:""):"");}
if(DEBUG){const h=document.createElement("div");h.style.cssText="margin-top:7px;font-size:11px;color:#9fb1c0";
  h.innerHTML=`click a lane → <span style="color:rgb(255,64,64)">■</span> selected · `+
    `<span style="color:rgb(40,200,255)">■</span> outgoing · <span style="color:rgb(190,110,240)">■</span> U-turn`;
  $("panel").appendChild(h);}
</script></body></html>
"""
