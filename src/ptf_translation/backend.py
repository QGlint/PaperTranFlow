"""翻译后端抽象（TranslationBackend）。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class TranslationBackend(ABC):
    """翻译后端接口。第一版只实现 GLM，但接口独立以便未来扩展。"""

    @abstractmethod
    def translate(self, text: str, target_lang: str = "简体中文") -> str:
        """把一段 Markdown 文本翻译为目标语言，返回译文。"""
        raise NotImplementedError
