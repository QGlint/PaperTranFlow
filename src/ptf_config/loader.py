"""统一配置加载（ConfigLoader）。

组合 UserConfigLocator + CredentialLoader + 可选 TOML 增强，
产出 PaperTranFlowConfig。
"""
from __future__ import annotations

import os
from pathlib import Path

from .credentials import CredentialLoader
from .locator import UserConfigLocator
from .models import (
    ChunkingConfig,
    GLMConfig,
    ImageHostConfig,
    MinerUConfig,
    OutputConfig,
    PaperTranFlowConfig,
    TranslationConfig,
)

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # pragma: no cover
    try:
        import tomli as _toml
    except ImportError:  # pragma: no cover
        _toml = None


def _load_toml(path: Path) -> dict:
    if _toml is None or not path.is_file():
        return {}
    try:
        with open(path, "rb") as f:
            return _toml.load(f)
    except Exception:
        return {}


class ConfigLoader:
    def __init__(self, cwd: Path | None = None):
        self._locator = UserConfigLocator(cwd=cwd)
        self._config_dir = self._locator.locate()
        self._credentials = CredentialLoader(self._config_dir)

    @property
    def config_dir(self) -> str:
        return str(self._config_dir) if self._config_dir else ""

    def load(self) -> PaperTranFlowConfig:
        toml = self._load_user_toml()

        mineru = MinerUConfig(
            token=self._credentials.load_mineru_token(),
            base_url=self._toml_str(toml, "mineru", "base_url", "https://mineru.net/api/v4"),
            model_version=self._toml_str(toml, "mineru", "model_version", "vlm"),
            enable_formula=self._toml_bool(toml, "mineru", "enable_formula", True),
            language=self._toml_str(toml, "mineru", "language", "en"),
        )

        glm = GLMConfig(
            api_key=self._credentials.load_glm_key(),
            base_url=self._toml_str(
                toml, "glm", "base_url", "https://open.bigmodel.cn/api/paas/v4"
            ),
            model=self._toml_str(toml, "glm", "model", "glm-4.7-flash"),
            temperature=self._toml_float(toml, "glm", "temperature", 0.7),
            top_p=self._toml_float(toml, "glm", "top_p", 0.9),
        )

        translation = TranslationConfig(
            concurrency=self._toml_int(toml, "translation", "concurrency", 1),
            max_retries=self._toml_int(toml, "translation", "max_retries", 2),
            backoff_base=self._toml_float(toml, "translation", "backoff_base", 2.0),
            target_lang=self._toml_str(toml, "translation", "target_lang", "简体中文"),
            request_interval=self._toml_float(toml, "translation", "request_interval", 3.0),
        )

        chunking = ChunkingConfig(
            target=self._toml_int(toml, "chunking", "target", 5000),
            hard_limit=self._toml_int(toml, "chunking", "hard_limit", 6500),
        )

        output = OutputConfig(
            zh_suffix=self._toml_str(toml, "output", "zh_suffix", ".zh.md"),
        )

        # 图床配置：从 CfImage.json 读取，默认关闭
        cf_base, cf_token = self._credentials.load_image_host()
        image_host = ImageHostConfig(
            base_url=cf_base,
            token=cf_token,
            enabled=self._toml_bool(toml, "image_host", "enabled", False),
        )

        return PaperTranFlowConfig(
            mineru=mineru,
            glm=glm,
            translation=translation,
            chunking=chunking,
            output=output,
            image_host=image_host,
            config_dir=self.config_dir,
        )

    def _load_user_toml(self) -> dict:
        if self._config_dir is None:
            return {}
        # 兼容现有 /config/user/ 目录结构：user.toml 放在 config/ 下，
        # 也允许 config/user/user.toml。
        candidates = [
            self._config_dir / "user.toml",
            self._config_dir / "user" / "user.toml",
        ]
        for c in candidates:
            data = _load_toml(c)
            if data:
                return data
        return {}

    # ---- TOML 取值辅助 ----

    @staticmethod
    def _section(toml: dict, name: str) -> dict:
        v = toml.get(name, {})
        return v if isinstance(v, dict) else {}

    @classmethod
    def _toml_str(cls, toml: dict, section: str, key: str, default: str) -> str:
        v = cls._section(toml, section).get(key, default)
        return str(v) if v is not None else default

    @classmethod
    def _toml_bool(cls, toml: dict, section: str, key: str, default: bool) -> bool:
        v = cls._section(toml, section).get(key)
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes", "on")

    @classmethod
    def _toml_int(cls, toml: dict, section: str, key: str, default: int) -> int:
        v = cls._section(toml, section).get(key)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _toml_float(cls, toml: dict, section: str, key: str, default: float) -> float:
        v = cls._section(toml, section).get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
