import sys
import os
import time
from PyQt6.QtWidgets import QApplication

# Ensure repo root is on sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from gcs.ui.gui import GCSWindow
from gcs.telemetry import telemetry_data, reset_telemetry_data

output_dir = r"C:\Users\harry\.gemini\antigravity-ide\brain\528a5af1-8ae7-4fb5-b72c-0c4ecefeaef2"
os.makedirs(output_dir, exist_ok=True)

app = QApplication(sys.argv)

win = GCSWindow()
win.resize(1920, 1080)
win.show()

app.processEvents()
time.sleep(0.5)

# 1. Disconnected State
win.refresh()
win._fast_instrument_update()
app.processEvents()
win.grab().save(os.path.join(output_dir, "screen_disconnected.png"))
print("Saved screen_disconnected.png")

# 2. Ready State (Connected, 3D Fix, Disarmed)
now = time.monotonic()
win.vehicle = object() # Simulated active link
telemetry_data['connected'] = True
telemetry_data['last_heartbeat_monotonic'] = now
telemetry_data['last_gps_monotonic'] = now
telemetry_data['last_attitude_monotonic'] = now
telemetry_data['last_battery_monotonic'] = now
telemetry_data['fix_type'] = 3
telemetry_data['satellites'] = 14
telemetry_data['lat'] = 47.397742
telemetry_data['lon'] = 8.545594
telemetry_data['alt'] = 0.0
telemetry_data['groundspeed'] = 0.0
telemetry_data['battery'] = 98
telemetry_data['battery_voltage'] = 16.4
telemetry_data['mode'] = "MANUAL"
telemetry_data['armed'] = False
win.refresh()
win._fast_instrument_update()
app.processEvents()
time.sleep(0.5)
win.grab().save(os.path.join(output_dir, "screen_ready.png"))
print("Saved screen_ready.png")

# 3. Flying State (Hold mode, Airborne, PFD active, altitude 18.5m, speed 5.2m/s)
telemetry_data['armed'] = True
telemetry_data['mode'] = "HOLD"
telemetry_data['alt'] = 18.5
telemetry_data['groundspeed'] = 5.2
telemetry_data['climb_rate'] = 0.8
telemetry_data['pitch'] = 6.5
telemetry_data['roll'] = -12.0
telemetry_data['yaw'] = 85.0
telemetry_data['battery'] = 84
telemetry_data['battery_voltage'] = 15.6
win.tabs.setCurrentIndex(0) # Fly workspace
win.refresh()
win._fast_instrument_update()
app.processEvents()
time.sleep(0.5)
win.grab().save(os.path.join(output_dir, "screen_flying.png"))
print("Saved screen_flying.png")

# 4. Planning Workspace
win.tabs.setCurrentIndex(1) # Plan tab
if hasattr(win, 'plan_view'):
    pv = win.plan_view
    pv.waypoints.clear()
    pv.add_waypoint(47.3980, 8.5460, 20.0)
    pv.add_waypoint(47.3995, 8.5475, 25.0)
    pv.add_waypoint(47.3985, 8.5490, 20.0)
    pv.takeoff_point = [47.3977, 8.5455, 15.0]
    pv.landing_point = [47.3977, 8.5455, 0.0]
    pv._sync_all()
app.processEvents()
time.sleep(0.5)
win.grab().save(os.path.join(output_dir, "screen_planning.png"))
print("Saved screen_planning.png")

# 5. Degraded / Stale Telemetry State
win.tabs.setCurrentIndex(0) # Back to Fly tab
# Heartbeat fresh, but GPS and attitude stale (>10s old)
telemetry_data['last_heartbeat_monotonic'] = time.monotonic()
telemetry_data['last_gps_monotonic'] = time.monotonic() - 15.0
telemetry_data['last_attitude_monotonic'] = time.monotonic() - 12.0
win.refresh()
win._fast_instrument_update()
app.processEvents()
time.sleep(0.5)
win.grab().save(os.path.join(output_dir, "screen_degraded.png"))
print("Saved screen_degraded.png")

# 6. Responsive 1366x768 verification
win.tabs.setCurrentIndex(0) # Fly tab
win.resize(1366, 768)
app.processEvents()
time.sleep(0.5)
win.grab().save(os.path.join(output_dir, "screen_1366x768.png"))
print("Saved screen_1366x768.png", flush=True)

# 7. Analyze Workspace
win.resize(1920, 1080)
win.tabs.setCurrentIndex(3) # Analyze tab
app.processEvents()
time.sleep(0.5)
win.grab().save(os.path.join(output_dir, "screen_analyze.png"))
print("Saved screen_analyze.png", flush=True)

# 8. Vehicle Setup Workspace
win.tabs.setCurrentIndex(2) # Setup tab
app.processEvents()
time.sleep(0.5)
win.grab().save(os.path.join(output_dir, "screen_setup.png"))
print("Saved screen_setup.png", flush=True)

# 9. Settings Workspace
win.tabs.setCurrentIndex(4) # Settings tab
app.processEvents()
time.sleep(0.5)
win.grab().save(os.path.join(output_dir, "screen_settings.png"))
print("Saved screen_settings.png", flush=True)

win.close()
print("All screenshots captured successfully.", flush=True)
os._exit(0)
