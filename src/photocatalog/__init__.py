__version__ = "0.1.0"

from . import config as _config

# HEIC/HEIF (iPhone photos) is opt-in via the `heic` extra: only when pillow-heif is
# installed do we teach Pillow to open it and let the scanner pick those files up.
try:
    import pillow_heif as _pillow_heif
except ImportError:
    pass
else:
    _pillow_heif.register_heif_opener()
    _config.SUPPORTED_EXTENSIONS |= {".heic", ".heif"}
