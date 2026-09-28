"""图床三级目录（folderName）测试。"""
import os
import sys
from pathlib import Path

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_config.models import PaperTranFlowConfig
from ptf_core.pipeline import Pipeline


def _pipeline(category="", sub_category=""):
    cfg = PaperTranFlowConfig()
    cfg.image_host.category = category
    cfg.image_host.sub_category = sub_category
    return Pipeline(cfg)


def _md(tmp_path):
    md = tmp_path / "Riedijk和Huijsing - 1991 - An integrated absolute temperature sensor with digital output.md"
    md.write_text("# Title\n\nbody\n", encoding="utf-8")
    return md


def test_folder_name_three_levels_with_sub_category(tmp_path):
    md = _md(tmp_path)
    p = _pipeline(category="paper", sub_category="Sensor")
    name = p._batch_folder_name(md)
    assert name == "paper/Sensor/An integrated absolute temperature sensor with digital output"


def test_folder_name_three_levels_no_sub_category(tmp_path):
    md = _md(tmp_path)
    p = _pipeline(category="paper")
    name = p._batch_folder_name(md)
    assert name == "paper/An integrated absolute temperature sensor with digital output"


def test_folder_name_auto_category(tmp_path):
    md = _md(tmp_path)
    p = _pipeline()  # category 未指定 -> 自动判断 paper
    name = p._batch_folder_name(md)
    assert name.startswith("paper/")


def test_folder_name_uses_english_title_not_heading(tmp_path):
    """第三级用去作者的英文文件名，而非 markdown 里的中文标题。"""
    md = _md(tmp_path)
    md.write_text("# 集成绝对温度传感器\n\nbody\n", encoding="utf-8")
    p = _pipeline(category="paper")
    name = p._batch_folder_name(md)
    # 应为英文标题，不含中文
    assert name == "paper/An integrated absolute temperature sensor with digital output"


def test_folder_name_manual_category(tmp_path):
    md = tmp_path / "LTC2991 - datasheet.pdf".replace(".pdf", ".md")
    md.write_text("body\n", encoding="utf-8")
    p = _pipeline()  # 自动判断 -> Manual
    name = p._batch_folder_name(md)
    assert name.split("/")[0] == "Manual"
