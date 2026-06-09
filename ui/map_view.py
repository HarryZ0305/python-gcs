from PyQt6.QtWebEngineWidgets import QWebEngineView 

MAP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        body { margin: 0; padding: 0; }
        #map { width: 100%; height: 100vh; background: #0d1b2a; }
        #mode-controls {
            position: absolute;
            top: 10px;
            right: 10px;
            z-index: 1000;
            background: rgba(30, 45, 61, 0.9);
            padding: 8px;
            border-radius: 6px;
            border: 2px solid #2a4a6a;
            font-family: 'Courier New', monospace;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .mode-btn {
            background: none;
            border-radius: 4px;
            padding: 6px 12px;
            font-weight: bold;
            font-size: 11px;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        #btn-takeoff {
            border: 1.5px solid #44ff88;
            color: #44ff88;
        }
        #btn-waypoint {
            border: 1.5px solid #00e5ff;
            color: #00e5ff;
        }
        #btn-landing {
            border: 1.5px solid #ff4444;
            color: #ff4444;
        }
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
    <div id="map"></div>
    
    <div id="mode-controls">
        <button id="btn-takeoff" class="mode-btn" onclick="setMode('takeoff')">TAKEOFF MODE</button>
        <button id="btn-waypoint" class="mode-btn" onclick="setMode('waypoint')">WAYPOINT MODE</button>
        <button id="btn-landing" class="mode-btn" onclick="setMode('landing')">LANDING MODE</button>
    </div>

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

        // Mission states
        var currentMode = 'waypoint';
        var takeoffPoint = null;
        var takeoffMarker = null;
        var landingPoint = null;
        var landingMarker = null;
        var waypoints = [];
        var waypointMarkers = [];
        var missionPath = L.polyline([], {color: '#ffaa00', weight: 3, dashArray: '5, 5'}).addTo(map);

        // Initialize mode button UI
        setMode('waypoint');

        map.on('click', function(e) {
            var lat = e.latlng.lat;
            var lon = e.latlng.lng;
            if (currentMode === 'takeoff') {
                setTakeoff(lat, lon);
            } else if (currentMode === 'waypoint') {
                addWaypoint(lat, lon);
            } else if (currentMode === 'landing') {
                setLanding(lat, lon);
            }
        });

        function setMode(mode) {
            currentMode = mode;
            var takeoffBtn = document.getElementById('btn-takeoff');
            var waypointBtn = document.getElementById('btn-waypoint');
            var landingBtn = document.getElementById('btn-landing');
            
            // Reset button active styles to empty outline
            takeoffBtn.style.background = 'none';
            takeoffBtn.style.color = '#44ff88';
            waypointBtn.style.background = 'none';
            waypointBtn.style.color = '#00e5ff';
            landingBtn.style.background = 'none';
            landingBtn.style.color = '#ff4444';
            
            // Set active mode style
            if (mode === 'takeoff') {
                takeoffBtn.style.background = '#44ff88';
                takeoffBtn.style.color = '#0d1b2a';
            } else if (mode === 'waypoint') {
                waypointBtn.style.background = '#00e5ff';
                waypointBtn.style.color = '#0d1b2a';
            } else if (mode === 'landing') {
                landingBtn.style.background = '#ff4444';
                landingBtn.style.color = '#ffffff';
            }
        }

        function updateMissionPath() {
            var pts = [];
            if (takeoffPoint) {
                pts.push(takeoffPoint);
            }
            for (var i = 0; i < waypoints.length; i++) {
                pts.push(waypoints[i]);
            }
            if (landingPoint) {
                pts.push(landingPoint);
            }
            missionPath.setLatLngs(pts);
        }

        function setTakeoff(lat, lon) {
            var pos = [lat, lon];
            takeoffPoint = pos;
            if (takeoffMarker) {
                map.removeLayer(takeoffMarker);
            }
            var icon = L.divIcon({
                html: '<div style="width:20px;height:20px;background:#44ff88;border:2px solid white;border-radius:50%;box-shadow:0 0 8px #44ff88;text-align:center;color:#0d1b2a;font-size:11px;line-height:20px;font-weight:bold;">T</div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10],
                className: ''
            });
            takeoffMarker = L.marker(pos, {icon: icon}).addTo(map);
            updateMissionPath();
        }

        function setLanding(lat, lon) {
            var pos = [lat, lon];
            landingPoint = pos;
            if (landingMarker) {
                map.removeLayer(landingMarker);
            }
            var icon = L.divIcon({
                html: '<div style="width:20px;height:20px;background:#ff4444;border:2px solid white;border-radius:50%;box-shadow:0 0 8px #ff4444;text-align:center;color:#ffffff;font-size:11px;line-height:20px;font-weight:bold;">L</div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10],
                className: ''
            });
            landingMarker = L.marker(pos, {icon: icon}).addTo(map);
            updateMissionPath();
        }

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
            updateMissionPath();
        }

        function getWaypoints() {
            return {
                'takeoff': takeoffPoint,
                'waypoints': waypoints,
                'landing': landingPoint
            };
        }

        function clearWaypoints() {
            if (takeoffMarker) {
                map.removeLayer(takeoffMarker);
            }
            if (landingMarker) {
                map.removeLayer(landingMarker);
            }
            for (var i = 0; i < waypointMarkers.length; i++) {
                map.removeLayer(waypointMarkers[i]);
            }
            takeoffPoint = null;
            takeoffMarker = null;
            landingPoint = null;
            landingMarker = null;
            waypoints = [];
            waypointMarkers = [];
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