# Settings

<p class="lead">roadstyle's settings apply as they are. lanestyle adds one key, `lanes`, with these defaults.</p>

```json
--8<-- "src/lanestyle/data/lanestyle.json"
```

Override them the roadstyle way, stating only what changes: a `lanestyle.json` in the current
folder, or a `"lanes"` key in `settings=`:

```python
ls.render_lanes(lanes, turns=turns, settings={"lanes": {"colors": {"bus": "#d35400"}}})
```

| Key | Default | Meaning |
|---|---|---|
| `colors.crossing` | light amber | a crosswalk lane (OSM `footway=crossing`), under the road with the zebra on it: lighter than a footway, with its own row in the Roads box |
| `colors.sidewalk` | light terracotta | a mapped sidewalk (OSM `footway=sidewalk`), with its own row in the Roads box (*sidewalks*); the verge between it and its road is a lighter tint of it |
| `colors.auto`, `colors.bus`, `colors.bike`, `colors.walk` | grey, pink, blue, amber | each lane is coloured by its mode group, with a row each in the Roads box (*car lanes*, *bus lanes*, *bike lanes*, *footways*); a use without a group of its own gets the car colour |
| `colors.clicked` | red | the clicked lane (also roadstyle's selection glow) |
| `colors.turns_into` | green | the lanes the clicked lane leads into |
| `colors.uturn` | purple | the lanes it reaches by a U-turn |
| `lines.divider`, `lines.centre`, `lines.edge` | see [Lane lines](../guides/lane-lines.md) | `color`, `width_m`, `dash_m` (`null` = solid) per type; `"lines": false` turns them off |
| `junction_trim_m` | 1 | how far lines stop short of the other roads' surface at a junction |
| `frame_gap_m` | 2 | a sidewalk within this many metres of the road it runs along (duckOSM's `along_link_id`) is one frame with it: the gap is filled in the footway colour and no outline is drawn between them; 0 = off |
| `frame_reach_m` | 8 | the widest gap between a road and its footpath that is filled (a framed footpath has its whole gap filled, wherever it is wider than `frame_gap_m`) |
| `crossing_max_m`, `crossing_min_on` | 12, 0.2 | a `footway=crossing` link longer than this many metres with under this share of its length on a road is drawn as a footway (OSM tagged a whole way a crossing where only its end crosses); `crossing_max_m` 0 = off |
| `frame_casing` | false | draw an edge line along the gap's own sides (those touching neither the road nor the footpath); off, it drew stray arcs |
| `connectors_clickable` | false | a connector (the surface joining two lanes at a junction) can be clicked and hovered like a lane; off, the click goes to the lane under it (or to nothing) |
| `tunnel_body` | `#f6f4ee` | the land colour of an opaque base drawn under the faded fill of tunnel lanes, so the casing ring of one lane's round end does not show inside the next; `""` = off |
| `fillet_m` | 0 (off) | pave gaps narrower than twice this between lane surfaces |
| `line_min_device_px` | 1.5 | lines are never thinner than this many physical pixels |
| `type_label_zoom` | `null` | a zoom number draws each lane's turns along it (`left + thru`) from that zoom; `null` (default) = no labels: they are in the popup as `lane_type` |
| `default_width_m` | 3.25 | lane width where `width_m` is null |
| `width_m_by_use` | `{"walk": 2.0, "bike": 1.5}` | the width where `width_m` is null, for a footpath (`walk`) and for an on-road bike lane: a `bike` lane beyond the link's motor lanes (`lane_num` > `lanes`; empty `lanes` counts as 0, as on a cycleway). Any other lane is `default_width_m` |
| `casing_m` | 0 | roadstyle's casing inside each lane's width (0: lanes merge into one surface) |
| `width_m_zoom` | 16 | from this zoom on, lanes are their width in metres; roadstyle's class widths below |

roadstyle's own settings (palettes, base maps, labels, arrows, tunnels) go in the same `settings=`
dict or a `roadstyle.json`: roadstyle's
[Settings & palettes](https://khoshkhah.github.io/roadstyle/reference/settings/). lanestyle sets two things
for lane maps: a palette with one grey for every class (lanes are coloured by mode group; the class dashes of a footway
or path stay, in the mode colour) and a lighter tunnel look. A lane's level decides where it is drawn: see
[Lane table](../guides/lane-table.md).
