import logging

from photocatalog import config, logging_setup


def test_setup_logging_creates_log_file_and_writes_to_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "logs" / "photocatalog.log")
    monkeypatch.setattr(logging_setup, "_configured", False)

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        logging_setup.setup_logging()
        logger = logging.getLogger("photocatalog.test")
        logger.info("hello from the test")

        for handler in root.handlers:
            handler.flush()

        assert config.LOG_FILE.exists()
        content = config.LOG_FILE.read_text()
        assert "hello from the test" in content
    finally:
        for handler in list(root.handlers):
            if handler not in original_handlers:
                root.removeHandler(handler)
                handler.close()
        logging_setup._configured = False


def test_setup_logging_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "logs" / "photocatalog.log")
    monkeypatch.setattr(logging_setup, "_configured", False)

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        logging_setup.setup_logging()
        handlers_after_first = len(root.handlers)
        logging_setup.setup_logging()
        assert len(root.handlers) == handlers_after_first
    finally:
        for handler in list(root.handlers):
            if handler not in original_handlers:
                root.removeHandler(handler)
                handler.close()
        logging_setup._configured = False
