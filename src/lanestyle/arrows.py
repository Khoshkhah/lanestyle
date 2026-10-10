"""Painted lane arrows (docs/design/lane_arrows.md): the one direction marking of a lane map, a generic arrow from the movements that leave each lane."""
from __future__ import annotations

_TURNS = {"left", "right", "uturn"}


def _kinds(lane_id, link_id, turns_of):
    """The move arrow of a lane: its left / right / thru / uturn, or None. A thru-only lane has one only beside a lane that turns;
    a fork, a merge or an end is shape, not marking, so those lanes get the plain direction arrow only."""
    own = turns_of.get(lane_id, set()) & (_TURNS | {"thru"})
    if not own:
        return None
    if own == {"thru"}:
        return own if any(turns_of.get(o, set()) & _TURNS for o in link_id) else None
    return own - {"uturn"} if own != {"uturn"} and own & {"left", "right", "thru"} else own   # ponytail: a uturn beside other moves is not drawn; a hook of its own if it ever matters


_ORDER = ("left", "thru", "right")


def _mark_name(kinds):
    """strokes.shape's name for a set of moves: "uturn", or the moves in left / thru / right order joined by "+"."""
    if kinds == {"uturn"}:
        return "uturn"
    return "+".join(k for k in _ORDER if k in kinds) or "thru"


def mark_strokes(lanes, turns, s, shifts, colour="#ffffff"):
    """The painted marks of each lane as LINE items (2026-10-10, docs/design/lane_arrows.md; strokes.py): a car lane's arrow (its moves, from
    ``turns``) ``end_m`` before its end, then a plain arrow back along it every ``repeat_m``; a bus lane's BUS and a bike lane's bike from 15 m,
    then every ``repeat_m`` (a shared ``bus,bike`` lane: BUS, its bike 12 m after). Each mark lies on its lane's own line, shifted as the lane (``shifts``, :func:`lanestyle.items.lane_shifts`), so it
    is exactly where the lane is filled; one item per lane and stroke width (a MultiLineString; ``edge_id`` its link, ``order`` ARROW).
    ``s``: ``lanes.arrows``; with ``at_junctions`` (2026-10-10) a car lane gets its arrow only where its link ends at a junction: three or more
    roads with car lanes at its end node (a two-way road counted once), not where a street just goes on into its next link. None when nothing is marked."""

    from lanestyle import strokes

    if not s or "link_id" not in lanes:
        return None
    turns_of = {}
    if turns is not None and len(turns):
        kind = turns["type"].where(turns["turn"].isna(), turns["turn"]) if "turn" in turns and "type" in turns else (turns["type"] if "type" in turns else [])
        for a, t in zip(turns["from_lane"].astype(str), kind):
            turns_of.setdefault(a, set()).add(t)
    lanes = lanes.reset_index(drop=True)
    siblings = lanes.groupby("link_id")["lane_id"].apply(lambda x: [str(i) for i in x]).to_dict()
    back, every = float(s["end_m"]), float(s.get("repeat_m") or 0)
    junction = None
    if s.get("at_junctions"):
        if not {"from_node_id", "to_node_id"} <= set(lanes.columns):
            raise ValueError("lanestyle arrows at_junctions: the lanes have no from_node_id / to_node_id")
        car = lanes[~lanes["use"].fillna("auto").astype(str).isin(["walk", "bike"])]
        roads_at = {}
        for a, b in set(zip(car["from_node_id"], car["to_node_id"])):
            for n in (a, b):
                roads_at.setdefault(n, set()).add(frozenset((a, b)))      # the two directions of a road: one road
        junction = {n for n, rs in roads_at.items() if len(rs) >= 3}
    out = []
    for i, r in enumerate(lanes.itertuples()):
        use, ln, w = str(getattr(r, "use", "auto") or "auto"), r.geometry, float(r.width_m)
        if ln is None or ln.geom_type != "LineString" or use == "walk":
            continue
        n = strokes.length_m(ln)
        if use.startswith("bus") or use == "bike":
            name = "bus" if use.startswith("bus") else "bike"
            at = [(d, name) for d in strokes.positions(n, 15, every or 60, back)]
            if name == "bus" and "bike" in use.split(","):        # a bus lane bikes share: its bike 12 m after each BUS, where it fits (2026-10-10)
                at += [(d + 12, "bike") for d, _ in list(at) if d + 12 + strokes.LENGTH / 2 <= n]
        else:
            if n < strokes.LENGTH + 2 or (junction is not None and r.to_node_id not in junction):
                continue
            end = n - back if n >= 2 * back else n / 2
            at = [(end, _mark_name(_kinds(str(r.lane_id), siblings[r.link_id], turns_of) or {"thru"}))]
            while every and at[-1][0] - every > 2 * strokes.LENGTH:
                at.append((at[-1][0] - every, "thru"))
        by_w = {}
        for d, name in at:
            for f in strokes.place(strokes.shape(name, w), ln, d, w, offset_m=shifts[i]):
                by_w.setdefault(f["properties"]["width_m"], []).append(f["geometry"]["coordinates"])
        for wm, parts in by_w.items():
            out.append({"type": "Feature", "geometry": {"type": "MultiLineString", "coordinates": parts},
                        "properties": {"edge_id": int(r.link_id), "order": 3, "color": colour, "width_m": wm, "offset_m": 0.0, "lane_id": str(r.lane_id),
                                       **({"minzoom": float(s["minzoom"])} if s.get("minzoom") is not None else {})}})   # 2026-10-10: specks zoomed out
    return {"type": "FeatureCollection", "features": out} if out else None
