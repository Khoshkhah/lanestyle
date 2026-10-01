"""The docs' pictures (docs/img/*.jpg), from a real lanestyle page of Monaco. Run by hand when the look
changes (needs playwright + chromium):

    python docs/build_images.py renders/lanes/monaco.html [NAME ...]      # a file, or a URL

The live map on the site is built in CI instead (docs/build_maps.py).
"""
import io
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

PAGE = sys.argv[1] if "://" in sys.argv[1] else Path(sys.argv[1]).resolve().as_uri()
ONLY = set(sys.argv[2:])
OUT = Path(__file__).parent / "img"
HIDE = (".rs-zoom,.maplibregl-ctrl-top-left,.maplibregl-ctrl-top-right,.rs-tl,.flt-ctrl,.ov-ctrl,.co-ctrl,.bm-ctrl,"
        ".maplibregl-ctrl-bottom-left,.maplibregl-ctrl-bottom-right{display:none!important}")

# name: (lon, lat, zoom, (width, height), hide the controls, a lane_id to click)
SHOTS = {
    "hero": (7.42600, 43.74140, 18.3, (1600, 900), True, None),
    "gallery/overview": (7.4215, 43.7362, 15.2, (900, 600), True, None),
    "gallery/lane_lines": (7.42652, 43.74163, 20.0, (900, 600), True, None),
    "gallery/roundabout": (7.41725, 43.73150, 19.1, (900, 600), True, None),
    "gallery/tunnel": (7.417431, 43.732942, 19.0, (900, 600), True, None),
    "gallery/bus_lane": (7.42512, 43.74110, 18.6, (900, 600), False, None),
    "gallery/click": (7.4196, 43.73616, 19.3, (900, 600), True, "auto"),
}

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
    pg.goto(PAGE)
    pg.wait_for_function("window.map && map.loaded() && map.isStyleLoaded()", timeout=120000)
    for name, (x, y, z, (w, h), hide, click) in SHOTS.items():
        if ONLY and name not in ONLY and name.split("/")[-1] not in ONLY:
            continue
        pg.set_viewport_size({"width": w, "height": h})
        pg.evaluate("css => { let s = document.getElementById('shot-css'); if (!s) { s = document.createElement('style');"
                    " s.id = 'shot-css'; document.head.appendChild(s); } s.textContent = css; }", HIDE if hide else "")
        pg.evaluate("a => map.jumpTo({center: [a[0], a[1]], zoom: a[2]})", [x, y, z])
        if click:        # the lane with most turns out, near the centre of the view
            pg.evaluate("""a => { const c = map.getCenter(); let best = null, n = -1;
              rsQuery(p => p.turns_out > 1 && !p.connector).forEach(id => {
                const g = _feats()[id].geometry.coordinates, m = g[Math.floor(g.length / 2)];
                const d = Math.hypot((m[0] - c.lng) * 0.72, m[1] - c.lat), p = _feats()[id].properties;
                const s = p.turns_out - d * 2000; if (s > n) { n = s; best = id; } });
              rsSelect(best); }""", [])
        pg.wait_for_timeout(4000)
        (OUT / name).parent.mkdir(parents=True, exist_ok=True)
        png = pg.screenshot(animations="disabled", caret="hide")
        Image.open(io.BytesIO(png)).convert("RGB").save(OUT / f"{name}.jpg", quality=85, optimize=True)
        print("wrote", OUT / f"{name}.jpg")
    b.close()
