"""用户配置目录定位（UserConfigLocator）。

优先级：
1. 环境变量 PaperTranFlow_CONFIG_DIR
2. Windows: %APPDATA%/PaperTranFlow/config
3. 开发环境：仓库根 /config（兼容现有 /config/user/）
"""
from __future__ import annotations

import os
from pathlib import Path


class UserConfigLocator:
    """定位用户配置目录，不硬编码 Linux 的 /config/user/ 为唯一位置。"""

    def __init__(self, cwd: Path | None = None):
        self._cwd = Path(cwd) if cwd else Path.cwd()

    def candidates(self) -> list[Path]:
        result: list[Path] = []

        env_dir = os.environ.get("PaperTranFlow_CONFIG_DIR")
        if env_dir:
            result.append(Path(env_dir))

        appdata = os.environ.get("APPDATA")
        if appdata:
            result.append(Path(appdata) / "PaperTranFlow" / "config")

        # 开发环境：仓库根 /config（向上查找 pyproject.toml 或 .git）
        root = self._find_repo_root(self._cwd)
        if root:
            result.append(root / "config")

        return result

    def locate(self) -> Path | None:
        for candidate in self.candidates():
            if candidate.is_dir():
                return candidate
        return None

    @staticmethod
    def _find_repo_root(start: Path) -> Path | None:
        cur = start
        while True:
            if (cur / "pyproject.toml").exists() or (cur / ".git").exists():
                return cur
            if cur.parent == cur:
                return None
            cur = cur.parent
