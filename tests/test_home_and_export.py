"""
Unit tests for home position stability, trajectory deduplication/outlier filtering,
and GeoJSON/KML flight path export.
"""
import os
import json
import tempfile
import time
import pytest
from unittest.mock import MagicMock
from gcs.telemetry import telemetry_data, handle_mavlink_message, reset_telemetry_data
from gcs.telemetry_logger import TelemetryLogger, haversine_distance

class FakeMsg:
    def __init__(self, msg_type, **kwargs):
        self._type = msg_type
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_type(self):
        return self._type

    def get_srcSystem(self):
        return 1

    def get_srcComponent(self):
        return 1


def test_home_position_stability():
    reset_telemetry_data()
    telemetry_data['sysid'] = 1
    telemetry_data['compid'] = 1

    # Receive HOME_POSITION from vehicle
    home_msg = FakeMsg('HOME_POSITION', latitude=473977420, longitude=85455940, altitude=488000)
    handle_mavlink_message(home_msg)

    assert telemetry_data['has_home'] is True
    assert abs(telemetry_data['home_lat'] - 47.397742) < 1e-6
    assert abs(telemetry_data['home_lon'] - 8.545594) < 1e-6
    assert abs(telemetry_data['home_alt'] - 488.0) < 1e-3

    # Subsequent drone movement (GLOBAL_POSITION_INT) must NOT change home position
    pos_msg = FakeMsg('GLOBAL_POSITION_INT', lat=473990000, lon=85470000, alt=500000, relative_alt=12000)
    handle_mavlink_message(pos_msg)

    # Drone current position moved
    assert abs(telemetry_data['lat'] - 47.399) < 1e-6
    # But Home remains fixed
    assert abs(telemetry_data['home_lat'] - 47.397742) < 1e-6
    assert abs(telemetry_data['home_lon'] - 8.545594) < 1e-6


def test_haversine_distance():
    # Distance between Zurich (47.3769, 8.5417) and Bern (46.9480, 7.4474) ~ 95 km
    dist = haversine_distance(47.3769, 8.5417, 46.9480, 7.4474)
    assert 94000 < dist < 96000


def test_trajectory_record_and_export():
    logger = TelemetryLogger()
    logger.clear_records()

    # Add 3 trajectory points
    now = time.time()
    logger.records.extend([
        {'timestamp': '2026-09-27T10:00:00', 'time_epoch': now, 'lat': 47.3977, 'lon': 8.5455, 'alt': 0.0},
        {'timestamp': '2026-09-27T10:00:05', 'time_epoch': now + 5, 'lat': 47.3980, 'lon': 8.5458, 'alt': 10.5},
        {'timestamp': '2026-09-27T10:00:10', 'time_epoch': now + 10, 'lat': 47.3985, 'lon': 8.5462, 'alt': 15.2},
    ])

    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tf:
        geojson_path = tf.name
    with tempfile.NamedTemporaryFile(suffix=".kml", delete=False) as tf:
        kml_path = tf.name

    try:
        # GeoJSON export test
        ok = logger.export_geojson(geojson_path)
        assert ok is True

        with open(geojson_path, 'r', encoding='utf-8') as f:
            gj = json.load(f)

        assert gj["type"] == "FeatureCollection"
        feature = gj["features"][0]
        assert feature["geometry"]["type"] == "LineString"
        coords = feature["geometry"]["coordinates"]
        assert len(coords) == 3
        # In GeoJSON coordinates are [lon, lat, alt]
        assert coords[0] == [8.5455, 47.3977, 0.0]
        assert coords[1] == [8.5458, 47.3980, 10.5]
        assert feature["properties"]["point_count"] == 3
        assert "relative_to_launch_home" in feature["properties"]["altitude_reference"]

        # KML export test
        ok = logger.export_kml(kml_path)
        assert ok is True

        with open(kml_path, 'r', encoding='utf-8') as f:
            kml_text = f.read()

        assert '<?xml version="1.0" encoding="UTF-8"?>' in kml_text
        assert '<kml xmlns="http://www.opengis.net/kml/2.2">' in kml_text
        assert '<LineString>' in kml_text
        assert '8.5455000,47.3977000,0.00' in kml_text
        assert '8.5462000,47.3985000,15.20' in kml_text
        assert '<altitudeMode>relativeToGround</altitudeMode>' in kml_text
    finally:
        if os.path.exists(geojson_path):
            os.remove(geojson_path)
        if os.path.exists(kml_path):
            os.remove(kml_path)
