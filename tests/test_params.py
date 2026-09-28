import pytest
import math
from gcs.params import (
    decode_param_value, encode_param_value, validate_param_value,
    create_param_backup_data, compare_params_for_restore,
    PARAM_TYPE_INT32, PARAM_TYPE_REAL32, PARAM_TYPE_UINT32,
    PARAM_TYPE_INT16, PARAM_TYPE_UINT16, PARAM_TYPE_INT8, PARAM_TYPE_UINT8
)

def test_int32_parameter_round_trip():
    test_values = [0, 1, -1, 42, -42, 1000, -1000, 2147483647, -2147483648, 4001, -1043333120]
    for val in test_values:
        wire_float = encode_param_value(val, PARAM_TYPE_INT32)
        decoded = decode_param_value(wire_float, PARAM_TYPE_INT32)
        assert decoded == val, f"INT32 round trip failed for {val}: got {decoded}"

def test_real32_parameter_round_trip():
    test_values = [0.0, 1.0, -1.0, 12.375, -5.5, 0.0001, 1000.5, 3.14159]
    for val in test_values:
        wire_float = encode_param_value(val, PARAM_TYPE_REAL32)
        decoded = decode_param_value(wire_float, PARAM_TYPE_REAL32)
        assert abs(decoded - val) < 1e-5, f"REAL32 round trip failed for {val}: got {decoded}"

def test_parameter_nan_inf_rejection():
    with pytest.raises(ValueError):
        encode_param_value(float('nan'), PARAM_TYPE_REAL32)
    with pytest.raises(ValueError):
        encode_param_value(float('inf'), PARAM_TYPE_REAL32)

    assert decode_param_value(float('nan'), PARAM_TYPE_REAL32) is None
    assert decode_param_value(float('inf'), PARAM_TYPE_REAL32) is None

def test_validate_param_value():
    # INT32
    ok, val, err = validate_param_value("4001", PARAM_TYPE_INT32)
    assert ok and val == 4001
    ok, val, err = validate_param_value("-42", PARAM_TYPE_INT32)
    assert ok and val == -42
    ok, val, err = validate_param_value("9999999999999999", PARAM_TYPE_INT32)
    assert not ok and "range" in err
    ok, val, err = validate_param_value("abc", PARAM_TYPE_INT32)
    assert not ok and "Invalid" in err

    # REAL32
    ok, val, err = validate_param_value("12.5", PARAM_TYPE_REAL32)
    assert ok and abs(val - 12.5) < 1e-5
    ok, val, err = validate_param_value("nan", PARAM_TYPE_REAL32)
    assert not ok

def test_parameter_backup_and_restore_comparison():
    current_params = {
        "SYS_AUTOSTART": {"value": 4001, "type": PARAM_TYPE_INT32},
        "MPC_XY_VEL_MAX": {"value": 12.0, "type": PARAM_TYPE_REAL32},
        "COM_ARM_WO_GPS": {"value": 0, "type": PARAM_TYPE_INT32}
    }
    
    backup = create_param_backup_data(current_params, {"system_id": 1, "component_id": 1, "autopilot": "PX4"})
    assert backup['format'] == "PythonGCS_Param_Backup"
    assert backup['count'] == 3
    assert backup['parameters']['SYS_AUTOSTART']['value'] == 4001

    # Compare for restore
    imported = {
        "SYS_AUTOSTART": {"value": 4001, "type": PARAM_TYPE_INT32}, # UNCHANGED
        "MPC_XY_VEL_MAX": {"value": 15.0, "type": PARAM_TYPE_REAL32}, # UPDATE
        "UNKNOWN_PARAM": {"value": 1.0, "type": PARAM_TYPE_REAL32}, # UNKNOWN_SKIP
        "COM_ARM_WO_GPS": {"value": 1.0, "type": PARAM_TYPE_REAL32} # TYPE_MISMATCH_SKIP (INT32 vs REAL32)
    }

    diffs = compare_params_for_restore(current_params, imported)
    actions = {d['name']: d['action'] for d in diffs}
    assert actions['SYS_AUTOSTART'] == 'UNCHANGED'
    assert actions['MPC_XY_VEL_MAX'] == 'UPDATE'
    assert actions['UNKNOWN_PARAM'] == 'UNKNOWN_SKIP'
    assert actions['COM_ARM_WO_GPS'] == 'TYPE_MISMATCH_SKIP'
