"""lanestyle's settings: ``data/lanestyle.json`` of the Rust engine, then a local ``lanestyle.json``, then ``settings["lanes"]``."""
import json

from lanestyle._rust_call import rust


def lane_settings(settings=None):
    """lanestyle's settings: its own defaults, then a ``lanestyle.json`` in the current folder, then ``settings["lanes"]``, each overriding
    only what it states (the roadstyle.json way)."""
    return json.loads(rust().lane_settings(json.dumps(settings) if settings is not None else None))
