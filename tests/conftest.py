import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def radar_env(tmp_path, monkeypatch):
    """每个测试一个干净的数据目录和配置。"""
    monkeypatch.setenv("RADAR_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("RADAR_CONFIG", str(tmp_path / "config.json"))
    from radar import config, store

    importlib.reload(config)
    store._initialized.clear()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    cfg = config.load()
    cfg["telegram_channels"] = ["testcargo"]
    cfg["news_queries"] = [{"q": "Irkeshtam border", "lang": "en-US"}]
    config.save(cfg)
    return config
