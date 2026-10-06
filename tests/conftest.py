import pytest

from photocatalog import config


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path_factory, monkeypatch):
    """Keep thumbnails and logs out of the real ~/.photocatalog."""
    data_dir = tmp_path_factory.mktemp("photocatalog-data")
    monkeypatch.setattr(config, "THUMBNAILS_DIR", data_dir / "thumbnails")
    monkeypatch.setattr(config, "LOG_DIR", data_dir / "logs")
    monkeypatch.setattr(config, "LOG_FILE", data_dir / "logs" / "photocatalog.log")
