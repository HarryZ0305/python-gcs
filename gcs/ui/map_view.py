import json
import math
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView

MAP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        @font-face {
            font-family: 'Google Sans Code';
            src: url('http://localhost:PORT_PLACEHOLDER/static/fonts/GoogleSansCode-Regular.ttf') format('truetype');
        }
        * { box-sizing: border-box; }
        body { margin: 0; padding: 0; background: #f5f7fa; font-family: 'Google Sans Code', monospace; }
        #map { width: 100%; height: 100vh; background: #f5f7fa; }

        /* Floating Mission Controls (Top Right) */
        #mode-controls {
            position: absolute;
            top: 12px;
            right: 12px;
            z-index: 1000;
            background: rgba(255, 255, 255, 0.95);
            padding: 8px;
            border-radius: 8px;
            border: 1px solid #cbd5e1;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
            color: #0f172a;
            display: flex;
            flex-direction: column;
            gap: 6px;
            min-width: 140px;
        }
        .panel-label {
            font-size: 10px;
            font-weight: bold;
            color: #5f6368;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 2px;
        }
        .mode-btn {
            background: #ffffff;
            border-radius: 5px;
            padding: 6px 10px;
            font-weight: bold;
            font-size: 11px;
            font-family: 'Google Sans Code', monospace;
            cursor: pointer;
            transition: all 0.15s ease;
            text-align: center;
        }
        #btn-takeoff { border: 1.5px solid #0f9d58; color: #0f9d58; }
        #btn-waypoint { border: 1.5px solid #0b57d0; color: #0b57d0; }
        #btn-landing { border: 1.5px solid #d93025; color: #d93025; }
        #btn-goto { border: 1.5px solid #8b5cf6; color: #8b5cf6; }

        /* Floating Map Tools (Left / Top-Left) */
        #map-tools {
            position: absolute;
            top: 12px;
            left: 12px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .tool-bar {
            background: rgba(255, 255, 255, 0.95);
            padding: 6px;
            border-radius: 8px;
            border: 1px solid #cbd5e1;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
            display: flex;
            gap: 6px;
        }
        .tool-btn {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 5px;
            padding: 5px 8px;
            font-size: 11px;
            font-weight: bold;
            font-family: 'Google Sans Code', monospace;
            cursor: pointer;
            color: #0f172a;
            display: flex;
            align-items: center;
            gap: 4px;
            transition: all 0.15s ease;
        }
        .tool-btn:hover {
            background: #f1f5f9;
            border-color: #94a3b8;
        }
        .tool-btn.active {
            background: #0b57d0;
            border-color: #0b57d0;
            color: #ffffff;
        }

        /* Map HUD Overlay */
        #map-hud {
            background: rgba(15, 23, 42, 0.88);
            backdrop-filter: blur(8px);
            color: #ffffff;
            padding: 8px 12px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            font-size: 11px;
            line-height: 1.5;
            display: flex;
            gap: 14px;
        }
        .hud-item {
            display: flex;
            flex-direction: column;
        }
        .hud-item span.label {
            font-size: 9px;
            color: #94a3b8;
            text-transform: uppercase;
            font-weight: 600;
        }
        .hud-item span.val {
            font-weight: bold;
            color: #38bdf8;
            font-size: 12px;
        }

        /* Drone SVG Icon Container */
        .drone-marker-container {
            width: 36px;
            height: 36px;
            position: relative;
            transform-origin: center center;
            transition: transform 0.15s ease-out;
        }
        .drone-svg {
            width: 36px;
            height: 36px;
            filter: drop-shadow(0 2px 5px rgba(0,0,0,0.4));
        }

        /* Go-To Target Pulse Marker */
        @keyframes pulse-ring {
            0% { transform: scale(0.6); opacity: 1; }
            100% { transform: scale(1.8); opacity: 0; }
        }
        .goto-pulse-container {
            width: 30px;
            height: 30px;
            position: relative;
        }
        .goto-pulse {
            position: absolute;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: rgba(139, 92, 246, 0.4);
            border: 2px solid #8b5cf6;
            animation: pulse-ring 1.5s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
        }
        .goto-center {
            position: absolute;
            top: 7px;
            left: 7px;
            width: 16px;
            height: 16px;
            background: #8b5cf6;
            border: 2px solid #ffffff;
            border-radius: 50%;
            box-shadow: 0 0 8px #8b5cf6;
        }
    </style>
    <link rel="stylesheet" href="http://localhost:PORT_PLACEHOLDER/static/leaflet.css"/>
    <script src="http://localhost:PORT_PLACEHOLDER/static/leaflet.js"></script>
</head>
<body>
    <div id="map"></div>

    <!-- Map Tools (Left / Top-Left) -->
    <div id="map-tools">
        <div class="tool-bar">
            <button id="btn-center" class="tool-btn" onclick="centerDrone()" title="Center on Drone">
                &#9678; CENTER
            </button>
            <button id="btn-follow" class="tool-btn active" onclick="toggleFollow()" title="Auto-Follow Drone">
                &#128274; FOLLOW: ON
            </button>
            <button id="btn-clear-trail" class="tool-btn" onclick="clearTrail()" title="Clear Flight Path Trail">
                &#129529; CLEAR TRAIL
            </button>
        </div>
        <div id="map-hud">
            <div class="hud-item">
                <span class="label">Dist to Home</span>
                <span id="hud-home-dist" class="val">--- m</span>
            </div>
            <div class="hud-item">
                <span class="label">Speed</span>
                <span id="hud-speed" class="val">0.0 m/s</span>
            </div>
            <div class="hud-item">
                <span class="label">Alt (AGL)</span>
                <span id="hud-alt" class="val">0.0 m</span>
            </div>
            <div class="hud-item">
                <span class="label">Heading</span>
                <span id="hud-heading" class="val">000&deg;</span>
            </div>
        </div>
    </div>

    <!-- Mode Controls (Top-Right) -->
    <div id="mode-controls">
        <div class="panel-label">Mission Planner</div>
        <button id="btn-takeoff" class="mode-btn" onclick="setMode('takeoff')">TAKEOFF</button>
        <button id="btn-waypoint" class="mode-btn" onclick="setMode('waypoint')">WAYPOINT</button>
        <button id="btn-landing" class="mode-btn" onclick="setMode('landing')">LANDING</button>
        <div class="panel-label" style="margin-top: 4px;">Guided Flight</div>
        <button id="btn-goto" class="mode-btn" onclick="setMode('goto')">FLY TO HERE</button>
    </div>

    <script>
        var map = L.map('map', { zoomControl: true }).setView([32.7157, -117.1611], 16);

        L.tileLayer('http://localhost:PORT_PLACEHOLDER/tiles/{z}/{x}/{y}.png', {
            attribution: 'OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(map);

        // Drone Icon with Directional Quadcopter SVG
        function createDroneIcon(headingDeg) {
            return L.divIcon({
                html: '<div id="drone-container" class="drone-marker-container" style="transform: rotate(' + headingDeg + 'deg);">' +
                      '<svg class="drone-svg" viewBox="0 0 100 100">' +
                      '  <circle cx="50" cy="50" r="20" fill="#0b57d0" stroke="#ffffff" stroke-width="4"/>' +
                      '  <polygon points="50,14 42,28 58,28" fill="#38bdf8" stroke="#ffffff" stroke-width="1.5"/>' +
                      '  <line x1="22" y1="22" x2="78" y2="78" stroke="#475569" stroke-width="4" stroke-linecap="round"/>' +
                      '  <line x1="78" y1="22" x2="22" y2="78" stroke="#475569" stroke-width="4" stroke-linecap="round"/>' +
                      '  <circle cx="22" cy="22" r="8" fill="#0f9d58" stroke="#ffffff" stroke-width="2"/>' +
                      '  <circle cx="78" cy="22" r="8" fill="#0f9d58" stroke="#ffffff" stroke-width="2"/>' +
                      '  <circle cx="22" cy="78" r="8" fill="#d93025" stroke="#ffffff" stroke-width="2"/>' +
                      '  <circle cx="78" cy="78" r="8" fill="#d93025" stroke="#ffffff" stroke-width="2"/>' +
                      '</svg></div>',
                iconSize: [36, 36],
                iconAnchor: [18, 18],
                className: ''
            });
        }

        var currentHeading = 0.0;
        var marker = L.marker([32.7157, -117.1611], { icon: createDroneIcon(0) }).addTo(map);
        var path = L.polyline([], { color: '#0b57d0', weight: 2.5, opacity: 0.85 }).addTo(map);
        var positions = [];
        var followDrone = true;

        // Home Position
        var homePoint = null;
        var homeMarker = null;
        var homeLine = L.polyline([], { color: '#64748b', weight: 1.5, dashArray: '4, 6', opacity: 0.7 }).addTo(map);

        // Go-To Target Marker
        var gotoMarker = null;

        // Mission states
        var currentMode = 'waypoint';
        var takeoffPoint = null;
        var takeoffMarker = null;
        var landingPoint = null;
        var landingMarker = null;
        var waypoints = [];
        var waypointMarkers = [];
        var missionPath = L.polyline([], { color: '#e37400', weight: 3, dashArray: '6, 6' }).addTo(map);
        var activeMarkerHighlight = null;

        setMode('waypoint');

        // Haversine distance calculator in meters
        function calculateDistance(lat1, lon1, lat2, lon2) {
            var R = 6371e3; // Earth radius in meters
            var p1 = lat1 * Math.PI / 180;
            var p2 = lat2 * Math.PI / 180;
            var dp = (lat2 - lat1) * Math.PI / 180;
            var dl = (lon2 - lon1) * Math.PI / 180;
            var a = Math.sin(dp/2) * Math.sin(dp/2) +
                    Math.cos(p1) * Math.cos(p2) *
                    Math.sin(dl/2) * Math.sin(dl/2);
            var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
        }

        // Map Click Dispatcher
        map.on('click', function(e) {
            var lat = e.latlng.lat;
            var lon = e.latlng.lng;
            if (currentMode === 'takeoff') {
                setTakeoff(lat, lon);
            } else if (currentMode === 'waypoint') {
                addWaypoint(lat, lon);
            } else if (currentMode === 'landing') {
                setLanding(lat, lon);
            } else if (currentMode === 'goto') {
                setGoToTarget(lat, lon);
            }
        });

        function setMode(mode) {
            currentMode = mode;
            var takeoffBtn = document.getElementById('btn-takeoff');
            var waypointBtn = document.getElementById('btn-waypoint');
            var landingBtn = document.getElementById('btn-landing');
            var gotoBtn = document.getElementById('btn-goto');

            takeoffBtn.style.background = '#ffffff'; takeoffBtn.style.color = '#0f9d58';
            waypointBtn.style.background = '#ffffff'; waypointBtn.style.color = '#0b57d0';
            landingBtn.style.background = '#ffffff'; landingBtn.style.color = '#d93025';
            gotoBtn.style.background = '#ffffff'; gotoBtn.style.color = '#8b5cf6';

            if (mode === 'takeoff') {
                takeoffBtn.style.background = '#0f9d58'; takeoffBtn.style.color = '#ffffff';
            } else if (mode === 'waypoint') {
                waypointBtn.style.background = '#0b57d0'; waypointBtn.style.color = '#ffffff';
            } else if (mode === 'landing') {
                landingBtn.style.background = '#d93025'; landingBtn.style.color = '#ffffff';
            } else if (mode === 'goto') {
                gotoBtn.style.background = '#8b5cf6'; gotoBtn.style.color = '#ffffff';
            }
        }

        function toggleFollow() {
            followDrone = !followDrone;
            var btn = document.getElementById('btn-follow');
            if (followDrone) {
                btn.classList.add('active');
                btn.innerHTML = '&#128274; FOLLOW: ON';
                centerDrone();
            } else {
                btn.classList.remove('active');
                btn.innerHTML = '&#128275; FOLLOW: OFF';
            }
        }

        function centerDrone() {
            var latlng = marker.getLatLng();
            map.panTo(latlng, { animate: true, duration: 0.5 });
        }

        function clearTrail() {
            positions = [];
            path.setLatLngs([]);
        }

        function setGoToTarget(lat, lon) {
            if (gotoMarker) {
                map.removeLayer(gotoMarker);
            }
            var icon = L.divIcon({
                html: '<div class="goto-pulse-container"><div class="goto-pulse"></div><div class="goto-center"></div></div>',
                iconSize: [30, 30],
                iconAnchor: [15, 15],
                className: ''
            });
            gotoMarker = L.marker([lat, lon], { icon: icon }).addTo(map);
            // Notify Python backend of Go-To coordinate selection
            document.title = 'ACTION:GOTO:' + lat + ':' + lon;
        }

        function setHome(lat, lon) {
            homePoint = [lat, lon];
            if (homeMarker) {
                map.removeLayer(homeMarker);
            }
            var homeIcon = L.divIcon({
                html: '<div style="width:22px;height:22px;background:#0f172a;border:2px solid #ffffff;border-radius:50%;box-shadow:0 0 8px rgba(0,0,0,0.5);text-align:center;color:#ffffff;font-size:11px;line-height:20px;font-weight:bold;">H</div>',
                iconSize: [22, 22],
                iconAnchor: [11, 11],
                className: ''
            });
            homeMarker = L.marker([lat, lon], { icon: homeIcon }).addTo(map);
            updateHomeLine();
        }

        function updateHomeLine() {
            if (!homePoint || !marker) return;
            var dronePos = marker.getLatLng();
            if (!dronePos) return;
            homeLine.setLatLngs([homePoint, [dronePos.lat, dronePos.lng]]);
            var dist = calculateDistance(dronePos.lat, dronePos.lng, homePoint[0], homePoint[1]);
            var hudDist = document.getElementById('hud-home-dist');
            if (hudDist) hudDist.textContent = dist.toFixed(1) + ' m';
        }

        function updateDrone(lat, lon, headingDeg, speed, alt) {
            var pos = [lat, lon];
            marker.setLatLng(pos);

            // Rotate drone icon
            if (headingDeg !== undefined && headingDeg !== null) {
                currentHeading = headingDeg;
                var el = document.getElementById('drone-container');
                if (el) {
                    el.style.transform = 'rotate(' + headingDeg + 'deg)';
                } else {
                    marker.setIcon(createDroneIcon(headingDeg));
                }
            }

            positions.push(pos);
            if (positions.length > 500) {
                positions.shift();
            }
            path.setLatLngs(positions);

            if (followDrone) {
                map.panTo(pos, { animate: false });
            }

            // Update HUD elements
            if (speed !== undefined) {
                document.getElementById('hud-speed').textContent = speed.toFixed(1) + ' m/s';
            }
            if (alt !== undefined) {
                document.getElementById('hud-alt').textContent = alt.toFixed(1) + ' m';
            }
            if (headingDeg !== undefined) {
                var degNorm = ((headingDeg % 360) + 360) % 360;
                document.getElementById('hud-heading').innerHTML = Math.round(degNorm) + '&deg;';
            }

            updateHomeLine();
        }

        function updateMissionPath() {
            var pts = [];
            if (takeoffPoint) pts.push(takeoffPoint);
            for (var i = 0; i < waypoints.length; i++) pts.push(waypoints[i]);
            if (landingPoint) pts.push(landingPoint);
            missionPath.setLatLngs(pts);
        }

        function setTakeoff(lat, lon) {
            var pos = [lat, lon];
            takeoffPoint = pos;
            if (takeoffMarker) map.removeLayer(takeoffMarker);
            var icon = L.divIcon({
                html: '<div style="width:20px;height:20px;background:#0f9d58;border:2px solid white;border-radius:50%;box-shadow:0 0 8px #0f9d58;text-align:center;color:#ffffff;font-size:11px;line-height:20px;font-weight:bold;">T</div>',
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
            if (landingMarker) map.removeLayer(landingMarker);
            var icon = L.divIcon({
                html: '<div style="width:20px;height:20px;background:#d93025;border:2px solid white;border-radius:50%;box-shadow:0 0 8px #d93025;text-align:center;color:#ffffff;font-size:11px;line-height:20px;font-weight:bold;">L</div>',
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
                html: '<div style="width:20px;height:20px;background:#e37400;border:2px solid white;border-radius:50%;box-shadow:0 0 6px rgba(0,0,0,0.5);text-align:center;color:#ffffff;font-size:11px;line-height:20px;font-weight:bold;">' + num + '</div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10],
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
            if (takeoffMarker) map.removeLayer(takeoffMarker);
            if (landingMarker) map.removeLayer(landingMarker);
            for (var i = 0; i < waypointMarkers.length; i++) {
                map.removeLayer(waypointMarkers[i]);
            }
            if (activeMarkerHighlight) map.removeLayer(activeMarkerHighlight);
            if (gotoMarker) map.removeLayer(gotoMarker);
            takeoffPoint = null;
            takeoffMarker = null;
            landingPoint = null;
            landingMarker = null;
            waypoints = [];
            waypointMarkers = [];
            activeMarkerHighlight = null;
            gotoMarker = null;
            missionPath.setLatLngs([]);
        }

        function setActiveWaypoint(seq) {
            if (activeMarkerHighlight) {
                map.removeLayer(activeMarkerHighlight);
                activeMarkerHighlight = null;
            }

            var targetMarker = null;
            var highlightColor = '#0b57d0';

            var hasTakeoff = (takeoffPoint !== null);
            var hasLanding = (landingPoint !== null);

            if (seq <= 0) return;

            if (hasTakeoff) {
                if (seq === 1) {
                    targetMarker = takeoffMarker;
                    highlightColor = '#0f9d58';
                } else if (seq > 1 && seq <= 1 + waypoints.length) {
                    targetMarker = waypointMarkers[seq - 2];
                    highlightColor = '#e37400';
                } else if (hasLanding && seq === 2 + waypoints.length) {
                    targetMarker = landingMarker;
                    highlightColor = '#d93025';
                }
            } else {
                if (seq >= 1 && seq <= waypoints.length) {
                    targetMarker = waypointMarkers[seq - 1];
                    highlightColor = '#e37400';
                } else if (hasLanding && seq === 1 + waypoints.length) {
                    targetMarker = landingMarker;
                    highlightColor = '#d93025';
                }
            }

            if (targetMarker) {
                var latlng = targetMarker.getLatLng();
                activeMarkerHighlight = L.circle(latlng, {
                    color: highlightColor,
                    fillColor: highlightColor,
                    fillOpacity: 0.2,
                    radius: 20,
                    weight: 2,
                    dashArray: '4, 4'
                }).addTo(map);
            }
        }

        function importMission(takeoff, wps, landing) {
            clearWaypoints();
            if (takeoff && takeoff.length === 2) setTakeoff(takeoff[0], takeoff[1]);
            if (wps && wps.length > 0) {
                for (var i = 0; i < wps.length; i++) addWaypoint(wps[i][0], wps[i][1]);
            }
            if (landing && landing.length === 2) setLanding(landing[0], landing[1]);
            var points = [];
            if (takeoffPoint) points.push(takeoffPoint);
            for (var i = 0; i < waypoints.length; i++) points.push(waypoints[i]);
            if (landingPoint) points.push(landingPoint);
            if (points.length > 0) map.fitBounds(points);
        }
    </script>
</body>
</html>
"""

class MapView(QWebEngineView):
    goto_requested = pyqtSignal(float, float)

    def __init__(self):
        super().__init__()
        from gcs.ui.tile_server import start_server
        port = start_server()
        local_html = MAP_HTML.replace("PORT_PLACEHOLDER", str(port))
        self.setHtml(local_html)
        self._last_pos = (0.0, 0.0)
        self._is_loaded = False
        self.loadFinished.connect(self._on_load_finished)
        self.titleChanged.connect(self._on_title_changed)

    def _on_load_finished(self, ok):
        if ok:
            self._is_loaded = True
            if self._last_pos != (0.0, 0.0):
                lat, lon = self._last_pos
                self.page().runJavaScript(f"if (typeof updateDrone === 'function') updateDrone({lat}, {lon}, 0, 0, 0);")

    def _on_title_changed(self, title):
        if title.startswith("ACTION:GOTO:"):
            parts = title.replace("ACTION:GOTO:", "").split(":")
            if len(parts) == 2:
                try:
                    lat = float(parts[0])
                    lon = float(parts[1])
                    self.goto_requested.emit(lat, lon)
                except ValueError:
                    pass

    def update_position(self, lat, lon, heading_deg=0.0, speed=0.0, alt=0.0):
        if (lat == 0.0 and lon == 0.0):
            return
        self._last_pos = (lat, lon)
        if self._is_loaded:
            self.page().runJavaScript(f"if (typeof updateDrone === 'function') updateDrone({lat}, {lon}, {heading_deg:.1f}, {speed:.1f}, {alt:.1f});")

    def set_mode(self, mode_name):
        if self._is_loaded:
            self.page().runJavaScript(f"if (typeof setMode === 'function') setMode('{mode_name}');")

    def set_home(self, lat, lon):
        if self._is_loaded and (lat != 0.0 or lon != 0.0):
            self.page().runJavaScript(f"if (typeof setHome === 'function') setHome({lat}, {lon});")

    def center_drone(self):
        if self._is_loaded:
            self.page().runJavaScript("if (typeof centerDrone === 'function') centerDrone();")

    def clear_trail(self):
        if self._is_loaded:
            self.page().runJavaScript("if (typeof clearTrail === 'function') clearTrail();")

    def get_waypoints(self, callback):
        self.page().runJavaScript("if (typeof getWaypoints === 'function') getWaypoints();", callback)

    def clear_waypoints(self):
        self.page().runJavaScript("if (typeof clearWaypoints === 'function') clearWaypoints();")

    def import_mission(self, takeoff, waypoints, landing):
        t_json = json.dumps(takeoff)
        w_json = json.dumps(waypoints)
        l_json = json.dumps(landing)
        self.page().runJavaScript(f"if (typeof importMission === 'function') importMission({t_json}, {w_json}, {l_json});")

    def get_map_bounds(self, callback):
        self.page().runJavaScript("if (typeof map !== 'undefined') JSON.stringify(map.getBounds()); else '';", callback)
