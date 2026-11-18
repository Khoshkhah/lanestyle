"""lanestyle: lane-level maps on roadstyle. roadstyle draws every road (the level editor's drawing); lanestyle adds the roads' own items
from duckOSM's GMNS lanes (lanes, lane lines, arrows, BUS and bike marks, zebras, sidewalks). ``lane_page`` makes the page. The rules are
Rust (the crate ``lanestyle``); this package calls them (``lanestyle._rust``)."""
from lanestyle.gmns import (
    boundary_from_geojson,
    from_gmns,
    read_boundary,
    read_crossings,
)
from lanestyle.page import lane_page
from lanestyle.settings import lane_settings

__version__ = "0.4.0"
__all__ = ["lane_page", "from_gmns", "read_crossings", "read_boundary", "boundary_from_geojson", "lane_settings"]
