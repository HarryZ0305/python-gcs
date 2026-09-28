"""
Unit tests for map tile server security (path traversal prevention),
OSM tile URL formatting, and offline MBTiles database retrieval.
"""
import os
import sqlite3
import tempfile
import pytest
from gcs.ui.tile_server import (
    is_path_safe,
    set_mbtiles_file,
    get_tile_from_mbtiles,
    tile_cache_dir
)

def test_is_path_safe_containment():
    base = os.path.abspath(tile_cache_dir)

    # Safe sub-paths
    safe_child = os.path.join(base, "14", "8523", "5721.png")
    assert is_path_safe(base, safe_child) is True

    # Traversal attempts escaping the base directory
    traversal_escape = os.path.abspath(os.path.join(base, "..", "..", "system32", "cmd.exe"))
    assert is_path_safe(base, traversal_escape) is False

    # Sneaky double-dot inside subfolder escaping out
    sneaky = os.path.join(base, "14", "..", "..", "..", "passwords.txt")
    assert is_path_safe(base, sneaky) is False


def test_mbtiles_tile_lookup():
    with tempfile.NamedTemporaryFile(suffix=".mbtiles", delete=False) as tf:
        db_path = tf.name

    try:
        # Create standard MBTiles SQLite schema
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE metadata (name text, value text);")
        cur.execute("CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob);")

        # In MBTiles, TMS tile_row for Slippy (z=2, x=1, y=1) is:
        # tms_y = (1 << 2) - 1 - 1 = 4 - 1 - 1 = 2
        fake_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest_tile_data"
        cur.execute(
            "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
            (2, 1, 2, fake_png_data)
        )
        conn.commit()
        conn.close()

        set_mbtiles_file(db_path)

        # Query existing tile
        retrieved = get_tile_from_mbtiles(z=2, x=1, y=1)
        assert retrieved == fake_png_data

        # Query non-existent tile
        empty = get_tile_from_mbtiles(z=2, x=0, y=0)
        assert empty is None

    finally:
        set_mbtiles_file(None)
        if os.path.exists(db_path):
            os.remove(db_path)
