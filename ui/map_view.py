from PyQt6.QtWebEngineWidgets import QWebEngineView 

MAP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        body { margin: 0; padding: 0; }
        #map { width: 100%; height: 100vh; background: #0d1b2a; }
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([32.7157, -117.1611], 15);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);

        var droneIcon = L.divIcon({
            html: '<div style="width:16px;height:16px;background:#00e5ff;border:2px solid white;border-radius:50%;box-shadow:0 0 8px #00e5ff;"></div>',
            iconSize: [16, 16],
            iconAnchor: [8, 8],
            className: ''
        });

        var marker = L.marker([32.7157, -117.1611], {icon: droneIcon}).addTo(map);
        var path = L.polyline([], {color: '#00e5ff', weight: 2, opacity: 0.7}).addTo(map);
        var positions = [];

        function updateDrone(lat, lon) {
            var pos = [lat, lon];
            marker.setLatLng(pos);
            positions.push(pos);
            path.setLatLngs(positions);
            map.panTo(pos);
        }
    </script>
</body>
</html>
"""

class MapView(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setHtml(MAP_HTML)
        self._last_pos = (0.0, 0.0)

    def update_position(self, lat, lon):
        # Only update if position actually changed and GPS has a fix
        if (lat, lon) == self._last_pos or (lat == 0.0 and lon == 0.0):
            return
        self._last_pos = (lat, lon)
        self.page().runJavaScript(f"updateDrone({lat}, {lon});") # type: ignore