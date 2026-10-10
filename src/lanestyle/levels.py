"""The band of a link from its tags (roadstyle's ``band_col``): what :func:`lanestyle.items.link_roads` gives each road it makes from the lanes."""
from __future__ import annotations

_SIDEWALK, _CROSSING = -1, 1


def tags_band(table):
    """The band of every row, complete (roadstyle's ``band_col`` replaces the level from the tags and a null is 0): the OSM ``layer`` if it is a number, else 1 for a bridge,
    -1 for a tunnel, else 0; except a mapped sidewalk (-1, under its street) and a crossing (1, over it). The same as duckOSM's and mapstyle's."""
    import numpy as np
    import pandas as pd

    def col(name):
        return table[name] if name in table else pd.Series([None] * len(table), index=table.index)

    def yes(s):
        return (s.notna() & ~s.astype(str).isin(["", "no", "None", "nan", "False", "false"])).to_numpy()
    layer = pd.to_numeric(col("layer"), errors="coerce").fillna(0).astype(int).to_numpy()
    tags = np.where(layer != 0, layer, np.where(yes(col("bridge")), 1, np.where(yes(col("tunnel")), -1, 0)))
    foot = col("footway").map({"sidewalk": _SIDEWALK, "crossing": _CROSSING}).fillna(0).astype(int).to_numpy()
    return np.where(foot != 0, foot, tags).astype(int)

