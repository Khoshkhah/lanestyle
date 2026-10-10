# Settings

<p class="lead">One file: lanestyle's `data/lanestyle.json`, with a `lanestyle.json` in the current folder on top.</p>

Your `lanestyle.json` states only what it changes, as roadstyle's settings do:

```json
{"lanes": {"colors": {"bus": "#e8590c"}, "lines": {"dash_m": 2.0}}}
```

| key | default | what |
|---|---|---|
| `colors.auto` / `bus` / `bike` / `walk` | `#a3a3a3` / `#d6336c` / `#1c7ed6` / `#f0cb8c` | a lane by its use (car lanes are drawn invisible; the road is in `auto`) |
| `colors.groups` | walking `#f0cb8c`, cycling and walking+cycling `#1c7ed6` | a road cars do not use, by who uses it |
| `default_width_m` | `3.25` | a lane with no width tag |
| `width_m_by_use` | walk `2.0`, bike `1.5` | an untagged footpath, an on-road bike lane |
| `casing_m` / `casing_min_px` | `0.14` / `1` | the road's outline, metres, and at least this many pixels |
| `centre_line_m` | `0.15` | the gap between two directions, where the centre line lies |
| `lines` | dashes 3 m / gaps 9 m, `0.15` m wide, `#f2f2f2`, from zoom 17 | lane lines (`divider`, `centre` switch them) |
| `junction_trim_m` | `1` | a lane line stops this far before its lane's end |
| `arrows` | `end_m` 10, `repeat_m` 0, `at_junctions` true, from zoom 18 | turn arrows: before the lane's end, again every `repeat_m` (0: once) |
| `zebra` | `stripe_m` 0.5, `gap_m` 0.5, from zoom 17 | painted crossings |
| `sidewalk` | `width_m` 2.0, from zoom 17 | sidewalks a street's tags name |
| `tunnel_body` | `#f6f4ee` | the ground colour a tunnel's paint is faded toward |

The road's own look (tunnels, bridges, names) is roadstyle's: a `roadstyle.json` in the current folder
([roadstyle's settings](https://khoshkhah.github.io/roadstyle/reference/parameters/)).
