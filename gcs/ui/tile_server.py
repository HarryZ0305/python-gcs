import os
import time
import math
import sqlite3
import urllib.request
import urllib.error
import http.server
import socketserver
import threading
from typing import Optional, Tuple
from gcs.logs import log
from gcs.paths import resource_path

PORT = 5501
server_instance = None
server_thread = None
_server_lock = threading.Lock()

tile_cache_dir = os.path.join(os.path.expanduser("~"), ".python-gcs", "tile_cache")
static_dir = resource_path(os.path.join('gcs', 'ui', 'static'))
_active_mbtiles_path: Optional[str] = None
_mbtiles_lock = threading.Lock()

def is_path_safe(base_dir: str, target_path: str) -> bool:
    """Verifies that target_path is strictly inside base_dir to prevent directory traversal."""
    try:
        base = os.path.abspath(base_dir)
        target = os.path.abspath(target_path)
        return os.path.commonpath([base, target]) == base
    except Exception:
        return False

def set_mbtiles_file(mbtiles_path: Optional[str]):
    global _active_mbtiles_path
    with _mbtiles_lock:
        if mbtiles_path and os.path.isfile(mbtiles_path):
            _active_mbtiles_path = os.path.abspath(mbtiles_path)
            log(f"Offline Map: Loaded MBTiles source: {_active_mbtiles_path}")
        else:
            _active_mbtiles_path = None

def get_tile_from_mbtiles(z: int, x: int, y: int) -> Optional[bytes]:
    """Extracts a tile from active MBTiles file (converting TMS tile_row to Slippy Y)."""
    with _mbtiles_lock:
        if not _active_mbtiles_path or not os.path.isfile(_active_mbtiles_path):
            return None
        db_path = _active_mbtiles_path

    try:
        # MBTiles schema uses TMS format: tms_y = (1 << zoom) - 1 - y
        tms_y = (1 << z) - 1 - y
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
            (z, x, tms_y)
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return bytes(row[0])
    except Exception as e:
        log(f"MBTiles query error ({z}/{x}/{y}): {e}")
    return None

def bootstrap_leaflet():
    """Ensure static files exist. Never attempts to write into a read-only PyInstaller directory."""
    # Check if bundled files exist in resource_path
    if os.path.exists(static_dir) and os.path.isfile(os.path.join(static_dir, 'leaflet.js')):
        return # Already bundled and present

    # If running in development and static files missing, attempt to download to user cache
    try:
        os.makedirs(static_dir, exist_ok=True)
        images_dir = os.path.join(static_dir, 'images')
        os.makedirs(images_dir, exist_ok=True)

        files = {
            'leaflet.js': 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
            'leaflet.css': 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
            'images/marker-icon.png': 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
            'images/marker-shadow.png': 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
            'images/marker-icon-2x.png': 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png'
        }
        headers = {'User-Agent': 'PythonGCS/1.0 (harryzhou935@gmail.com; Bootstrapper)'}
        for rel_path, url in files.items():
            dest_path = os.path.join(static_dir, rel_path.replace('/', os.sep))
            if not os.path.exists(dest_path):
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = response.read()
                with open(dest_path, 'wb') as f:
                    f.write(data)
    except Exception as e:
        log(f"Offline Map Bootstrapper notice: {e}")

class TileHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute normal request logs to avoid cluttering GCS console
        pass

    def do_GET(self):
        path = self.path
        if '?' in path:
            path = path.split('?')[0]

        if path.startswith('/static/'):
            self.serve_static(path)
        elif path.startswith('/tiles/'):
            self.serve_tile(path)
        else:
            self.send_error(404, "File Not Found")

    def serve_static(self, path):
        rel_path = path.replace('/static/', '', 1).replace('/', os.sep)
        file_path = os.path.join(static_dir, rel_path)

        if not is_path_safe(static_dir, file_path):
            self.send_error(403, "Access Denied")
            return

        if os.path.exists(file_path) and os.path.isfile(file_path):
            self.send_response(200)
            if file_path.endswith('.js'):
                self.send_header('Content-Type', 'application/javascript')
            elif file_path.endswith('.css'):
                self.send_header('Content-Type', 'text/css')
            elif file_path.endswith('.png'):
                self.send_header('Content-Type', 'image/png')
            elif file_path.endswith('.ttf'):
                self.send_header('Content-Type', 'font/ttf')
            else:
                self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            with open(file_path, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "File Not Found")

    def serve_tile(self, path):
        # Expected format: /tiles/z/x/y.png
        parts = path.strip('/').split('/')
        if len(parts) != 4 or parts[0] != 'tiles':
            self.send_error(400, "Bad Request")
            return

        z_str, x_str, y_file = parts[1], parts[2], parts[3]
        if not y_file.endswith('.png'):
            self.send_error(400, "Bad Request: Tile must end in .png")
            return

        y_str = y_file[:-4]
        try:
            z, x, y = int(z_str), int(x_str), int(y_str)
            if not (0 <= z <= 19) or x < 0 or y < 0:
                self.send_error(400, "Tile coordinates out of bounds")
                return
        except ValueError:
            self.send_error(400, "Invalid tile coordinate values")
            return

        # 1. Check MBTiles if loaded
        mbtiles_data = get_tile_from_mbtiles(z, x, y)
        if mbtiles_data:
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Cache-Control', 'public, max-age=604800')
            self.end_headers()
            self.wfile.write(mbtiles_data)
            return

        # 2. Check local disk cache
        cache_path = os.path.join(tile_cache_dir, str(z), str(x), f"{y}.png")
        if not is_path_safe(tile_cache_dir, cache_path):
            self.send_error(403, "Access Denied")
            return

        if os.path.exists(cache_path) and os.path.isfile(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    tile_data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'public, max-age=604800')
                self.end_headers()
                self.wfile.write(tile_data)
                return
            except Exception:
                pass

        # 3. Download from OSM on demand with required .png suffix
        osm_url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        try:
            req = urllib.request.Request(
                osm_url,
                headers={'User-Agent': 'PythonGCS/1.0 (harryzhou935@gmail.com; GCS Tile Cache Proxy)'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                tile_data = response.read()

            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'wb') as f:
                f.write(tile_data)

            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Cache-Control', 'public, max-age=604800')
            self.end_headers()
            self.wfile.write(tile_data)
        except urllib.error.HTTPError as e:
            self.send_error(e.code, f"Tile Error: {e.reason}")
        except urllib.error.URLError:
            self.send_error(404, "Tile Not Found (Offline)")
        except Exception as e:
            self.send_error(500, f"Error: {e}")

def find_free_port():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def start_server():
    global server_instance, server_thread, PORT
    with _server_lock:
        if server_instance is not None:
            return PORT

        bootstrap_leaflet()

        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('localhost', PORT))
            s.close()
        except Exception:
            PORT = find_free_port()

        class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        server_instance = ThreadingHTTPServer(('localhost', PORT), TileHTTPRequestHandler)
        server_thread = threading.Thread(target=server_instance.serve_forever, daemon=True)
        server_thread.start()
        log(f"Tile Server: Started on http://localhost:{PORT}")
        return PORT

def stop_server():
    global server_instance
    with _server_lock:
        if server_instance is not None:
            try:
                server_instance.shutdown()
                server_instance.server_close()
            except Exception as e:
                log(f"Tile Server shutdown exception: {e}")
            server_instance = None
            log("Tile Server: Stopped.")

def latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return xtile, ytile
