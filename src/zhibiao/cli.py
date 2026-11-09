from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .config import get_settings
from .extractor import extract_document
from .pipeline import ingest_pdf, search


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zhibiao", description="标书知识库管线")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="解析 PDF、分块、嵌入并写入 Chroma")
    ingest.add_argument("pdf", type=Path, help="待解析的 PDF 文件")
    ingest.add_argument(
        "--parser", choices=["auto", "mineru", "pymupdf"], default="auto",
        help="解析器：auto 优先 MinerU，失败回退 PyMuPDF",
    )
    ingest.add_argument("--reparse", action="store_true", help="忽略已缓存的解析结果")
    ingest.add_argument("--dry-run", action="store_true", help="只解析和分块，不调用 embedding")
    ingest.add_argument("--max-chars", type=int, default=None, help="片段最大字符数")
    ingest.add_argument("--overlap", type=int, default=None, help="相邻片段重叠字符数")
    ingest.add_argument("--collection", default=None, help="覆盖 Chroma collection 名称")

    search = sub.add_parser("search", help="语义检索已入库片段")
    search.add_argument("query", help="检索问题")
    search.add_argument("-n", "--n-results", type=int, default=5, help="返回条数")
    search.add_argument("--collection", default=None, help="覆盖 Chroma collection 名称")

    extract = sub.add_parser(
        "extract",
        help="结构化抽取项目概况、评标办法、前附表、资格审查、格式清单、时间节点",
    )
    extract.add_argument("pdf", type=Path, help="已入库的 PDF 文件")
    extract.add_argument("--output-dir", type=Path, default=None, help="输出目录（默认解析缓存目录）")
    extract.add_argument("--refresh", action="store_true", help="忽略抽取分片缓存，重新调用 LLM")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = get_settings()
        if getattr(args, "collection", None):
            settings = replace(settings, chroma_collection=args.collection)

        if args.command == "ingest":
            ingest_pdf(
                pdf_path=Path(args.pdf),
                settings=settings,
                parser=args.parser,
                reparse=args.reparse,
                max_chars=args.max_chars,
                overlap=args.overlap,
                dry_run=args.dry_run,
            )
        elif args.command == "search":
            search(args.query, settings, n_results=args.n_results)
        elif args.command == "extract":
            extract_document(
                Path(args.pdf), settings, output_dir=args.output_dir, refresh=args.refresh
            )
    except Exception as exc:  # noqa: BLE001 - CLI 统一转换为退出码
        print(f"错误: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
