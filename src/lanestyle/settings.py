"""lanestyle's settings and its rules for a lane's colour and width (2026-10-10, kept from the old render.py when the lane page became
the level editor's drawing): ``data/lanestyle.json`` with any local ``lanestyle.json`` on top."""
import json
from pathlib import Path

_MARKED = ("auto", "bus", "bike", "walk")       # the mode groups: each has its colour and a legend row
_USE_NAME = {"auto": "car lanes", "bus": "bus lanes", "bike": "bike lanes", "walk": "footways"}      # the legend rows
# with several modes loaded (``from_gmns(modes=...)``) a lane of a road cars do not use is coloured by who uses it
_GROUP_ORDER = ("walking", "cycling")
_GROUP_NAME = {"walking": "pedestrians only", "cycling": "bikes only", "walking+cycling": "pedestrians + bikes"}


def _colour_groups(g, s):
    """What colours the lanes and what the Roads box lists: ``(column, {value: colour}, [(label, colour)])``.

    A lane of a road cars use is coloured by its ``use`` (car, bus, bike, walk). With several modes loaded (a ``modes`` column from
    ``from_gmns(modes=...)``), a lane of a road cars do not use takes the colour of who uses it (``colors.groups``: walking, cycling,
    walking+cycling), as the level editor colours that road (2026-10-09: one rule; before, every set of modes had its colour, cars too)."""
    col = s["colors"]
    def key(u):          # a shared lane ("bus,bike": a bus lane bikes may use) is the first of bus, bike, walk it allows; a use of none of them is a car lane's
        return u if u in _MARKED else next((m for m in ("bus", "bike", "walk") if m in u.split(",")), "auto")
    keys = {u: key(u) for u in set(g["use"])}
    if "modes" in g and g["modes"].replace("", None).dropna().nunique() > 1:
        who = g["modes"].fillna("").map(lambda m: None if "driving" in m.split(",") else "+".join(x for x in _GROUP_ORDER if x in m.split(",")) or None)
        if "connector" in g:     # a connector of a car road's lane keeps its lane's use
            who = who.where(~g["connector"].fillna(False).astype(bool) | who.notna(), None)
        g["mode_group"] = [w if isinstance(w, str) else keys[u] for w, u in zip(who, g["use"], strict=True)]
        colours = {k: col[k] for k in _MARKED} | {k: col["groups"][k] for k in set(who.dropna())}
        present = set(g["mode_group"])
        rows = [(_USE_NAME[k], col[k]) for k in _MARKED if k in present] + [(_GROUP_NAME[k], col["groups"][k]) for k in _GROUP_NAME if k in present]
        return "mode_group", colours, rows
    present = [k for k in _MARKED if k in set(keys.values())]
    return "use", {u: col[k] for u, k in keys.items()}, [(_USE_NAME[k], col[k]) for k in present]


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


def _widths(g, s):
    """Each lane's width in metres: its own ``width_m``, else a default by use (``width_m_by_use``): a ``walk`` lane is
    a footpath, and a ``bike`` lane *beyond the link's motor lanes* (``lane_num`` > ``lanes``; empty ``lanes`` is 0,
    as on a cycleway) is an on-road bike lane, both narrow; any other lane is ``default_width_m``."""
    import pandas as pd

    w = g["width_m"] if "width_m" in g else pd.Series(float("nan"), index=g.index)
    by = s.get("width_m_by_use") or {}
    default = pd.Series(float(s["default_width_m"]), index=g.index)
    if "walk" in by:
        default[g["use"] == "walk"] = by["walk"]
    if "bike" in by and {"lane_num", "lanes"} <= set(g.columns):
        beyond = pd.to_numeric(g["lane_num"], errors="coerce") > pd.to_numeric(g["lanes"], errors="coerce").fillna(0)
        default[(g["use"] == "bike") & beyond] = by["bike"]
    return w.fillna(default)


def _roads_only(g):
    """The lanes of links that have a road class: a link with none is no road (a ferry in the walking network, a way with no ``highway`` tag)."""
    return g[g["highway"].notna()] if "highway" in g and g["highway"].isna().any() else g
