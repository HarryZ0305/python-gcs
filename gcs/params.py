import struct
import math
from typing import Tuple, Union, Optional, Dict, Any, List

PARAM_TYPE_UINT8 = 1
PARAM_TYPE_INT8 = 2
PARAM_TYPE_UINT16 = 3
PARAM_TYPE_INT16 = 4
PARAM_TYPE_UINT32 = 5
PARAM_TYPE_INT32 = 6
PARAM_TYPE_REAL32 = 9

PARAM_TYPE_NAMES = {
    PARAM_TYPE_UINT8: 'UINT8',
    PARAM_TYPE_INT8: 'INT8',
    PARAM_TYPE_UINT16: 'UINT16',
    PARAM_TYPE_INT16: 'INT16',
    PARAM_TYPE_UINT32: 'UINT32',
    PARAM_TYPE_INT32: 'INT32',
    PARAM_TYPE_REAL32: 'REAL32',
}

def decode_param_value(wire_float: float, param_type: int) -> Union[int, float, None]:
    try:
        raw_bytes = struct.pack('<f', wire_float)
    except Exception:
        return None

    if param_type == PARAM_TYPE_INT32:
        return struct.unpack('<i', raw_bytes)[0]
    elif param_type == PARAM_TYPE_UINT32:
        return struct.unpack('<I', raw_bytes)[0]
    elif param_type == PARAM_TYPE_INT16:
        return struct.unpack('<h', raw_bytes[:2])[0]
    elif param_type == PARAM_TYPE_UINT16:
        return struct.unpack('<H', raw_bytes[:2])[0]
    elif param_type == PARAM_TYPE_INT8:
        return struct.unpack('<b', raw_bytes[:1])[0]
    elif param_type == PARAM_TYPE_UINT8:
        return struct.unpack('<B', raw_bytes[:1])[0]
    elif param_type == PARAM_TYPE_REAL32:
        if math.isnan(wire_float) or math.isinf(wire_float):
            return None
        return float(wire_float)
    else:
        if math.isnan(wire_float) or math.isinf(wire_float):
            return None
        return float(wire_float)

def encode_param_value(value: Union[int, float], param_type: int) -> float:
    if param_type == PARAM_TYPE_INT32:
        int_val = int(value)
        int_val = max(-2147483648, min(2147483647, int_val))
        return struct.unpack('<f', struct.pack('<i', int_val))[0]
    elif param_type == PARAM_TYPE_UINT32:
        uint_val = int(value)
        uint_val = max(0, min(4294967295, uint_val))
        return struct.unpack('<f', struct.pack('<I', uint_val))[0]
    elif param_type == PARAM_TYPE_INT16:
        int_val = max(-32768, min(32767, int(value)))
        return struct.unpack('<f', struct.pack('<i', int_val))[0]
    elif param_type == PARAM_TYPE_UINT16:
        uint_val = max(0, min(65535, int(value)))
        return struct.unpack('<f', struct.pack('<I', uint_val))[0]
    elif param_type == PARAM_TYPE_INT8:
        int_val = max(-128, min(127, int(value)))
        return struct.unpack('<f', struct.pack('<i', int_val))[0]
    elif param_type == PARAM_TYPE_UINT8:
        uint_val = max(0, min(255, int(value)))
        return struct.unpack('<f', struct.pack('<I', uint_val))[0]
    elif param_type == PARAM_TYPE_REAL32:
        f_val = float(value)
        if math.isnan(f_val) or math.isinf(f_val):
            raise ValueError('Parameter value cannot be NaN or Infinite')
        return f_val
    else:
        return float(value)

def validate_param_value(val_str: str, param_type: int) -> Tuple[bool, Optional[Union[int, float]], str]:
    val_str = val_str.strip()
    if not val_str:
        return False, None, 'Empty value'
    
    try:
        if param_type in (PARAM_TYPE_INT32, PARAM_TYPE_INT16, PARAM_TYPE_INT8):
            val = int(val_str)
            if param_type == PARAM_TYPE_INT32 and not (-2147483648 <= val <= 2147483647):
                return False, None, 'Value out of INT32 range (-2147483648 to 2147483647)'
            elif param_type == PARAM_TYPE_INT16 and not (-32768 <= val <= 32767):
                return False, None, 'Value out of INT16 range (-32768 to 32767)'
            elif param_type == PARAM_TYPE_INT8 and not (-128 <= val <= 127):
                return False, None, 'Value out of INT8 range (-128 to 127)'
            return True, val, ''
        elif param_type in (PARAM_TYPE_UINT32, PARAM_TYPE_UINT16, PARAM_TYPE_UINT8):
            val = int(val_str)
            if param_type == PARAM_TYPE_UINT32 and not (0 <= val <= 4294967295):
                return False, None, 'Value out of UINT32 range (0 to 4294967295)'
            elif param_type == PARAM_TYPE_UINT16 and not (0 <= val <= 65535):
                return False, None, 'Value out of UINT16 range (0 to 65535)'
            elif param_type == PARAM_TYPE_UINT8 and not (0 <= val <= 255):
                return False, None, 'Value out of UINT8 range (0 to 255)'
            return True, val, ''
        elif param_type == PARAM_TYPE_REAL32:
            val = float(val_str)
            if math.isnan(val) or math.isinf(val):
                return False, None, 'Value cannot be NaN or Infinite'
            return True, val, ''
        else:
            try:
                val = int(val_str)
                return True, val, ''
            except ValueError:
                val = float(val_str)
                if math.isnan(val) or math.isinf(val):
                    return False, None, 'Value cannot be NaN or Infinite'
                return True, val, ''
    except ValueError as e:
        return False, None, f'Invalid number format: {e}'

def create_param_backup_data(parameters_data: Dict[str, dict], vehicle_info: Optional[dict] = None) -> dict:
    from datetime import datetime
    params_export = {}
    for name, meta in sorted(parameters_data.items()):
        p_type = meta.get('type', PARAM_TYPE_REAL32)
        params_export[name] = {
            'value': meta.get('value'),
            'type': p_type,
            'type_name': PARAM_TYPE_NAMES.get(p_type, f'TYPE_{p_type}')
        }
    return {
        'format': 'PythonGCS_Param_Backup',
        'version': '1.0',
        'timestamp': datetime.now().isoformat(),
        'vehicle': vehicle_info or {'system_id': 1, 'component_id': 1, 'autopilot': 'PX4'},
        'count': len(params_export),
        'parameters': params_export
    }

def compare_params_for_restore(
    current_params: Dict[str, dict], 
    imported_data: Union[dict, list]
) -> List[dict]:
    diffs = []
    
    # Handle both structured backup format and flat {name: val} format
    if isinstance(imported_data, dict) and 'parameters' in imported_data:
        items_to_check = imported_data['parameters']
    elif isinstance(imported_data, dict):
        items_to_check = imported_data
    else:
        return diffs

    for name, incoming in items_to_check.items():
        if isinstance(incoming, dict):
            new_val = incoming.get('value')
            new_type = incoming.get('type')
        else:
            new_val = incoming
            new_type = None

        if name not in current_params:
            diffs.append({
                'name': name,
                'current_value': None,
                'target_value': new_val,
                'type': new_type or PARAM_TYPE_REAL32,
                'action': 'UNKNOWN_SKIP',
                'description': 'Parameter not present on current vehicle'
            })
            continue

        curr_meta = current_params[name]
        curr_val = curr_meta.get('value')
        curr_type = curr_meta.get('type', PARAM_TYPE_REAL32)

        # Check type compatibility if incoming type specified
        if new_type is not None and new_type != curr_type:
            diffs.append({
                'name': name,
                'current_value': curr_val,
                'target_value': new_val,
                'type': curr_type,
                'action': 'TYPE_MISMATCH_SKIP',
                'description': f'Type mismatch: FCU expects {PARAM_TYPE_NAMES.get(curr_type)}, file has {PARAM_TYPE_NAMES.get(new_type)}'
            })
            continue

        # Check value change
        val_changed = False
        if curr_type in (PARAM_TYPE_INT32, PARAM_TYPE_UINT32, PARAM_TYPE_INT16, PARAM_TYPE_UINT16, PARAM_TYPE_INT8, PARAM_TYPE_UINT8):
            val_changed = int(curr_val) != int(new_val)
        else:
            val_changed = abs(float(curr_val) - float(new_val)) > 1e-6

        if val_changed:
            diffs.append({
                'name': name,
                'current_value': curr_val,
                'target_value': new_val,
                'type': curr_type,
                'action': 'UPDATE',
                'description': f'{curr_val} -> {new_val}'
            })
        else:
            diffs.append({
                'name': name,
                'current_value': curr_val,
                'target_value': new_val,
                'type': curr_type,
                'action': 'UNCHANGED',
                'description': 'Identical value'
            })

    return diffs
