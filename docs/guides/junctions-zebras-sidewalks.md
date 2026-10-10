# Junctions, zebras and sidewalks

<p class="lead">Lanes stop where a junction begins; painted crossings and tagged sidewalks are drawn, nothing is guessed.</p>

![Boulevard Albert 1er at zoom 18: arrows before the junctions, zebras, the plaza's sidewalks](../img/gallery/albert_1er.jpg)

## Junctions

A junction is plain, as on a real road: the lanes, their lines and arrows stop where it begins, and the
road surface goes on through it. Where it begins is SUMO's (duckOSM's GMNS export cuts each lane there);
the lane stays on duckOSM's own line, so it never jumps sideways. Where a lane goes on straight into the
lane of the next road (a road that splits into two, two that merge), the two lane lines meet: duckOSM
bends the narrower road's lane to its place in the wider one.

The connectors (SUMO's paths from lane to lane through a junction) are not drawn: `lane_page(...,
connectors=True)` adds them unseen, for a page that highlights routes.

## Zebras

A crossing duckOSM calls painted (OSM `crossing=marked` / `zebra`, `crossing:markings`) is white stripes
across the road it crosses: `zebra.stripe_m` (0.5 m) wide, `zebra.gap_m` apart, as long as the crossing is
wide, from zoom 17. The stripes are the street's own items: a bridge over the street covers them.
An unmarked crossing shows only its footway.

## Sidewalks

A sidewalk mapped as its own way (`footway=sidewalk`) is drawn by roadstyle like any footway. A sidewalk
only in a street's tags (`sidewalk=left`, `right` or `both`) is a strip in the walk colour just outside
the street, on that side of the OSM way, as wide as `sidewalk:width` (else `sidewalk.width_m`, 2 m), from
zoom 17; it stops where the street's lanes stop. `sidewalk=separate`, `no`, a bare `yes` and no tag add
nothing.
