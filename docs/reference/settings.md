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
| `colors.auto`, `colors.bus`, `colors.bike`, `colors.walk` | grey, pink, blue, amber | each lane is coloured by its mode group, with a row each in the Roads box (*car lanes*, *bus lanes*, *bike lanes*, *footways*); a use without a group of its own gets the car colour |
| `colors.clicked` | red | the clicked lane (also roadstyle's selection glow) |
| `colors.turns_into` | green | the lanes the clicked lane leads into |
| `colors.uturn` | purple | the lanes it reaches by a U-turn |
| `lines.divider`, `lines.centre`, `lines.edge` | see [Lane lines](../guides/lane-lines.md) | `color`, `width_m`, `dash_m` (`null` = solid) per type; `"lines": false` turns them off |
| `junction_trim_m` | 1 | how far lines stop short of the other roads' surface at a junction |
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
