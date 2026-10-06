from pathlib import Path

DATA_DIR = Path.home() / ".photocatalog"
DEFAULT_DB_PATH = DATA_DIR / "catalog.db"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "photocatalog.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_VISION_MODEL = "qwen3-vl:8b"
VISION_TIMEOUT_SECONDS = 600
VISION_MAX_RETRIES = 2

# Longest side of the JPEG sent to the vision model, and its quality.
VISION_IMAGE_MAX_DIMENSION = 896
VISION_IMAGE_QUALITY = 85

THUMBNAIL_SIZE = (320, 320)

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff",
    # RAW formats: handled via their embedded JPEG preview, not full demosaicing.
    ".arw", ".cr2", ".cr3", ".nef", ".raf",
}

DEFAULT_PAGE_SIZE = 60
