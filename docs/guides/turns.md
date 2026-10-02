# Turns, clicks and labels

<p class="lead">The `turns` table says which lane leads into which. It makes a lane clickable, labels every lane with its turns, and fills the popup.</p>

<div class="ls-shot" markdown>
![A lane clicked at Larvotto: the lane red, the lanes it leads into green, its popup open](../img/gallery/click.jpg)
</div>

## The turns table

A DataFrame with `from_lane` and `to_lane` (both `lane_id`s) and an optional `type`:

| `type` | drawn as | label word |
|---|---|---|
| `thru`, `left`, `right` | green on a click | `thru`, `left`, `right` |
| `uturn` | purple on a click | `U-turn` |
| `diverge` | green | `fork` |
| `merge` | green | `merge` |

`from_gmns` builds it from the GMNS `movement` table: each lane of the inbound link in
`start_ib_lane`..`end_ib_lane` into the lane at the same place in `start_ob_lane`..`end_ob_lane`
(equal-length ranges paired in order, as osm2gmns and duckOSM write them; NULL means every lane).

## Click a lane

The clicked lane turns **red** (`colors.clicked`), the lanes it leads into **green**
(`colors.turns_into`), U-turns **purple** (`colors.uturn`). Connectors on the way are coloured with
the lanes they lead into. A U-turn at a road end is a half-circle through the two lane ends, as wide as the lanes (duckOSM writes it). Click the background to clear. Without `turns`, a click only selects.

The colours are in the settings:

```python
ls.render_lanes(lanes, turns=turns, settings={"lanes": {"colors": {
    "clicked": "#d62828", "turns_into": "#2a9d8f", "uturn": "#7b2cbf"}}})
```

## Type labels

Each lane's type is the turns that leave it (`left + thru`, `right`, `U-turn`, `fork`, `merge`), or `end` where
none does; a bus or bike lane says its use first (`bus · thru`). It is in the **popup** (`lane_type`), not drawn on
the map: the lanes are coloured by their mode group instead. To draw it along each lane, set `type_label_zoom` to a
zoom, e.g. `settings={"lanes": {"type_label_zoom": 18}}` (the default is `null`: no labels).

## The popup

The popup lists what the lane table has, in this order: `name`, `lane_type`, `connects` (for a
connector: "lane 2 of Boulevard X → lane 1 of Avenue Y"), `highway`, `lane_id`, `lane_num`, `lanes`,
`use`, `turn`, `width_m`, `tunnel`, `bridge`, `layer`, `turns_in`, `turns_out`, `from_lane`,
`to_lane`, `link_id`, `reverse_link_id`, `osm_id`, `from_node_id`, `to_node_id`.

## Connectors

With duckOSM's `lane_connector` table, `from_gmns` returns one row per connector (`connector` True):
the curve from a lane's end to the next lane's start through a junction, or where a lane shifts
sideways. They are drawn like lanes, without arrows, lane lines or labels, and take the level and
road class of the lane they leave.
