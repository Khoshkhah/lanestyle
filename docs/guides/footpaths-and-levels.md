# Footpaths, levels and connectors

<p class="lead">A map of cars and pedestrians together: sidewalks next to their roads, zebras, tunnels over tunnels. All of it is drawing: nothing the data says is moved.</p>

Build both networks and read them into one table:

```bash
duckosm gmns area.duckdb -m driving -m walking -o area_gmns.duckdb
```

```python
lanes, turns = ls.from_gmns("area_gmns.duckdb", modes=("driving", "walking"), source_db="area.duckdb")
m = ls.render_lanes(lanes, turns=turns)
```

## Sidewalks and the gap to the road

duckOSM records, for every footpath, the roads it runs along (`link_along`: the footpath's route). A sidewalk is the OSM way `footway=sidewalk`; any other footway,
path, pedestrian or cycleway beside a road (within 5 m of its edge) is `adjacent`. lanestyle frames a footpath with every road of its route and
every other piece of that street within `frame_reach_m`:

- the gap between them is filled in a lighter tint of the footpath colour (a verge), and no outline is drawn between them;
- a mapped sidewalk has its own colour (`colors.sidewalk`), a footpath beside a road keeps the footway colour;
- the popup of a footpath says which road it runs along (`along`), the popup of a road which footpaths run along it (`footpaths`);
- the gap is not clickable and has no casing (`frame_casing`).

Only roads cars can use count: a service road closed to cars is no road to run along. A footpath that lies mostly on a road is drawn above it.

## Crossings

A zebra is painted from duckOSM's `crossing` / `lane_crossing` tables: one rectangle across the road, cut to each lane it covers. A `footway=crossing` way
that OSM tagged along a whole street (long, and off any road) is drawn as a footway; a short one stays a cream crosswalk.

## Levels

The level of a lane is its `layer`, else 1 for a bridge and -1 for a tunnel. A tunnel differs from ground in its **look** only (a faded, hatched fill); outlines,
joints and matching follow the same rules. Lanes on different layers never touch: layer -1 lies completely over layer -2, in colour and in its lines.
Layers above ground are still one band each.

## Connectors

A connector is the surface joining two lanes at a junction. It takes the modes both lanes have, is drawn under the lanes (turns below straight ones) and is
not clickable (`connectors_clickable`). Where a link goes on as one way, duckOSM writes the movements for the lanes that carry on (a lane drop merges,
a bike lane continues), so no lane has no way out. See [Settings](../reference/settings.md) for every key.
