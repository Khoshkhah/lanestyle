"""The calls into lanestyle's Rust engine, the extension module ``lanestyle._rust`` (built from ``rust/lanestyle-py``)."""


def rust():
    """The Rust extension module, or an ImportError that says how to build it."""
    try:
        from lanestyle import _rust
    except ImportError as e:
        raise ImportError("lanestyle needs its Rust extension lanestyle._rust: pip install lanestyle, or in a source checkout: "
                          "python rust/lanestyle-py/build.py") from e
    return _rust
