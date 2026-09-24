"""Config 相关测试。"""
import sys
import os
from pathlib import Path

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_config.credentials import CredentialLoader, mask_secret
from ptf_config.loader import ConfigLoader
from ptf_config.models import PaperTranFlowConfig


def _tmp_config(tmp_path, mineru_token="tok-mineru", glm_key="key-glm"):
    user = tmp_path / "user"
    user.mkdir(parents=True)
    (user / "MirerU").write_text(mineru_token, encoding="utf-8")
    (user / "GLM").write_text(glm_key, encoding="utf-8")
    return tmp_path


def test_credential_loader_reads_token_files(tmp_path):
    cfg_dir = _tmp_config(tmp_path)
    loader = CredentialLoader(cfg_dir)
    assert loader.load_mineru_token() == "tok-mineru"
    assert loader.load_glm_key() == "key-glm"


def test_credential_loader_case_insensitive(tmp_path):
    user = tmp_path / "user"
    user.mkdir(parents=True)
    (user / "mineru").write_text("case-insensitive", encoding="utf-8")
    loader = CredentialLoader(tmp_path)
    assert loader.load_mineru_token() == "case-insensitive"


def test_credential_loader_env_override(tmp_path, monkeypatch):
    cfg_dir = _tmp_config(tmp_path)
    monkeypatch.setenv("PaperTranFlow_MINERU_TOKEN", "from-env")
    loader = CredentialLoader(cfg_dir)
    assert loader.load_mineru_token() == "from-env"


def test_mask_secret_never_reveals():
    out = mask_secret("sk-abcdef123456")
    assert "sk-abcdef" not in out
    assert "configured" in out


def test_config_loader_full(tmp_path, monkeypatch):
    cfg_dir = _tmp_config(tmp_path)
    monkeypatch.setenv("PaperTranFlow_CONFIG_DIR", str(cfg_dir))
    cfg = ConfigLoader(cwd=tmp_path).load()
    assert isinstance(cfg, PaperTranFlowConfig)
    assert cfg.mineru.token == "tok-mineru"
    assert cfg.glm.api_key == "key-glm"
    assert cfg.glm.model == "glm-4.7-flash"
    assert cfg.chunking.target == 5000
    assert cfg.chunking.hard_limit == 6500
