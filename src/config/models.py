"""配置数据模型（dataclass）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MinerUConfig:
    token: str = ""
    base_url: str = "https://mineru.net/api/v4"
    model_version: str = "vlm"
    enable_formula: bool = True
    language: str = "en"
    # 轮询间隔（秒）与最大等待（秒）
    poll_interval: float = 3.0
    poll_timeout: float = 3600.0
    connect_timeout: float = 5.0
    read_timeout: float = 600.0
    write_timeout: float = 600.0

    @property
    def configured(self) -> bool:
        return bool(self.token)


@dataclass
class GLMConfig:
    api_key: str = ""
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-4.7-flash"
    temperature: float = 0.7
    top_p: float = 0.9
    connect_timeout: float = 5.0
    read_timeout: float = 600.0
    write_timeout: float = 300.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class TranslationConfig:
    concurrency: int = 1
    max_retries: int = 3
    backoff_base: float = 2.0
    target_lang: str = "简体中文"


@dataclass
class ChunkingConfig:
    target: int = 5000
    hard_limit: int = 6500


@dataclass
class OutputConfig:
    zh_suffix: str = ".zh.md"


@dataclass
class PaperFlowConfig:
    mineru: MinerUConfig = field(default_factory=MinerUConfig)
    glm: GLMConfig = field(default_factory=GLMConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    # 实际定位到的配置目录（供诊断）
    config_dir: str = ""
