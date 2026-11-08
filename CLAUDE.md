# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

`zhibiao`（README 名：zhihuibiaoshu）是一个标书制作项目。当前已实现招标文件的知识库管线：PDF 经 MinerU 云端精准解析（失败时回退 PyMuPDF）转为 Markdown，按章节分块后用智谱 `embedding-3` 嵌入，写入 Chroma 向量库，供后续多 Agent 编写标书时检索。

技术栈：Python 3.13 + uv（FastAPI、Celery/Redis、SQLAlchemy 2.0 + asyncpg、ChromaDB、OpenAI/zai-sdk、LangGraph、python-docx、PyMuPDF）；前端为 `frontend/` 下独立的 React 19 + Vite + TypeScript + TailwindCSS v4 + Electron 项目。

## 常用命令

### Python 后端

- `uv sync` — 同步依赖到 `.venv`
- `uv add <pkg>` / `uv add --dev <pkg>` — 添加运行时/开发依赖
- `uv run <cmd>` — 在项目虚拟环境中执行命令
- `uv run zhibiao ingest <pdf>` — 解析 PDF → 分块 → 智谱嵌入 → 写入 Chroma
  - `--parser auto|mineru|pymupdf`：默认 `auto`（MinerU 优先，失败回退 PyMuPDF）
  - `--dry-run`：只解析和分块，不调用 embedding、不写库
  - `--reparse`：忽略 `data/parsed/` 缓存重新解析
  - `--max-chars` / `--overlap` / `--collection`：覆盖分块与集合配置
- `uv run zhibiao search "投标保证金是多少" -n 5` — 语义检索已入库片段
- `uv run pytest` — 运行测试；单个测试：`uv run pytest tests/test_chunker.py::test_split_long_text_respects_max_and_overlap -v`

### 前端 / 桌面端

- `cd frontend && npm install`（本机需加 `--cache G:/uv-project/zhibiao/.npm-cache`）
- `npm run dev` — Vite 开发服务器
- `npm run build` — `tsc -b` 类型检查 + 生产构建
- `npm run lint` — oxlint
- `npm run electron` — 构建后启动 Electron 桌面端（加载 `dist/index.html`）

## 架构

### 知识库入库管线（核心）

入口 `src/zhibiao/cli.py` → `pipeline.py`，各模块职责：

1. **`mineru.py`**：MinerU 云端精准解析 API。本地 PDF 通过 `/api/v4/file-urls/batch` 申请上传链接、PUT 上传、轮询 `/api/v4/extract-results/batch/{batch_id}`、下载结果 zip。单文件上限 200 页，`split_pdf()` 会用 PyMuPDF 在本地切成多个 ≤200 页的分片后批量上传；每个分片记录 `page_offset`，用于把分片内 `page_idx` 还原成全局页码。
2. **`content_list.py`**：把 MinerU 的 `*_content_list.json` 转成 `Block`（Markdown 文本 + 1-based 全局页码 + 标题层级），表格先保留 HTML、公式用 `$$` 包裹、图片保留图注。`blocks_from_markdown()` 用于 content_list 缺失时降级。
3. **`fallback.py`**：MinerU 失败时用 PyMuPDF 逐页提取文本生成 Markdown，并按页生成 `Block`。若文本中替换字符（�）比例高会警告——该 PDF 的字体可能缺少 ToUnicode 映射，此时 PyMuPDF 结果会乱码。
4. **`chunker.py`**：按 Markdown 标题（一级/二级标题切段）和长度（默认 1000 字符、重叠 120）切块；超长块按句末标点/换行切分；表格 HTML 会先转成管道分隔的纯文本（`html_table_to_text()`）以减少 embedding 噪声；块保留 `page_start`/`page_end`/`heading`，续块会加 `【章节】...` 上下文前缀。
5. **`embedder.py`**：智谱 `embedding-3` 批量嵌入（默认每批 32 条、4 次指数退避重试；维度参数被拒时自动降级为模型默认维度）。
6. **`store.py`**：Chroma `PersistentClient`，集合 `bid_documents`（cosine），以 `doc_id` 为单位先删后写保证幂等；片段 ID 为 `<doc_id>:<序号>`，metadata 含来源文件、页码、章节、解析器。
7. **`pipeline.py`**：编排解析 → 分块 → 嵌入 → 入库；解析结果缓存在 `data/parsed/<doc_id>/`（`manifest.json`、`blocks.json`、`chunks.jsonl`、MinerU 原始输出与 `mineru_full.md`），再次入库默认复用缓存。

### 前端 / Electron

- `frontend/` 是独立 npm 项目，不是 npm workspace。
- TailwindCSS v4 走 `@tailwindcss/vite` 插件 + `frontend/src/index.css` 顶部的 `@import 'tailwindcss';`，没有 `tailwind.config.js`。
- `frontend/electron/main.cjs` 是 Electron 主进程，`npm run electron` 会先构建再加载 `dist/index.html`。因为通过 `file://` 加载，`vite.config.ts` 中必须保留 `base: './'`（否则 `/assets/...` 绝对路径会导致白屏）。

## 配置与环境

- 根目录 `.env` 保存密钥与运行配置（已 gitignore、已从 git 索引移除）。关键项：`ZHIPU_API_KEY`、`EMBEDDING_MODEL=embedding-3`、`EMBEDDING_DIMENSIONS=1024`、`CHROMA_DIR=./chroma_db`、`MINERU_MODE=cloud`、`MINERU_API_KEY`、`MINERU_ENDPOINT`、`MINERU_MODEL_VERSION=vlm`、`MINERU_MAX_POLLS`。禁止把 `.env` 提交到 git。
- 运行时数据目录（均已 gitignore）：`chroma_db/`（向量库）、`data/parsed/`（解析缓存）、`upload/files/`（待解析 PDF，目前未忽略）。
- MinerU 精准解析是异步任务，200 页文档轮询可能需要 10–30 分钟；`MINERU_MAX_POLLS=360`（×5 秒）为轮询上限。
- 本机环境注意：全局 npm 缓存 `G:\nodejs\node_cache` 不可写，npm 命令需 `--cache G:/uv-project/zhibiao/.npm-cache`；Electron 二进制从 GitHub 下载会失败，需通过镜像安装：`cd frontend && ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/" node node_modules/electron/install.js`。
