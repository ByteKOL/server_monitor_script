# logger_config.py
import logging
from logging.handlers import RotatingFileHandler
try:
    from .. import config  # package mode
except Exception:
    import config  # direct/path mode

def setup_logger():
    """
    Setup a logger that writes to both console and rotating file.
    """
    logger = logging.getLogger("monitor_logger")
    logger.setLevel(logging.INFO)

    # Rotating file handler, max 5MB per file, keep 3 backups
    file_handler = RotatingFileHandler(config.logfile, maxBytes=5*1024*1024, backupCount=3)
    file_handler.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Log format
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# Create global logger instance
logger = setup_logger()
