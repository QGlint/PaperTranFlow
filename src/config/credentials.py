"""凭据读取（CredentialLoader）。

兼容现有 /config/user/ 的「纯 token 文件」格式：
    <config_dir>/user/MirerU   -> MinerU API token
    <config_dir>/user/GLM      -> GLM API key
"""
from __future__ import annotations

import os
from pathlib import Path

# 文件名大小写不敏感；兼容历史拼写 "MirerU" / "MinerU"
_MINERU_NAMES = ("mireru", "mineru")
_GLM_NAMES = ("glm",)


def _read_first_line(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    return text.splitlines()[0].strip() if text else ""


def _find_case_insensitive(directory: Path, names: tuple[str, ...]) -> Path | None:
    if not directory.is_dir():
        return None
    lowered = {p.name.lower(): p for p in directory.iterdir() if p.is_file()}
    for name in names:
        if name in lowered:
            return lowered[name]
    return None


class CredentialLoader:
    """从用户配置目录读取 MinerU / GLM 凭据。

    显式环境变量优先，其次纯 token 文件。
    """

    MINERU_TOKEN_ENV = "PAPERFLOW_MINERU_TOKEN"
    GLM_KEY_ENV = "PAPERFLOW_GLM_KEY"

    def __init__(self, config_dir: Path | None):
        self._config_dir = config_dir

    def _user_dir(self) -> Path | None:
        if self._config_dir is None:
            return None
        return self._config_dir / "user"

    def load_mineru_token(self) -> str:
        env = os.environ.get(self.MINERU_TOKEN_ENV, "").strip()
        if env:
            return env
        user_dir = self._user_dir()
        if user_dir:
            f = _find_case_insensitive(user_dir, _MINERU_NAMES)
            if f:
                return _read_first_line(f)
        return ""

    def load_glm_key(self) -> str:
        env = os.environ.get(self.GLM_KEY_ENV, "").strip()
        if env:
            return env
        user_dir = self._user_dir()
        if user_dir:
            f = _find_case_insensitive(user_dir, _GLM_NAMES)
            if f:
                return _read_first_line(f)
        return ""


def mask_secret(secret: str) -> str:
    """脱敏：只显示长度，不显示内容。"""
    if not secret:
        return "(empty)"
    return f"<configured, {len(secret)} chars>"
