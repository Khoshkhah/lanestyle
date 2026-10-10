"""The docs' pictures (docs/img/*.jpg), from a lane page of Monaco (lane_page.py or docs/build_maps.py). Run by hand
when the look changes (needs playwright + chromium); fix a place in the editor first (its link: ?at=lon,lat,zoom):

    python docs/build_images.py docs/maps/monaco.html [NAME ...]      # a file, or a URL
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGE = sys.argv[1] if "://" in sys.argv[1] else Path(sys.argv[1]).resolve().as_uri()
ONLY = set(sys.argv[2:])
OUT = Path(__file__).parent / "img"
HIDE = ".maplibregl-control-container,.maplibregl-ctrl,.co-ctrl{display:none!important}"

# name: (lon, lat, zoom, (width, height), click the car lane nearest the middle)
SHOTS = {
    "hero": (7.43065, 43.74275, 18.6, (1200, 600), False),
    "gallery/albert_1er": (7.4218, 43.7350, 18.0, (900, 600), False),
    "gallery/lane_lines": (7.42652, 43.74163, 20.0, (900, 600), False),
    "gallery/roundabout": (7.41725, 43.73150, 19.1, (900, 600), False),
    "gallery/tunnel": (7.417431, 43.732942, 19.0, (900, 600), False),
    "gallery/bus_lane": (7.42512, 43.74110, 18.6, (900, 600), False),
    "gallery/click": (7.4196, 43.73616, 19.3, (900, 600), True),
}
# the boxes that float over the map (Roads, Tunnels) and the zoom label: not in a picture
UNCLUTTER = """() => {
  document.querySelectorAll('div').forEach(d => { const s = getComputedStyle(d);
    if ((s.position === 'absolute' || s.position === 'fixed') && d.querySelector('input[type=checkbox], select')) d.style.display = 'none'; });
  document.querySelectorAll('div,span').forEach(e => { if (/^z [0-9.]+$/.test((e.textContent || '').trim()) && !e.children.length) e.style.display = 'none'; }); }"""
NEAREST_LANE = """() => { const c = map.project(map.getCenter());
  const fs = map.queryRenderedFeatures({layers: ['roads-simple'], filter: ['to-boolean', ['get', '__rs_pick']]}); let best = null, bd = 1e9;
  for (const f of fs) { const g = f.geometry, cs = g.type === 'LineString' ? g.coordinates : g.coordinates.flat();
    const m = map.project(cs[Math.floor(cs.length / 2)]), d = Math.hypot(m.x - c.x, m.y - c.y); if (d < bd) { bd = d; best = [m.x, m.y]; } }
  return best; }"""

with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
    for name, (x, y, z, (w, h), click) in SHOTS.items():
        if ONLY and name not in ONLY and name.split("/")[-1] not in ONLY:
            continue
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1.5)
        pg.goto(PAGE)
        pg.wait_for_function("window.map && map.loaded()", timeout=180000)
        pg.add_style_tag(content=HIDE)
        pg.evaluate(UNCLUTTER)
        pg.evaluate("a => map.jumpTo({center: [a[0], a[1]], zoom: a[2], bearing: 0})", [x, y, z])
        pg.wait_for_timeout(1500)
        pg.wait_for_function("map.loaded() && map.areTilesLoaded()", timeout=300000)
        if click:
            at = pg.evaluate(NEAREST_LANE)
            pg.mouse.click(at[0], at[1])
        pg.wait_for_timeout(2500)
        (OUT / name).parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=85)
        print("wrote", OUT / f"{name}.jpg")
        pg.close()
    b.close()
