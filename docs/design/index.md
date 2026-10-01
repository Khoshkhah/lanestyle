# Design notes

<p class="lead">How lanestyle came to be built the way it is: the problems, the options and what was decided.</p>

- [lanestyle on roadstyle](lanestyle_on_roadstyle.md): why each lane is a roadstyle line, the one
  roadstyle change (widths in metres), the lane table, and the lane lines as their own layer.
- [GMNS CSV input](gmns_csv_input.md): reading plain GMNS files without duckOSM, and the simple lane
  placement that needs.
- [One file: `link_osm`](gmns_link_osm.md): levels inside the GMNS database, so lanestyle needs one input.

The lane placement itself lives in duckOSM, with its own notes: paired carriageways, lane
movements, lane connectors, and runs of pieces as one road.
See [duckOSM's design notes](https://github.com/Khoshkhah/duckOSM/tree/main/docs/design).
