import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


@pytest.fixture
def store(tmp_path):
    """An empty store directory; tests add items to it."""
    d = tmp_path / "plugins"
    d.mkdir()
    return str(d)


@pytest.fixture
def make_plugin(store):
    """Create a plugin dir. header_version goes in the PHP header,
    stable_tag goes in readme.txt. Either may be None to omit it."""
    def _make(slug, header_version="1.0.0", stable_tag="1.0.0"):
        path = os.path.join(store, slug)
        os.makedirs(path, exist_ok=True)
        if header_version is not None:
            write(os.path.join(path, slug + ".php"),
                  "<?php\n/*\n * Plugin Name: %s\n * Version: %s\n */\n"
                  % (slug, header_version))
        if stable_tag is not None:
            write(os.path.join(path, "readme.txt"),
                  "=== %s ===\nStable tag: %s\n" % (slug, stable_tag))
        return path
    return _make


@pytest.fixture
def make_theme(store):
    def _make(slug, version="1.0.0"):
        path = os.path.join(store, slug)
        os.makedirs(path, exist_ok=True)
        if version is not None:
            write(os.path.join(path, "style.css"),
                  "/*\nTheme Name: %s\nVersion: %s\n*/\n" % (slug, version))
        return path
    return _make
