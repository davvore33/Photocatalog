import importlib
import sys
import types

import photocatalog
from photocatalog import config

HEIF_EXTENSIONS = {".heic", ".heif"}


def _reload_with(monkeypatch, pillow_heif, extensions):
    monkeypatch.setitem(sys.modules, "pillow_heif", pillow_heif)
    monkeypatch.setattr(config, "SUPPORTED_EXTENSIONS", set(extensions))
    importlib.reload(photocatalog)


def test_heif_enabled_when_pillow_heif_is_installed(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(register_heif_opener=lambda: calls.append(True))

    _reload_with(monkeypatch, fake, config.SUPPORTED_EXTENSIONS - HEIF_EXTENSIONS)

    assert calls == [True]
    assert HEIF_EXTENSIONS <= config.SUPPORTED_EXTENSIONS


def test_heif_stays_disabled_without_pillow_heif(monkeypatch):
    _reload_with(monkeypatch, None, config.SUPPORTED_EXTENSIONS - HEIF_EXTENSIONS)  # None => ImportError

    assert not HEIF_EXTENSIONS & config.SUPPORTED_EXTENSIONS
