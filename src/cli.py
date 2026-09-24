"""PaperFlow CLI。

职责：参数解析、配置加载、启动 Job、显示进度/日志、返回退出码。
不包含业务逻辑（业务在 core/pipeline.py）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pf_config.credentials import mask_secret
from pf_config.loader import ConfigLoader
from pf_core.events import EventType
from pf_core.pipeline import Pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paperflow",
        description="本地 CLI 优先的文档解析、Markdown 标准化与文档翻译工具。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("parse", help="PDF -> MinerU -> Markdown (+ content_list.json)").add_argument(
        "input", help="输入 PDF 路径"
    )
    sub.add_parser("translate", help="Markdown -> 中文 Markdown").add_argument(
        "input", help="输入 Markdown 路径"
    )
    sub.add_parser("run", help="完整 pipeline（parse + translate）").add_argument(
        "input", help="输入 PDF 路径"
    )
    sub.add_parser("resume", help="从 checkpoint 续跑").add_argument(
        "input", help="输入 Markdown 路径"
    )
    config_sub = sub.add_parser("config", help="配置相关命令")
    config_sub_sub = config_sub.add_subparsers(dest="config_command", required=True)
    config_sub_sub.add_parser("check", help="检查 MinerU/GLM 配置")

    parser.add_argument("--job-dir", help="job 工作目录（默认 .paperflow/jobs/<name>）")
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    return parser


def _make_emitter():
    def emit(event: EventType, data: dict) -> None:
        if event == EventType.JOB_STARTED:
            print(f"[START] {data.get('path', '')}")
        elif event == EventType.MINERU_SUBMITTED:
            print("[MINERU] 已提交解析任务…")
        elif event == EventType.MINERU_COMPLETED:
            print(f"[MINERU] 完成 -> {data.get('path', '')}")
        elif event == EventType.NORMALIZATION_STARTED:
            print("[NORMALIZE] 开始标准化…")
        elif event == EventType.NORMALIZATION_COMPLETED:
            print(f"[NORMALIZE] 完成（{data.get('blocks', 0)} blocks）")
        elif event == EventType.CHUNKING_COMPLETED:
            print(f"[CHUNK] 完成（{data.get('chunks', 0)} chunks）")
        elif event == EventType.TRANSLATION_STARTED:
            print(f"[TRANSLATE] 开始翻译（{data.get('chunks', 0)} chunks）")
        elif event == EventType.CHUNK_COMPLETED:
            cid = data.get("chunk_id", "")
            if data.get("resumed"):
                print(f"  [chunk] {cid} 跳过（已缓存）")
            elif data.get("started"):
                print(f"  [chunk] {cid} 翻译中…")
            else:
                print(f"  [chunk] {cid} 完成")
        elif event == EventType.JOB_COMPLETED:
            print(f"[DONE] 输出 -> {data.get('path', '')}")
        elif event == EventType.JOB_FAILED:
            print(f"[FAILED] {data.get('error', '')}")

    return emit


def _cmd_config_check() -> int:
    loader = ConfigLoader()
    cfg = loader.load()
    print(f"Config dir: {cfg.config_dir or '(未找到)'}")
    print(f"MinerU: {'configured' if cfg.mineru.configured else 'not configured'}"
          f"  {mask_secret(cfg.mineru.token)}")
    print(f"GLM:    {'configured' if cfg.glm.configured else 'not configured'}"
          f"  {mask_secret(cfg.glm.api_key)}")
    print(f"GLM model: {cfg.glm.model}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "config" and args.config_command == "check":
        return _cmd_config_check()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"错误：文件不存在 -> {input_path}", file=sys.stderr)
        return 2

    cfg = ConfigLoader().load()
    job_dir = Path(args.job_dir) if args.job_dir else None

    if args.command == "parse":
        if not cfg.mineru.configured:
            print("错误：MinerU 未配置（请检查 /config/user/MirerU）", file=sys.stderr)
            return 3
        pipeline = Pipeline(cfg, emit=_make_emitter())
        try:
            result_md, _ = pipeline.parse(input_path, job_dir)
            print(f"解析完成：{result_md}")
            return 0
        except Exception as e:
            print(f"错误：{e}", file=sys.stderr)
            return 1

    if args.command in ("translate", "run", "resume"):
        if args.command in ("translate", "resume") and not cfg.glm.configured:
            print("错误：GLM 未配置（请检查 /config/user/GLM）", file=sys.stderr)
            return 3
        if args.command == "run" and not cfg.mineru.configured:
            print("错误：MinerU 未配置（请检查 /config/user/MirerU）", file=sys.stderr)
            return 3
        pipeline = Pipeline(cfg, emit=_make_emitter())
        try:
            if args.command == "run":
                out = pipeline.run(input_path, job_dir)
            elif args.command == "resume":
                out = pipeline.resume(input_path, job_dir)
            else:
                out = pipeline.translate(input_path, job_dir)
            print(f"翻译完成：{out}")
            return 0
        except Exception as e:
            print(f"错误：{e}", file=sys.stderr)
            return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
