import os
import csv
import json
import time
import math
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
from gcs.logs import log
from gcs.telemetry import telemetry_data

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance in meters between two lat/lon points."""
    R = 6371000.0 # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

class TelemetryLogger:
    def __init__(self):
        self.is_logging = False
        self.thread: Optional[threading.Thread] = None
        self.file_path: Optional[str] = None
        self.log_dir = os.path.join(os.path.expanduser("~"), ".python-gcs", "logs")
        self._lock = threading.Lock()
        self.records: List[Dict[str, Any]] = [] # Timestamped trajectory records
        self._last_logged_point = None

    def start(self):
        if self.is_logging:
            return
        
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.file_path = os.path.join(self.log_dir, f"flight_{timestamp}.csv")
            self.is_logging = True
            
            self.thread = threading.Thread(target=self._log_loop, daemon=True)
            self.thread.start()
            log(f"Telemetry logging started: {self.file_path}")
        except Exception as e:
            log(f"Telemetry logging start failed: {e}")

    def stop(self):
        self.is_logging = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
            self.thread = None
        log("Telemetry logging stopped.")

    def clear_records(self):
        with self._lock:
            self.records.clear()
            self._last_logged_point = None
        log("Trajectory trail records reset.")

    def get_records_snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.records)

    def _log_loop(self):
        headers = [
            "timestamp", "armed", "mode", "lat", "lon", "alt_rel", "alt_amsl",
            "groundspeed", "throttle", "battery", "voltage",
            "roll", "pitch", "yaw", "satellites", "fix_type"
        ]
        
        try:
            with open(self.file_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                f.flush()
                
                while self.is_logging:
                    armed = telemetry_data.get('armed', False)
                    lat = telemetry_data.get('lat', 0.0)
                    lon = telemetry_data.get('lon', 0.0)
                    alt_rel = telemetry_data.get('alt', 0.0)
                    alt_amsl = telemetry_data.get('alt_amsl', 0.0)
                    speed = telemetry_data.get('groundspeed', 0.0)
                    mode = telemetry_data.get('mode', 'UNKNOWN')

                    # Record trajectory point if position is valid
                    if lat != 0.0 and lon != 0.0:
                        should_record = False
                        with self._lock:
                            if not self.records:
                                should_record = True
                            else:
                                last = self.records[-1]
                                dist = haversine_distance(last['lat'], last['lon'], lat, lon)
                                # Filter out GPS glitches (impossible speed jump > 200m/s)
                                dt = max(0.1, time.time() - last['time_epoch'])
                                if dist / dt < 200.0:
                                    if dist >= 1.0 or dt >= 1.0:
                                        should_record = True

                            if should_record:
                                point_entry = {
                                    'timestamp': datetime.now().isoformat(),
                                    'time_epoch': time.time(),
                                    'lat': lat,
                                    'lon': lon,
                                    'alt': alt_rel,
                                    'alt_amsl': alt_amsl,
                                    'groundspeed': speed,
                                    'mode': mode,
                                    'armed': armed
                                }
                                self.records.append(point_entry)
                                # Cap in-memory records to 10,000 to prevent unbounded memory growth
                                if len(self.records) > 10000:
                                    self.records.pop(0)

                    # Write CSV row if armed or position valid
                    if armed or (lat != 0.0 and lon != 0.0):
                        row = {
                            "timestamp": datetime.now().isoformat(),
                            "armed": armed,
                            "mode": mode,
                            "lat": lat,
                            "lon": lon,
                            "alt_rel": alt_rel,
                            "alt_amsl": alt_amsl,
                            "groundspeed": speed,
                            "throttle": telemetry_data.get('throttle', 0),
                            "battery": telemetry_data.get('battery', -1),
                            "voltage": telemetry_data.get('voltage', 0.0),
                            "roll": telemetry_data.get('roll', 0.0),
                            "pitch": telemetry_data.get('pitch', 0.0),
                            "yaw": telemetry_data.get('yaw', 0.0),
                            "satellites": telemetry_data.get('satellites', 0),
                            "fix_type": telemetry_data.get('fix_type', 0)
                        }
                        writer.writerow(row)
                        f.flush()

                    time.sleep(1.0) # 1 Hz logging rate
        except Exception as e:
            log(f"Telemetry logging loop exception: {e}")

    def export_geojson(self, filename: str) -> bool:
        records = self.get_records_snapshot()
        if not records:
            if telemetry_data.get('lat', 0.0) != 0.0:
                records = [{
                    'lon': telemetry_data['lon'],
                    'lat': telemetry_data['lat'],
                    'alt': telemetry_data.get('alt', 0.0),
                    'timestamp': datetime.now().isoformat()
                }]
            else:
                return False

        coordinates = [[r['lon'], r['lat'], round(r.get('alt', 0.0), 2)] for r in records]
        
        geojson_data = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates
                },
                "properties": {
                    "name": "PythonGCS Flight Trail",
                    "point_count": len(coordinates),
                    "start_time": records[0].get('timestamp', ''),
                    "end_time": records[-1].get('timestamp', ''),
                    "altitude_reference": "relative_to_launch_home"
                }
            }]
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(geojson_data, f, indent=2)
        return True

    def export_kml(self, filename: str) -> bool:
        records = self.get_records_snapshot()
        if not records:
            if telemetry_data.get('lat', 0.0) != 0.0:
                records = [{
                    'lon': telemetry_data['lon'],
                    'lat': telemetry_data['lat'],
                    'alt': telemetry_data.get('alt', 0.0)
                }]
            else:
                return False

        coord_strings = [f"{r['lon']:.7f},{r['lat']:.7f},{r.get('alt', 0.0):.2f}" for r in records]
        coord_block = " ".join(coord_strings)

        kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>PythonGCS Flight Trail</name>
    <description>Recorded flight path. Altitude values are relative to launch point elevation.</description>
    <Style id="flightPathStyle">
      <LineStyle>
        <color>ff0055ff</color>
        <width>4</width>
      </LineStyle>
      <PolyStyle>
        <color>7f0055ff</color>
      </PolyStyle>
    </Style>
    <Placemark>
      <name>Flight Trajectory</name>
      <styleUrl>#flightPathStyle</styleUrl>
      <LineString>
        <extrude>1</extrude>
        <tessellate>1</tessellate>
        <altitudeMode>relativeToGround</altitudeMode>
        <coordinates>
          {coord_block}
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(kml_content)
        return True

logger_instance = TelemetryLogger()
