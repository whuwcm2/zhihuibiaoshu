from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from zhibiao.bid_writer import write_bid
from zhibiao.config import PROJECT_ROOT, get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.cli", description="标书生成工具")
    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write", help="根据解析后的招标文件生成投标文件")
    write.add_argument("doc_id", help="已解析并抽取的文档 ID")
    write.add_argument(
        "--profile",
        type=Path,
        default=PROJECT_ROOT / "bidder_profile.json",
        help="投标人资料 JSON（默认 bidder_profile.json）",
    )
    write.add_argument("--output-dir", type=Path, default=None, help="产物输出目录")
    write.add_argument("--no-docx", action="store_true", help="只生成 Markdown，不导出 Word")

    prompts = sub.add_parser("prompts", help="LangSmith Prompt Hub 管理")
    prompts_sub = prompts.add_subparsers(dest="prompts_command", required=True)
    prompts_sub.add_parser("push", help="推送本地提示词到 LangSmith Prompt Hub")

    sub.add_parser(
        "sync-documents", help="把 data/parsed 下的现有文档一次性同步到 PostgreSQL"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prompts":
            return _push_prompts()
        if args.command == "sync-documents":
            return _sync_documents()
        write_bid(
            doc_id=args.doc_id,
            settings=get_settings(),
            profile_path=args.profile,
            output_dir=args.output_dir,
            export_docx=not args.no_docx,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 统一转换为退出码
        print(f"错误: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


def _sync_documents() -> int:
    from zhibiao.db import create_engine, create_session_factory
    from zhibiao.document_store import backfill_documents

    settings = get_settings()
    if not settings.database_url:
        print("错误: DATABASE_URL 未配置", file=sys.stderr, flush=True)
        return 1

    async def run() -> int:
        engine = create_engine(settings)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                return await backfill_documents(session, settings)
        finally:
            await engine.dispose()

    count = asyncio.run(run())
    print(f"已同步 {count} 个文档到数据库", flush=True)
    return 0


def _push_prompts() -> int:
    from zhibiao.prompts import push_prompts

    results = push_prompts()
    failed = 0
    for name, status in results.items():
        print(f"{name}: {status}")
        if status.startswith("ERROR"):
            failed += 1
    if failed:
        print(f"{failed} 个提示词推送失败", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
