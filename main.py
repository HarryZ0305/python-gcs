import threading
from gcs.ui.gui import launch_gui     
from gcs.ui.tile_server import start_tile_server
from gcs.telemetry_logger import logger_instance

if __name__ == '__main__':
    threading.Thread(target=start_tile_server, daemon=True).start()
    logger_instance.start()
    launch_gui()