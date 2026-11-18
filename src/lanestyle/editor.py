"""The lanes in roadstyle's level editor: each road one line at its full width, with the bus and bike lanes, lane lines and marks as
the road's items (the Rust engine makes them, lanestyle::editor).

    LANESTYLE_GMNS=monaco_gmns.duckdb LANESTYLE_SOURCE_DB=monaco.duckdb \\
        roadstyle-levels edit AREA --items lanestyle.editor:lane_items
"""
import json
import os

from lanestyle._rust_call import rust


def lane_items(roads, gmns=None, source_db=None, connectors=None):
    """The editor's hook: sets each road's ``width_m`` and line on ``roads`` (the editor's table: ``edge``, ``road``, ``highway``,
    ``modes``, ``edge_ref``) and gives ``([], kw)``, the render keywords with the road's own ``items``. The files: given, else
    ``LANESTYLE_GMNS`` and ``LANESTYLE_SOURCE_DB``; ``connectors`` (else ``LANESTYLE_CONNECTORS=1``): the lane connectors too, unseen."""
    from shapely import wkb

    gmns, src = gmns or os.environ.get("LANESTYLE_GMNS"), source_db or os.environ.get("LANESTYLE_SOURCE_DB")
    if not gmns:
        raise ValueError("lanestyle.editor.lane_items: give gmns (or set LANESTYLE_GMNS) to the GMNS .duckdb, and source_db (LANESTYLE_SOURCE_DB) to its duckOSM file")
    on = connectors if connectors is not None else os.environ.get("LANESTYLE_CONNECTORS") == "1"
    nan = lambda v: v is None or v != v          # noqa: E731
    cols = {c: [None if nan(v) else str(v) for v in roads[c]] for c in ("edge", "road", "edge_ref", "highway", "modes") if c in roads}
    kw, width, lines, notes = rust().lane_items(json.dumps(cols), [g.wkb for g in roads.geometry], str(gmns), str(src) if src else None, bool(on))
    for n in notes:
        print(n, flush=True)
    roads["width_m"] = width
    roads.geometry = [wkb.loads(bytes(b)) for b in lines]
    return [], json.loads(kw)
