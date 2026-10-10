# Fix the drawing in the editor

<p class="lead">The page draws your level area; roadstyle's level editor changes it, with your lanes on the roads.</p>

![Tunnel Dorsale under Avenue Prince Pierre at zoom 19](../img/gallery/tunnel.jpg)

Which road is drawn over which, and how each road ends (its heads, round, square or flat caps), comes
from the level area (`duckosm levels` makes `monaco.levels/`). Fix a place in the editor, and the page
you build next draws it the same way, because both use the same drawing:

```bash
LANESTYLE_GMNS=monaco_gmns.duckdb LANESTYLE_SOURCE_DB=monaco.duckdb \
    roadstyle-levels edit monaco.levels --items lanestyle.editor:lane_items
```

Open `http://localhost:8780/?at=7.4218,43.7350,18` to start at a place (longitude, latitude, zoom).

- Click two roads to see the rules between them and add one: a road over another (an order), one of its
  ends over it (a stack), or two roads that meet.
- A rule you add that the solver cannot keep says why: the rules it makes a loop with. Switch one of them
  off.
- Apply redraws the changed roads and their lanes in place.

Your edits are kept in `monaco.levels/edits.csv`, `heads.csv` and `caps.csv`; `duckosm levels` keeps them
when it makes the area again.
