import threading
from gcs.ui.gui import launch_gui
from gcs.ui.tile_server import start_server

if __name__ == '__main__':
    # Start offline tile cache server in background
    threading.Thread(target=start_server, daemon=True).start()
    # Launch main desktop GUI
    launch_gui()
