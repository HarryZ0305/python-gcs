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

        var waypoints = [];
        var waypointMarkers = [];
        var missionPath = L.polyline([], {color: '#ffaa00', weight: 3, dashArray: '5, 5'}).addTo(map);

        map.on('click', function(e) {
            var lat = e.latlng.lat;
            var lon = e.latlng.lng;
            addWaypoint(lat, lon);
        });

        function addWaypoint(lat, lon) {
            var pos = [lat, lon];
            waypoints.push(pos);
            var num = waypoints.length;
            var icon = L.divIcon({
                html: '<div style="width:18px;height:18px;background:#ffaa00;border:2px solid white;border-radius:50%;box-shadow:0 0 6px rgba(0,0,0,0.5);text-align:center;color:#0d1b2a;font-size:11px;line-height:18px;font-weight:bold;">' + num + '</div>',
                iconSize: [18, 18],
                iconAnchor: [9, 9],
                className: ''
            });
            var m = L.marker(pos, {icon: icon}).addTo(map);
            waypointMarkers.push(m);
            missionPath.setLatLngs(waypoints);
        }

        function getWaypoints() {
            return waypoints;
        }

        function clearWaypoints() {
            for (var i = 0; i < waypointMarkers.length; i++) {
                map.removeLayer(waypointMarkers[i]);
            }
            waypointMarkers = [];
            waypoints = [];
            missionPath.setLatLngs([]);
        }

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
        self._is_loaded = False
        self.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok):
        if ok:
            self._is_loaded = True
            # If we received a position while loading, send it now
            if self._last_pos != (0.0, 0.0):
                lat, lon = self._last_pos
                self.page().runJavaScript(f"if (typeof updateDrone === 'function') updateDrone({lat}, {lon});")

    def update_position(self, lat, lon):
        # Only update if position actually changed and GPS has a fix
        if (lat, lon) == self._last_pos or (lat == 0.0 and lon == 0.0):
            return
        self._last_pos = (lat, lon)
        if self._is_loaded:
            self.page().runJavaScript(f"if (typeof updateDrone === 'function') updateDrone({lat}, {lon});")

    def get_waypoints(self, callback):
        self.page().runJavaScript("if (typeof getWaypoints === 'function') getWaypoints();", callback)

    def clear_waypoints(self):
        self.page().runJavaScript("if (typeof clearWaypoints === 'function') clearWaypoints();")