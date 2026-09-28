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

class CommandAlreadyPendingError(RuntimeError):
    """Raised when an identical command is already pending for the target vehicle."""
    pass

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

    def is_active(self) -> bool:
        if self.event.is_set():
            return False
        return (time.monotonic() - self.start_time) < self.timeout

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
        self._last_acks: Dict[Tuple[int, int, int], dict] = {}

    def register(self, command_id: int, target_system: int = 1, target_component: int = 1, timeout: float = 3.0) -> PendingCommand:
        """
        Registers a pending command for the exact (command_id, target_system, target_component).
        Rejects concurrent identical commands if one is already active.
        """
        key = (command_id, target_system, target_component)
        with self._lock:
            now = time.monotonic()
            # Clean up expired pending commands
            expired = [k for k, v in self._pending.items() if (now - v.start_time) > v.timeout + 1.0]
            for k in expired:
                del self._pending[k]

            existing = self._pending.get(key)
            if existing is not None and existing.is_active():
                raise CommandAlreadyPendingError(
                    f"Command {command_id} already active for target {target_system}:{target_component}"
                )

            pending = PendingCommand(command_id, target_system, target_component, timeout)
            self._pending[key] = pending
            return pending

    def handle_ack(self, msg) -> Optional[PendingCommand]:
        """
        Routes COMMAND_ACK strictly to the exact (cmd_id, src_sys, src_comp) pending command.
        Does NOT accept ACKs from wrong systems or components.
        """
        cmd_id = getattr(msg, 'command', 0)
        result = getattr(msg, 'result', -1)
        src_sys = msg.get_srcSystem()
        src_comp = msg.get_srcComponent()
        progress = getattr(msg, 'progress', 0)
        result_param2 = getattr(msg, 'result_param2', 0)

        result_name = ACK_RESULT_NAMES.get(result, f'UNKNOWN({result})')
        log(f'COMMAND_ACK: Command {cmd_id} from sys {src_sys}:{src_comp} -> {result_name} (progress={progress})')

        key = (cmd_id, src_sys, src_comp)

        with self._lock:
            self._last_acks[key] = {
                'result': result,
                'result_str': result_name,
                'progress': progress,
                'time': time.monotonic()
            }

            # Exact match ONLY: No fallback to default system or loose cmd_id
            target_pending = self._pending.get(key)

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
                    self._pending.pop(key, None)

            return target_pending

    def clear(self):
        with self._lock:
            for pending in self._pending.values():
                pending.result_str = 'CANCELLED'
                pending.event.set()
            self._pending.clear()
            self._last_acks.clear()

command_manager = CommandManager()
