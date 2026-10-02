# Put it on a website

<p class="lead">The map is one HTML file. Serve it, embed it, or script it: everything roadstyle's pages can do, a lanestyle page can.</p>

## Serve it

`render_lanes(...).save("lanes.html")` writes a page that opens straight from disk. For a URL,
`ls.write_serve("lanes.html")` drops a `serve.py` next to it:

```bash
python serve.py 8080      # http://localhost:8080/lanes.html, no caching
```

It serves the folder with `Cache-Control: no-store`, so a rebuilt map shows at once. Working
remotely? Forward the port (VS Code's Ports panel, or `ssh -L 8080:localhost:8080 host`).

## Open it at a spot

A page opens at the place in its address: `monaco.html#zoom/lat/lon`, for example `monaco.html#20.5/43.73204/7.41653` (longitude last, as in OpenStreetMap links).
Change the address and the map moves. It is how a link can point at one junction.

## Embed it

```html
<iframe src="monaco.html" style="width:100%;height:600px;border:0"></iframe>
```

The page on this site is exactly that: [Get started](../get-started.md).

## Drive it from JavaScript

The page is a roadstyle page, so the whole `window.rs*` API is there. Lane properties are the lane
table's columns:

```js
const bus = rsQuery(p => p.use === "bus");          // feature ids
rsColor(bus, "#ff8800"); rsFocus(bus);              // paint them, fit the camera
rsSelect(rsQuery(p => p.lane_id === "8121729169906061189_2")[0]);   // click a lane by its id
document.addEventListener("rs:select", e => console.log(e.detail.properties.lane_type));
```

Feature ids are indexes into roadstyle's source, not `lane_id`s: look a lane up with `rsQuery`.
Every function and event: roadstyle's
[JavaScript API](https://khoshkhah.github.io/roadstyle/reference/javascript/).

## Base maps and keys

The default base map is CARTO's Voyager, which needs a free key (`CARTO_API_KEY` in the
environment, or roadstyle's settings); without one its tiles are stamped *API KEY REQUIRED*.
Keyless choices: `basemap="esri_street"`, `"osm"`, `"blank"`. Details:
roadstyle's [API keys](https://khoshkhah.github.io/roadstyle/get-started/#api-keys).
