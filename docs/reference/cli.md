# Command line

<p class="lead">One script in the repo, `render_lanes.py`: a GMNS database in, a map and a server out.</p>

```bash
python render_lanes.py GMNS_DB OUT.html [--source-db DB] [--mode driving | --modes driving,walking] [--boundary FILE.geojson]
```

| Argument | Meaning |
|---|---|
| `GMNS_DB` | a duckOSM GMNS database (`duckosm gmns`) |
| `OUT.html` | the map; a `serve.py` is written next to it |
| `--source-db` | optional: the duckOSM database the GMNS file was made from, for the area's boundary when it has one, `osm_id`, and the levels of GMNS files made before duckOSM wrote them |
| `--mode` | the GMNS schema to read, `gmns_<mode>` (default `driving`) |
| `--modes` | several modes in one map, e.g. `driving,walking`: the first as it is, the others add only the links it does not have (footpaths, not the roads you also walk on). Wins over `--mode` |
| `--boundary` | a GeoJSON file to outline the area with instead |

```bash
python render_lanes.py monaco_gmns.duckdb monaco.html
# wrote monaco.html: 5308 lanes, 4359 turns
# serve it:  python serve.py 8080
```

The same from Python is three lines: [Get started](../get-started.md#your-own-area).
