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
| `colors.bus`, `colors.bike` | muted blue, blue | lane colours painted over the palette, with a row each in the Roads box |
| `colors.clicked` | red | the clicked lane (also roadstyle's selection glow) |
| `colors.turns_into` | green | the lanes the clicked lane leads into |
| `colors.uturn` | purple | the lanes it reaches by a U-turn |
| `lines.divider`, `lines.centre`, `lines.edge` | see [Lane lines](../guides/lane-lines.md) | `color`, `width_m`, `dash_m` (`null` = solid) per type; `"lines": false` turns them off |
| `junction_trim_m` | 1 | how far lines stop short of the other roads' surface at a junction |
| `fillet_m` | 0 (off) | pave gaps narrower than twice this between lane surfaces |
| `line_min_device_px` | 1.5 | lines are never thinner than this many physical pixels |
| `type_label_zoom` | 18 | the zoom the lane type labels appear at; `null` = no labels |
| `default_width_m` | 3.25 | lane width where `width_m` is null |
| `casing_m` | 0 | roadstyle's casing inside each lane's width (0: lanes merge into one surface) |
| `width_m_zoom` | 16 | from this zoom on, lanes are their width in metres; roadstyle's class widths below |

roadstyle's own settings (palettes, base maps, labels, arrows, tunnels) go in the same `settings=`
dict or a `roadstyle.json`: roadstyle's
[Settings & palettes](https://khoshkhah.github.io/roadstyle/reference/settings/). lanestyle sets
three of them for lane maps: tunnels at 85 % opacity, with no gap shade and no fill dashes.
