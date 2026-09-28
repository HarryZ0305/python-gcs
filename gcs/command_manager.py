import time
import threading
from typing import Dict, Tuple, Optional
from gcs.logs import log

ACK_RESULT_NAMES = {
    0: 'ACCEPTED',
    1: 'TEMPORARILY_REJECTED',
    2: 'DENIED',
    3: 'UNSUPPORTED',
    4: 'FAILED',
    5: 'IN_PROGRESS',
    6: 'CANCELLED'
}

class PendingCommand:
    def __init__(self, command_id: int, target_system: int = 1, target_component: int = 1, timeout: float = 3.0):
        self.command_id = command_id
        self.target_system = target_system
        self.target_component = target_component
        self.timeout = timeout
        self.start_time = time.monotonic()
        self.event = threading.Event()
        self.result_code: Optional[int] = None
        self.result_str: str = 'TIMEOUT'
        self.progress: int = 0
        self.result_param2: int = 0

    def wait(self) -> Tuple[bool, str, Optional[int]]:
        remaining = max(0.1, self.timeout - (time.monotonic() - self.start_time))
        signaled = self.event.wait(timeout=remaining)
        if not signaled:
            self.result_str = f'TIMEOUT ({self.timeout}s)'
            self.result_code = None
            return False, self.result_str, None
        success = (self.result_code == 0)
        return success, self.result_str, self.result_code


class CommandManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Dict[Tuple[int, int, int], PendingCommand] = {}
        self._last_acks: Dict[int, dict] = {}

    def register(self, command_id: int, target_system: int = 1, target_component: int = 1, timeout: float = 3.0) -> PendingCommand:
        key = (command_id, target_system, target_component)
        pending = PendingCommand(command_id, target_system, target_component, timeout)
        with self._lock:
            # Clean up expired pending commands
            now = time.monotonic()
            expired = [k for k, v in self._pending.items() if (now - v.start_time) > v.timeout + 2.0]
            for k in expired:
                del self._pending[k]
            self._pending[key] = pending
        return pending

    def handle_ack(self, msg) -> Optional[PendingCommand]:
        cmd_id = getattr(msg, 'command', 0)
        result = getattr(msg, 'result', -1)
        src_sys = msg.get_srcSystem()
        src_comp = msg.get_srcComponent()
        progress = getattr(msg, 'progress', 0)
        result_param2 = getattr(msg, 'result_param2', 0)

        result_name = ACK_RESULT_NAMES.get(result, f'UNKNOWN({result})')
        log(f'COMMAND_ACK: Command {cmd_id} from sys {src_sys}:{src_comp} -> {result_name} (progress={progress})')

        key = (cmd_id, src_sys, src_comp)
        fallback_key = (cmd_id, 1, 1)

        target_pending = None
        with self._lock:
            self._last_acks[cmd_id] = {
                'result': result,
                'result_str': result_name,
                'progress': progress,
                'time': time.monotonic()
            }
            if key in self._pending:
                target_pending = self._pending[key]
            elif fallback_key in self._pending:
                target_pending = self._pending[fallback_key]
            else:
                # Find any pending with matching cmd_id
                for k, v in self._pending.items():
                    if k[0] == cmd_id:
                        target_pending = v
                        break

            if target_pending:
                target_pending.progress = progress
                target_pending.result_param2 = result_param2
                if result == 5: # IN_PROGRESS
                    # Keep waiting, do not complete yet
                    pass
                else:
                    target_pending.result_code = result
                    target_pending.result_str = result_name
                    target_pending.event.set()
                    # Remove from pending dictionary
                    keys_to_del = [k for k, v in self._pending.items() if v is target_pending]
                    for k in keys_to_del:
                        del self._pending[k]

        return target_pending

    def clear(self):
        with self._lock:
            for pending in self._pending.values():
                pending.result_str = 'CANCELLED'
                pending.event.set()
            self._pending.clear()
            self._last_acks.clear()

command_manager = CommandManager()
