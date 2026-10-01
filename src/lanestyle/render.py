"""The engine: a lane table drawn with roadstyle, one line per lane at its width in metres.

    import lanestyle as ls
    lanes, turns = ls.from_gmns("monaco_gmns.duckdb", source_db="monaco.duckdb")
    ls.render_lanes(lanes, turns=turns).save("lanes.html")

Design: docs/design/lanestyle_on_roadstyle.md.
"""
import json
from pathlib import Path

from lanestyle.lines import lane_lines

_POPUP = ["name", "lane_type", "connects", "highway", "lane_id", "lane_num", "lanes", "use", "turn", "width_m", "tunnel", "bridge",
          "layer", "turns_in", "turns_out", "from_lane", "to_lane", "link_id", "reverse_link_id", "osm_id", "from_node_id",
          "to_node_id"]                       # the ones present and not null show
_MARKED = ("bus", "bike")          # uses painted over the palette; any other use keeps the road colour

# click a lane: it turns `clicked`, the lanes its turns lead into `turns_into`, U-turns `uturn`.
# roadstyle feature ids are indexes into its source, so lane_id -> id is built on the first click.
_CLICK_JS = """<script>
(function(){
  const T = __TURNS__, C = __COLORS__;
  let idx = null;
  const ids = ls => (ls || []).map(l => idx[l]).filter(i => i !== undefined);
  document.addEventListener("rs:select", e => {
    const d = e.detail || {};
    if (d.overlay || d.id == null) return;
    if (!idx) { idx = {}; const all = rsQuery(() => true), rows = rsGetProps(all);
                all.forEach((id, k) => { idx[rows[k].lane_id] = id; }); }
    const t = T[(d.properties || {}).lane_id] || [];
    rsColor([[[d.id], C.clicked], [ids(t[0]), C.turns_into], [ids(t[1]), C.uturn]]);
  });
  document.addEventListener("rs:deselect", () => rsColor(null));
})();
</script>
"""


# the lane lines: one MapLibre line layer per band and type, right after that band's fill, so a
# bridge covers the lines of the street under it; widths in metres (k = width_m / cos(lat)) from
# width_m_zoom, dashes in multiples of the line width (dash_m / width_m), exact at every zoom
_LINES_JS = """<script>
(function(){
  const D = __LINES__, S = __STYLES__, Z = __ZOOM__;
  // never thinner than one physical pixel of this screen (a sub-pixel line vanishes in some browsers
  // and at browser zooms under 100 %), true to scale above that; faded in over two zoom levels
  const MIN = __MIN_DEVICE_PX__ / (window.devicePixelRatio || 1);     // compact columns (_compact), rebuilt here
  const L = {type: "FeatureCollection", features: D.c.map((c, i) => ({type: "Feature",
    properties: {t: D.types[D.t[i]], b: D.bands[D.b[i]], k: D.k[i]},
    geometry: {type: Array.isArray(c[0][0]) ? "MultiLineString" : "LineString", coordinates: c}}))};
  // after the band's last fill layer: roadstyle (main, 2026-09-30) draws tunnel stretches at street
  // level (roads-tunnelgr-*, after the under-road pieces); older versions have only roads-tunnel-fill
  const AFTER = {tunnel: ["roads-tunnelgr-fill", "roads-tunnel-under-fill", "roads-tunnel-fill"],
                 low: ["roads-low-fill"], ground: ["roads-fill"], high: ["roads-high-fill"],
                 bridge: ["roads-bridge-fill"]};
  const px = z => 512 * Math.pow(2, z) / 40075016.686;
  function add(){
    if (map.getSource("lane-lines")) return;
    map.addSource("lane-lines", {type: "geojson", data: L});
    const ids = map.getStyle().layers.map(l => l.id);
    for (const b in AFTER) {
      const after = AFTER[b].find(id => ids.includes(id));
      if (!after) continue;
      const i = ids.indexOf(after);
      for (const t in S) {
        const s = S[t];
        if (!s) continue;
        const w = ["interpolate", ["exponential", 2], ["zoom"]];
        for (let z = Z; z <= 22; z++) w.push(z, ["max", ["*", ["get", "k"], px(z)], MIN]);
        const paint = {"line-color": s.color, "line-width": w,
                       "line-opacity": ["interpolate", ["linear"], ["zoom"], Z, 0.35, Z + 2, 1]};
        if (s.dash_m) paint["line-dasharray"] = s.dash_m.map(d => d / s.width_m);
        map.addLayer({id: "lane-lines-" + b + "-" + t, type: "line", source: "lane-lines", minzoom: Z,
                      filter: ["all", ["==", ["get", "t"], t], ["==", ["get", "b"], b]],
                      layout: {"line-cap": "butt", "line-join": "round"}, paint: paint}, ids[i + 1]);
      }
    }
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""


def _compact(fc):
    """The lines as columns, not GeoJSON features: a city's ~35k lines are half wrapping otherwise."""
    fs = fc["features"]
    types = sorted({f["properties"]["t"] for f in fs})
    bands = sorted({f["properties"]["b"] for f in fs})
    return {"types": types, "bands": bands,
            "t": [types.index(f["properties"]["t"]) for f in fs],
            "b": [bands.index(f["properties"]["b"]) for f in fs],
            "k": [f["properties"]["k"] for f in fs], "c": [f["geometry"]["coordinates"] for f in fs]}


# roadstyle's tunnel look is a faded fill over a dashed casing; with metre widths and no casing the
# dashes cover the whole lane and show through as blocks, so lanes get a plain casing under the fade
_ROADSTYLE = {"config": {"tunnel_gap_shade": 0, "tunnel_dash_shade": 0}}


def _break_twins(g):
    """roadstyle pairs two lines with swapped end points (to 6 decimals) as a two-way road's two
    directions and shifts them apart. Lanes are never such a pair (each has its own geometry), but the
    two halves of a one-way loop are: nudge one end of the later one by 2e-6 degrees (~0.2 m)."""
    # ponytail: geometry nudge; roadstyle's `twoway_col` (in progress on its main) replaces it
    from shapely.geometry import LineString

    key = lambda c: (round(c[0], 6), round(c[1], 6))
    seen, geoms = set(), list(g.geometry)
    for i, ln in enumerate(geoms):
        if ln is None or ln.geom_type != "LineString":
            continue
        cs = list(ln.coords)
        a, z = key(cs[0]), key(cs[-1])
        if (z, a) in seen:
            cs[-1] = (cs[-1][0] + 2e-6, cs[-1][1] + 2e-6)
            geoms[i] = LineString(cs)
            z = key(cs[-1])
        seen.add((a, z))
    return g.set_geometry(geoms, crs=g.crs)


# a lane's type label: the turns that leave it, in this order, as these words
_TYPE_ORDER = ["left", "uturn", "thru", "diverge", "merge", "right"]
_TYPE_WORD = {"left": "left", "uturn": "U-turn", "thru": "thru", "diverge": "fork", "merge": "merge",
              "right": "right"}

# the type label along each lane (lane_type), from zoom __ZOOM__, in roadstyle's street-name font
_LABELS_JS = """<script>
(function(){
  function add(){
    if (map.getLayer("lane-type-labels")) return;
    const font = map.getLayer("roads-labels") ? map.getLayoutProperty("roads-labels", "text-font") : null;
    map.addLayer({id: "lane-type-labels", type: "symbol", source: "roads", minzoom: __ZOOM__,
      filter: ["!", ["to-boolean", ["get", "connector"]]],     // lanes only; a connector says it in its popup
      layout: Object.assign({"symbol-placement": "line", "text-field": ["get", "lane_type"], "text-size": 11,
                             "symbol-spacing": 220, "text-keep-upright": true}, font ? {"text-font": font} : {}),
      paint: {"text-color": "#1b1b1b", "text-halo-color": "#ffffff", "text-halo-width": 1.5}});
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""


# round lane ends make joins smooth (a lane meeting the next at an angle), so they stay - except in
# tunnels: tunnel lanes are see-through, and where lanes and connectors overlap their round ends
# show as darker discs, so the tunnel layers end flat (connectors join the lanes there)
_FLAT_ENDS_JS = """<script>
(function(){
  function flat(){
    for (const l of map.getStyle().layers)
      if (l.type === "line" && l.source === "roads" && l.id.startsWith("roads-tunnel")
          && map.getLayoutProperty(l.id, "line-cap") === "round")
        map.setLayoutProperty(l.id, "line-cap", "butt");
  }
  if (map.isStyleLoaded()) flat(); else map.once("load", flat);
})();
</script>
"""


# bus / bike lanes are coloured with roadstyle's "colour by" (Road class + Lane use, the latter on),
# but its dropdown and legend box are hidden: the colours get rows in the Roads filter box instead,
# under the road classes, before Bridges / Tunnels
_USE_ROWS_JS = """<style>.co-ctrl,.co-lg{display:none!important}</style>
<script>
(function(){
  const ROWS = __ROWS__;
  function add(){
    const body = document.querySelector(".flt-ctrl .flt-body");
    if (!body) return setTimeout(add, 200);
    if (body.querySelector(".ls-use")) return;
    const before = body.querySelector(".flt-grade");
    ROWS.forEach(([label, color], i) => {
      const lab = document.createElement("label"); lab.className = "ls-use";
      if (i === 0) lab.style.cssText = "margin-top:4px;padding-top:4px;border-top:1px solid #ddd";
      const pad = document.createElement("input"); pad.type = "checkbox"; pad.style.visibility = "hidden";
      const sw = document.createElement("span"); sw.className = "flt-sw"; sw.style.background = color;
      lab.appendChild(pad); lab.appendChild(sw); lab.appendChild(document.createTextNode(" " + label));
      body.insertBefore(lab, before);
    });
  }
  add();
})();
</script>
"""


def _lane_types(g, turns):
    """Each lane's type label: the turns that leave it (``left + thru``, ``U-turn``, ``fork``, ``merge``)
    or ``end`` where none does; a bus or bike lane says so first (``bus · thru``)."""
    out = {}
    types = turns["type"] if "type" in turns else ["turn"] * len(turns)
    for a, t in zip(turns["from_lane"].astype(str), types):
        out.setdefault(a, set()).add(t)

    def label(lane, use):
        ts = out.get(lane, set())
        words = " + ".join(_TYPE_WORD.get(t, t) for t in _TYPE_ORDER + sorted(ts - set(_TYPE_ORDER)) if t in ts)
        return (words or "end") if use == "auto" else f"{use} · {words or 'end'}"
    return [label(lane, use) for lane, use in zip(g["lane_id"], g["use"])]


def _merge(a, b):
    """``a`` updated by ``b``, nested dicts merged (state only what changes)."""
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def lane_settings(settings=None):
    """lanestyle's settings: ``data/lanestyle.json``, then a ``lanestyle.json`` in the current folder,
    then ``settings["lanes"]``, each overriding only what it states (the roadstyle.json way)."""
    s = json.loads((Path(__file__).parent / "data" / "lanestyle.json").read_text())["lanes"]
    local = Path("lanestyle.json")
    if local.is_file():
        s = _merge(s, json.loads(local.read_text()).get("lanes"))
    return _merge(s, (settings or {}).get("lanes"))


def render_lanes(lanes, turns=None, palette="mono", settings=None, **kwargs):
    """Draw a lane table (see :func:`lanestyle.from_gmns` for the columns) as one roadstyle map and
    return roadstyle's ``WebMap`` (``.save(path)``, ``.html``).

    Each lane is one line on its own geometry, exactly ``width_m`` metres wide from
    ``width_m_zoom`` on (``default_width_m`` where null). Bus and bike lanes are painted over the
    palette (a "Lane use" colouring; the legend lists only uses present). ``turns`` (``from_lane``,
    ``to_lane``, optional ``type``) makes a lane clickable: it turns red and the lanes it leads into
    green, U-turns purple. Lane lines (dividers, centre and edge lines, styled per type under
    ``lines``) come from ``link_id`` / ``lane_num`` (+ ``reverse_link_id``, node ids; see
    :func:`lanestyle.lines.lane_lines`). ``settings``: roadstyle settings, plus a ``"lanes"`` key
    for lanestyle's own (``data/lanestyle.json``). Other keywords go to ``roadstyle.render_edges``."""
    import roadstyle as rs

    s = lane_settings(settings)
    g = lanes.copy()
    g["width_m"] = g["width_m"].fillna(s["default_width_m"]) if "width_m" in g else s["default_width_m"]
    g["use"] = g["use"].fillna("auto") if "use" in g else "auto"
    present = {u: s["colors"][u] for u in _MARKED if u in set(g["use"])}
    opts = {}
    if present:
        opts = dict(color_options={"Road class": {}, "Lane use": {"color_by": "use", "colors": present}},
                    color_active="Lane use")
    conn = g["connector"].fillna(False).astype(bool) if "connector" in g else None
    if conn is not None:                                 # arrows on lanes, not on connectors
        g["oneway"] = ~conn
    if turns is not None and len(turns):                 # what each lane is for (label + popup)
        g["lane_type"] = _lane_types(g, turns)
        if conn is not None and conn.any():              # a connector says what it is, in words
            kind = dict(zip(zip(turns["from_lane"].astype(str), turns["to_lane"].astype(str)),
                            turns["type"] if "type" in turns else ["turn"] * len(turns)))
            road = dict(zip(g["lane_id"], g.get("name", [None] * len(g))))
            num = dict(zip(g["lane_id"], g.get("lane_num", [None] * len(g))))
            first = {}                                   # a road's name sits on its lane 1 only
            for lid, nm in road.items():
                if isinstance(nm, str):
                    first[str(lid).rsplit("_", 1)[0]] = nm

            def says(a, b):
                def lane(x):
                    n = num.get(x)
                    nm = first.get(str(x).rsplit("_", 1)[0]) or "(unnamed road)"
                    return f"lane {int(n)} of {nm}" if n == n and n is not None else str(x)
                return f"{lane(a)} → {lane(b)}"
            g.loc[conn, "lane_type"] = ["connector · " + _TYPE_WORD.get(kind.get((a, b)), kind.get((a, b)) or "turn")
                                         for a, b in zip(g.loc[conn, "from_lane"], g.loc[conn, "to_lane"])]
            g.loc[conn, "connects"] = [says(a, b) for a, b in zip(g.loc[conn, "from_lane"], g.loc[conn, "to_lane"])]
    if turns is not None and len(turns):                 # how many lanes lead in / out, for the popup
        g["turns_in"] = g["lane_id"].map(turns.groupby(turns["to_lane"].astype(str)).size()).fillna(0).astype(int)
        g["turns_out"] = g["lane_id"].map(turns.groupby(turns["from_lane"].astype(str)).size()).fillna(0).astype(int)
    lines = lane_lines(g, s)
    m = rs.render_edges(
        _break_twins(g), palette=palette,
        width_m_col="width_m", width_m_zoom=s["width_m_zoom"], casing_m=s["casing_m"],
        road_popup=[c for c in _POPUP if c in g.columns],
        **{"select_color": s["colors"]["clicked"], **kwargs},   # roadstyle's own selection glow
        settings=_merge(_ROADSTYLE, {k: v for k, v in (settings or {}).items() if k != "lanes"}),
        **opts)
    js = ""
    if present:                                          # bus / bike colours as rows in the Roads box
        js += _USE_ROWS_JS.replace("__ROWS__", json.dumps([[f"{u} lanes", c] for u, c in present.items()]))
    if lines:
        js += (_LINES_JS.replace("__LINES__", json.dumps(_compact(lines), separators=(",", ":")))
               .replace("__STYLES__", json.dumps(s["lines"])).replace("__ZOOM__", json.dumps(s["width_m_zoom"]))
               .replace("__MIN_DEVICE_PX__", json.dumps(s.get("line_min_device_px", 1))))
    if conn is not None and conn.any():
        js += _FLAT_ENDS_JS
    if turns is not None and len(turns):
        via = {}                                         # (from lane, to lane) -> its connector
        if conn is not None and conn.any():
            via = dict(zip(zip(g.loc[conn, "from_lane"], g.loc[conn, "to_lane"]), g.loc[conn, "lane_id"]))
        js += _click_js(turns, s, via)
        if s.get("type_label_zoom") is not None:
            js += _LABELS_JS.replace("__ZOOM__", json.dumps(s["type_label_zoom"]))
    if not js:
        return m
    html = m.html
    i = html.rfind("</body>")
    return type(m)(html[:i] + js + html[i:])


def _click_js(turns, s, via=None):
    nxt, via = {}, via or {}
    types = turns["type"] if "type" in turns else [None] * len(turns)
    for a, b, t in zip(turns["from_lane"].astype(str), turns["to_lane"].astype(str), types):
        nxt.setdefault(a, [[], []])[t == "uturn"].append(b)
        if (a, b) in via:                                # and the connector into it
            nxt[a][t == "uturn"].append(via[a, b])
    return (_CLICK_JS.replace("__TURNS__", json.dumps(nxt, separators=(",", ":")))
            .replace("__COLORS__", json.dumps({k: s["colors"][k] for k in ("clicked", "turns_into", "uturn")})))


_SERVE_PY = '''#!/usr/bin/env python3
"""Static server for this lanestyle render.
   python serve.py [port]   ->  http://localhost:8080/__INDEX__"""
import sys, http.server, socketserver
from functools import partial
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html") and self.path != "/__INDEX__":   # the root URL opens the map
            self.send_response(302)
            self.send_header("Location", "/__INDEX__")
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")   # a rebuilt map shows on a plain reload
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
