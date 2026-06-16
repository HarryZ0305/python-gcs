import os
import csv
import time
import threading
from datetime import datetime
from gcs.telemetry import telemetry_data

class TelemetryLogger:
    def __init__(self):
        self.is_logging = False
        self.thread = None
        self.file_path = None
        self.log_dir = os.path.join(os.path.expanduser("~"), ".python-gcs", "logs")

    def start(self):
        if self.is_logging:
            return
        
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.file_path = os.path.join(self.log_dir, f"flight_{timestamp}.csv")
        self.is_logging = True
        
        self.thread = threading.Thread(target=self._log_loop, daemon=True)
        self.thread.start()
        
        from gcs.logs import log
        log(f"Telemetry logging started: {self.file_path}")

    def stop(self):
        self.is_logging = False
        if self.thread:
            self.thread.join(timeout=1.0)
            
        from gcs.logs import log
        log("Telemetry logging stopped.")

    def _log_loop(self):
        headers = [
            "timestamp", "armed", "mode", "lat", "lon", "alt",
            "vx", "vy", "vz", "roll", "pitch", "yaw",
            "battery", "groundspeed", "satellites"
        ]
        
        with open(self.file_path, mode='w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            
            while self.is_logging:
                if telemetry_data.get('armed', False):
                    row = {
                        "timestamp": datetime.now().isoformat(),
                        "armed": telemetry_data.get('armed', False),
                        "mode": telemetry_data.get('mode', 'UNKNOWN'),
                        "lat": telemetry_data.get('lat', 0.0),
                        "lon": telemetry_data.get('lon', 0.0),
                        "alt": telemetry_data.get('alt', 0.0),
                        "vx": telemetry_data.get('vx', 0.0),
                        "vy": telemetry_data.get('vy', 0.0),
                        "vz": telemetry_data.get('vz', 0.0),
                        "roll": telemetry_data.get('roll', 0.0),
                        "pitch": telemetry_data.get('pitch', 0.0),
                        "yaw": telemetry_data.get('yaw', 0.0),
                        "battery": telemetry_data.get('battery', 0),
                        "groundspeed": telemetry_data.get('groundspeed', 0.0),
                        "satellites": telemetry_data.get('satellites', 0)
                    }
                    writer.writerow(row)
                    f.flush()
                time.sleep(1.0) # Log at 1 Hz

logger_instance = TelemetryLogger()
