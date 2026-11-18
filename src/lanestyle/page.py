"""The lane page: the level editor's drawing without its panel. roadstyle draws every road from the level area's roads and levels;
lanestyle adds the road's own items (lanes, lane lines, arrows, BUS and bike marks). The Rust engine makes the page (lanestyle::page).

    import lanestyle as ls
    ls.lane_page("monaco.levels", "monaco_gmns.duckdb", "monaco.duckdb").save("lanes.html")
"""
import json

from lanestyle._rust_call import rust


class LanePage:
    """The page's HTML (MapLibre in it): ``.html``, ``.save(path)``, and the page in a notebook."""

    def __init__(self, html):
        self.html = html

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.html)
        return path

    def _repr_html_(self):
        import html as h
        return f'<iframe srcdoc="{h.escape(self.html)}" style="width:100%;height:600px;border:0"></iframe>'


def lane_page(area, gmns, source_db, connectors=False, **kw):
    """The lanes of ``gmns`` (duckOSM's GMNS file of ``source_db``) on the roads of the level ``area`` (made by ``duckosm levels``,
    with your edits). ``connectors``: also the lane connectors through the junctions, unseen. ``kw`` go to roadstyle's page (e.g.
    ``name=``; ``basemap=`` / ``filter_control=True`` / ``tunnel_control=True``: by default the page is blank, just the lanes)."""
    html, notes = rust().lane_page(str(area), str(gmns), str(source_db), bool(connectors), json.dumps(kw))
    for n in notes:
        print(n, flush=True)
    return LanePage(html)
