from datetime import datetime

log_messages = []  # shared buffer the GUI console reads from

def log(msg):
    """Add a timestamped message to the shared log buffer (and terminal)."""
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    log_messages.append(entry)
    print(entry)