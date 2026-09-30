"""The engine: a lane table drawn with roadstyle, one line per lane at its width in metres.

    import lanestyle as ls
    lanes, turns = ls.from_gmns("monaco_gmns.duckdb", source_db="monaco.duckdb")
    ls.render_lanes(lanes, turns=turns).save("lanes.html")

Design: docs/design/lanestyle_on_roadstyle.md.
"""
import json
from pathlib import Path

_POPUP = ["name", "lane_id", "lane_num", "turn", "use", "width_m", "link_id"]
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
    green, U-turns purple. ``settings``: roadstyle settings, plus a ``"lanes"`` key for
    lanestyle's own (``data/lanestyle.json``). Other keywords go to ``roadstyle.render_edges``."""
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
    m = rs.render_edges(
        g, palette=palette, width_m_col="width_m", width_m_zoom=s["width_m_zoom"], casing_m=s["casing_m"],
        road_popup=[c for c in _POPUP if c in g.columns],
        **{"select_color": s["colors"]["clicked"], **kwargs},   # roadstyle's own selection glow
        settings={k: v for k, v in (settings or {}).items() if k != "lanes"} or None,
        **opts)
    if turns is None or not len(turns):
        return m
    nxt = {}
    types = turns["type"] if "type" in turns else [None] * len(turns)
    for a, b, t in zip(turns["from_lane"].astype(str), turns["to_lane"].astype(str), types):
        nxt.setdefault(a, [[], []])[t == "uturn"].append(b)
    js = (_CLICK_JS.replace("__TURNS__", json.dumps(nxt, separators=(",", ":")))
          .replace("__COLORS__", json.dumps({k: s["colors"][k] for k in ("clicked", "turns_into", "uturn")})))
    html = m.html
    i = html.rfind("</body>")
    return type(m)(html[:i] + js + html[i:])


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
