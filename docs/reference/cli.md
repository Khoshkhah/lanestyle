# Command line

<p class="lead">One script in the repo, `lane_page.py`: the level area, the GMNS file and the duckOSM database in, a page out.</p>

```bash
python lane_page.py AREA GMNS_DB SOURCE_DB OUT.html [--connectors]
```

| argument | what |
|---|---|
| `AREA` | the level area (`duckosm levels SOURCE_DB` makes `SOURCE_DB.levels`) |
| `GMNS_DB` | `duckosm gmns SOURCE_DB -o GMNS_DB` |
| `SOURCE_DB` | the duckOSM database |
| `OUT.html` | the page |
| `--connectors` | also the lane connectors, unseen |

The page is blank, just the lanes. The editor with the same drawing:
`roadstyle-levels edit AREA --items lanestyle.editor:lane_items` ([the editor](../guides/editor.md)).
