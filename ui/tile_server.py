import os
import time
import urllib.request
import urllib.error
import http.server
import socketserver
import threading
from logs import log

PORT = 5501
server_instance = None
server_thread = None
tile_cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tile_cache'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'static'))

def bootstrap_leaflet():
    """Download Leaflet JS, CSS and marker images for offline use if not present."""
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
    
    # Use proper User-Agent to avoid issues with unpkg or OSM CDN
    headers = {'User-Agent': 'PythonGCS/1.0 (harryzhou935@gmail.com; Bootstrapper)'}
    
    for rel_path, url in files.items():
        dest_path = os.path.join(static_dir, rel_path.replace('/', os.sep))
        if not os.path.exists(dest_path):
            try:
                log(f"Offline Map Bootstrapper: downloading {url}...")
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = response.read()
                with open(dest_path, 'wb') as f:
                    f.write(data)
            except Exception as e:
                log(f"Offline Map Bootstrapper Error: Failed to bootstrap {rel_path}: {e}")

class TileHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute console request logging to keep GCS clean
        pass

    def do_GET(self):
        # Parse path (strip query params)
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
        # Protect against directory traversal
        rel_path = path.replace('/static/', '', 1).replace('/', os.sep)
        file_path = os.path.abspath(os.path.join(static_dir, rel_path))
        
        if not file_path.startswith(static_dir):
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
            else:
                self.send_header('Content-Type', 'application/octet-stream')
            self.end_headers()
            with open(file_path, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "File Not Found")

    def serve_tile(self, path):
        # expected format: /tiles/z/x/y.png
        parts = path.strip('/').split('/')
        if len(parts) != 4 or parts[0] != 'tiles':
            self.send_error(400, "Bad Request")
            return
            
        z, x, y = parts[1], parts[2], parts[3]
        if not y.endswith('.png'):
            self.send_error(400, "Bad Request")
            return
            
        cache_path = os.path.abspath(os.path.join(tile_cache_dir, z, x, y))
        
        # Security path checks
        if not cache_path.startswith(os.path.abspath(tile_cache_dir)):
            self.send_error(403, "Access Denied")
            return
            
        # 1. Return from disk cache if exists
        if os.path.exists(cache_path) and os.path.isfile(cache_path):
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.end_headers()
            with open(cache_path, 'rb') as f:
                self.wfile.write(f.read())
            return
            
        # 2. Download from OSM on demand and cache if online
        osm_url = f"https://tile.openstreetmap.org/{z}/{x}/{y}"
        try:
            req = urllib.request.Request(
                osm_url,
                headers={'User-Agent': 'PythonGCS/1.0 (harryzhou935@gmail.com; GCS Map Cache Proxy)'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                tile_data = response.read()
                
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'wb') as f:
                f.write(tile_data)
                
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.end_headers()
            self.wfile.write(tile_data)
        except urllib.error.URLError:
            # Offline or connection timed out
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
    if server_instance is not None:
        return PORT
        
    bootstrap_leaflet()
    
    # Try default port 5501 first, fall back to dynamic if busy
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
    if server_instance is not None:
        server_instance.shutdown()
        server_instance.server_close()
        server_instance = None
        log("Tile Server: Stopped.")

# Slippy map utilities for coordinate to tile calculation
def latlon_to_tile(lat, lon, zoom):
    import math
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return xtile, ytile

def download_area_task(bounds, progress_callback, finished_callback, is_cancelled_fn=None):
    """
    Downloads tiles within bounds for zoom levels 13 to 18.
    bounds: dict matching Leaflet LatLngBounds structure
    progress_callback: takes (current, total)
    finished_callback: takes (downloaded_count, skipped_count, success)
    is_cancelled_fn: optional function returning boolean to abort the task
    """
    try:
        sw = bounds['_southWest']
        ne = bounds['_northEast']
        
        min_lat = min(sw['lat'], ne['lat'])
        max_lat = max(sw['lat'], ne['lat'])
        min_lon = min(sw['lng'], ne['lng'])
        max_lon = max(sw['lng'], ne['lng'])
        
        tiles = []
        for zoom in range(13, 19): # zoom levels 13 to 18 (inclusive)
            x1, y1 = latlon_to_tile(max_lat, min_lon, zoom)
            x2, y2 = latlon_to_tile(min_lat, max_lon, zoom)
            
            n = 2.0 ** zoom
            min_x = max(0, min(x1, x2))
            max_x = min(int(n - 1), max(x1, x2))
            min_y = max(0, min(y1, y2))
            max_y = min(int(n - 1), max(y1, y2))
            
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    tiles.append((zoom, x, y))
                    
        total = len(tiles)
        if total == 0:
            finished_callback(0, 0, True)
            return
            
        log(f"Offline Map: Downloading {total} tiles for zoom 13-18...")
        downloaded = 0
        skipped = 0
        
        for idx, (zoom, x, y) in enumerate(tiles):
            if is_cancelled_fn and is_cancelled_fn():
                log("Offline Map Downloader: Cancelled by user.")
                finished_callback(downloaded - skipped, skipped, False)
                return
                
            # Safe caching path
            cache_path = os.path.abspath(os.path.join(tile_cache_dir, str(zoom), str(x), f"{y}.png"))
            if not cache_path.startswith(os.path.abspath(tile_cache_dir)):
                continue
                
            # Skip if already cached
            if os.path.exists(cache_path):
                skipped += 1
                downloaded += 1
                if idx % 10 == 0 or idx == total - 1:
                    progress_callback(downloaded, total)
                continue
                
            # Fetch OSM tile
            url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
            try:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                req = urllib.request.Request(
                    url,
                    headers={'User-Agent': 'PythonGCS/1.0 (harryzhou935@gmail.com; Offline Map Downloader)'}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    tile_data = response.read()
                with open(cache_path, 'wb') as f:
                    f.write(tile_data)
                
                downloaded += 1
                progress_callback(downloaded, total)
                
                # Throttled download (150ms sleep)
                time.sleep(0.15)
            except Exception as e:
                log(f"Offline Map Downloader Error at tile {zoom}/{x}/{y}: {e}")
                downloaded += 1
                progress_callback(downloaded, total)
                
        finished_callback(total - skipped, skipped, True)
    except Exception as e:
        log(f"Offline Map Downloader Task Exception: {e}")
        finished_callback(0, 0, False)
