# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

`zhibiao`（README 名：zhihuibiaoshu）是一个标书制作项目。当前已实现招标文件的知识库管线：PDF 经 MinerU 云端精准解析（失败时回退 PyMuPDF）转为 Markdown，按章节分块后用智谱 `embedding-3` 嵌入，写入 Chroma 向量库，供后续多 Agent 编写标书时检索。

技术栈：Python 3.13 + uv（FastAPI、Celery/Redis、SQLAlchemy 2.0 + asyncpg、Alembic、ChromaDB、OpenAI/zai-sdk、LangGraph、LangSmith、python-docx、PyMuPDF）；前端为 `frontend/` 下独立的 React 19 + Vite + TypeScript + TailwindCSS v4 + Electron 项目。

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
- `uv run zhibiao extract <pdf>` — 用 DeepSeek 结构化抽取：项目概况、评标办法（评审因素/分值/评分标准）、投标人须知前附表、资格审查条件、第八章格式清单、关键时间节点；输出 `extraction.json` 和 `extraction.md` 到解析缓存目录（`--output-dir` 可覆盖，`--refresh` 忽略分片缓存重新调用 LLM）
- `uv run python -m src.cli write <doc_id>` — 用 LangGraph 多 Agent 生成投标文件（Markdown + Word）。输入 `bidder_profile.json`，缺失字段一律写【待填写】；产物写入 `data/bids/<doc_id>/`（`bid.md`、`bid.docx`、`agent_outputs/`、`bid_meta.json`）
  - `--profile <path>` 指定投标人资料；`--output-dir` 指定产物目录；`--no-docx` 只生成 Markdown
- `uv run python -m src.cli prompts push` — 把本地提示词 push 到 LangSmith Prompt Hub（需要具备 prompts 读写权限的完整 API key；`lsv2_tr_` 开头的 tracing key 会返回 403）
- `uv run alembic upgrade head` — 应用 PostgreSQL 迁移；新环境首次启动 API/Celery 前必须先执行
- `uv run alembic check` — 校验 SQLAlchemy 模型与迁移脚本是否一致
- `uv run alembic revision --autogenerate -m "..."` — 修改 `db_models.py` 后生成新迁移
- `uv run python -m src.cli sync-documents` — 一次性把现有 `data/parsed`/`upload/parsed` 文档回填到 `documents`/`projects` 表
- `uv run pytest` — 全量测试（99 个用例，7 秒左右跑完；网络调用全部 mock，API 测试使用临时 SQLite，测试内强制关闭 LangSmith tracing / Prompt Hub）
- 单个测试：`uv run pytest tests/test_chunker.py::test_split_long_text_boundaries -v`
- `zhibiao` 命令退出码：成功 0，业务/配置异常 1，argparse 参数错误 2

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
8. **`extractor.py`**：基于 `blocks.json` 和 DeepSeek JSON 模式做结构化抽取，按页构建带 `[PDF p.X]` 标记的上下文，六类抽取分别独立调用 LLM；超长表格（前附表、评分表）按行/页拆成多次调用后合并，避免输出截断。结果写入 `data/parsed/<doc_id>/extraction.json` 与 `extraction.md`，各分片缓存位于 `extraction_parts/`。提示词要求逐条附页码、全量不合并，并明确禁止编造。`check_provenance()` 会核对每个带页码抽取项的页码是否存在、quote 能否在对应页原文中找到，结果写入 `provenance_warnings` 并渲染为报告末尾的“溯源核对”章节。
9. **`toc.py`**：`parse_toc()` 解析“标题.... 页码”形式的目录行并按章/节/条目标注层级；`toc_from_blocks()` 从解析缓存前 10 页提取目录，`extract` 会把结果写入 `extraction.json` 的 `toc` 字段并在 Markdown 中输出目录表。

### 投标文件生成（LangGraph 多 Agent）

入口：`src/cli.py` → `src/zhibiao/bid_writer.py`。流程为 `planner → technical_writer → commercial_writer → format_writer → reviewer → assembler`，每个 writer 是独立 DeepSeek Agent。技术标/格式文件按 4 个评分因素/格式项分批生成，商务标按资格审查与评分响应分批生成；单批输出截断时会自动二分重试。reviewer 分技术标、商务/格式两次做结构审查，并叠加规则审计（评分因素/资格/格式覆盖、【待填写】保留、未授权公司名称）。

- `src/zhibiao/profile.py`：`bidder_profile.json` 模板深合并；所有空值/缺失字段统一替换为 `【待填写】`，`missing_fields()` 供审查 Agent 使用。`bidder_profile.json` 已 gitignore，`bidder_profile.example.json` 为示例。
- `src/zhibiao/llm.py`：`DeepSeekChat` 文本/JSON 两种调用，含重试与截断检测。
- `src/zhibiao/bid_writer.py`：加载 `data/parsed/<doc_id>/extraction.json`，构建技术/商务/格式三部分；技术部分逐项响应施工组织设计评分因素，商务部分覆盖资格条件与材料，格式部分按第八章清单生成。提示词统一要求“只用给定事实，缺失信息写【待填写】，禁止编造”。
- `src/zhibiao/docx_export.py`：把 Markdown 子集（标题/段落/列表/表格/加粗）转成 docx，`【待填写】` 标红加粗。
- 产物：`data/bids/<doc_id>/bid.md`、`bid.docx`、`bid_meta.json`、`agent_outputs/{outline.json,technical.md,commercial.md,format.md,review.json}`。
- `src/zhibiao/prompts.py`：全部写作/审查提示词集中为 `ChatPromptTemplate`，登记在 `PROMPT_SPECS`（名称 `zhibiao-technical-writer`、`zhibiao-commercial-qualification`、`zhibiao-commercial-scoring`、`zhibiao-format-writer`、`zhibiao-reviewer-technical`、`zhibiao-reviewer-commercial`）。`PromptHub` 在每次 `write_bid` 运行时按名称 `client.pull_prompt(name, skip_cache=True)` 拉取 Hub 最新版本，失败或关闭时回退本地模板；`push_all()` 用 `client.push_prompt()` 上传版本。Hub 发布新 commit 后下一轮生成任务即热更新，无需重启服务和 worker。

### LangSmith 追踪

- `LANGSMITH_TRACING=true` 时，LangGraph 节点自动上报；`langsmith.wrappers.wrap_openai` 包装 DeepSeek/OpenAI 客户端；`@traceable` 覆盖关键链路：
  - `bid.write`、`celery.parse_pdf`、`celery.write_bid`、`parse.pdf`、`ingest.pdf`、`search`
  - 工具：`mineru.split_pdf`、`mineru.parse`、`pymupdf.parse`、`chroma.replace_document`
  - 检索/嵌入：`chroma.query`、`zhipu.embed_documents`、`zhipu.embed_query`
  - 抽取：`deepseek.extract_json`、`extract.document`
- Trace 项目名由 `LANGSMITH_PROJECT` 指定（当前 `zhibiao`）。LangSmith 后端不可用时不影响主流程：追踪上报是后台异步的，Prompt Hub 拉取失败会打印一次警告并使用本地模板。
- Prompt Hub 需要在 LangSmith 中创建具备 prompts 权限的 API key；tracing-only key 只能写入 trace，不能 pull/push 提示词。注意 trace 上报成功后，某些 tracing key 也无法在 API 中读取 runs，需要在 LangSmith Web 项目页查看。

### 业务数据库与持久化

前置：PostgreSQL 需运行在 `DATABASE_URL`（当前 `bidding` 库）；Redis 仅作为 Celery broker/result backend。首次部署先执行 `uv run alembic upgrade head`，API 启动不会自动建表。

四张核心业务表 + 公司表（模型在 `src/zhibiao/db_models.py` 与 `src/zhibiao/company.py`）：

- `users`：`id` UUID、`username` 唯一、`display_name`、`email`、`password_hash`、`is_active`、时间戳。当前只建表，尚未实现登录/鉴权。
- `projects`：`id` UUID、`name` 唯一、`description`、`status`、`owner_id` 外键 `users.id`、时间戳。
- `documents`：`doc_id` 字符串主键（沿用原磁盘目录名）、`filename`、`source`、`root`、`page_count`、`parser`、`chunk_count`、`has_extraction`、`project_id` 外键 `projects.id`、时间戳。
- `tasks`：`id` 字符串主键（即 Celery task_id/job_id）、`task_type`、`status`（pending/running/succeeded/failed）、`stage`、`retry_count`、`max_retries`、`payload` JSONB、`result` JSONB、`error`、`duration_ms`、`doc_id`/`project_id`/`user_id` 外键、`created_at`/`started_at`/`finished_at`/`updated_at`。
- `companies`：公司资料表，见下方 API。

- `src/zhibiao/db.py`：async engine、`async_sessionmaker`、`Base`；`init_db()` 仅供测试/回填使用，生产 schema 由 Alembic 管理。
- `src/zhibiao/db_models.py`：`User`、`Project`、`Document`、`Task` ORM 模型。
- `src/zhibiao/document_store.py`：文档 upsert、项目 `get_or_create`、从 `manifest.json`/`extraction.json` 回填，以及 `backfill_documents()`。
- `src/zhibiao/task_store.py`：任务创建/查询/开始/阶段更新/完成；`run_async()` 为 Celery 同步任务提供一次性 NullPool engine，把状态写回 PostgreSQL。
- `alembic/versions/0001_companies.py`：`companies` 基线；`0002_business_tables.py`：`users`、`projects`、`documents`、`tasks`。
- 现有磁盘文档通过 `uv run python -m src.cli sync-documents` 一次性回填；解析任务完成后会自动 upsert 新文档。
- 任务状态写入失败只打印 `[task-db]` 告警，不影响解析/投标主流程。

### API 服务与 Celery（`api/` + `src/zhibiao/tasks.py`）

前置：PostgreSQL 与 Redis 均需运行；worker 启动前先执行 `uv run alembic upgrade head`。

- 启动 worker（Windows 必须 `--pool=solo`）：`uv run celery -A zhibiao.tasks.celery_app worker --loglevel=info --pool=solo --concurrency=1`
- 启动 API：`uv run uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload`，Swagger 在 `/docs`
- `GET /api/health` — 健康检查（含 Redis 连通性；数据库连通性在启动日志中检查）
- `POST /api/parse` — multipart 上传 PDF（`file`、`parser=auto|mineru|pymupdf`，可选 `extract=true` 结构化抽取、`ingest=true` 向量入库）；先写入 `tasks`（pending），再投递 Celery，返回 `202` + `job_id`
- `GET /api/parse/{job_id}` — 查询 `tasks` 表；返回 `status`/`stage`（parsing/extracting/embedding）/时间戳/`result`/`error`
- `POST /api/bids` — JSON `{doc_id, profile?, company_id?, export_docx?}`；`profile`、`company_id` 二选一，都为空时使用服务端 `bidder_profile.json`；`company_id` 从 `companies` 表读取；先写 `tasks` 再投递 `bidding.write_bid`
- `GET /api/bids/{job_id}` — 查询 `tasks` 表，校验 `task_type=write_bid`；返回产物路径、占位符数量、审查结果与 `scoring_report`
- `GET /api/tasks` — 任务历史，支持 `task_type`、`status`、`limit`、`offset`
- `POST /api/companies` — 录入公司信息，JSON `{company_name, profile}`；返回 `201` + 公司详情
- `GET /api/companies` — 分页/按名称搜索（`q`、`limit`、`offset`）
- `GET /api/companies/{company_id}` — 公司详情（含完整 `profile`）
- `PUT /api/companies/{company_id}` — 全量更新公司名称与资料
- `DELETE /api/companies/{company_id}` — 删除公司信息（`204`）
- `GET /api/documents` — 从 `documents` 表查询已解析文档，关联 `projects` 返回项目名、页数、片段数、解析器、抽取状态
- `GET /api/bids` — 仍扫描 `data/bids`/`upload/bids` 下的历史产物（文件清单，不是任务状态；任务历史请用 `/api/tasks`）
- `GET /api/bids/{doc_id}/files/{filename}` — 提供 `bid.md`、`bid.docx`、`bid_meta.json` 的下载/预览（`?download=false` 为内联预览）
- `/api/parse` 与 `/api/bids` 共用 Celery 队列，但任务状态不再依赖 Redis 登记表或 `AsyncResult`；API 只查 `tasks` 表。新增任务后仍需重启 worker 才能注册。

实现要点：
- `src/zhibiao/tasks.py`：Celery app 与 `zhibiao.parse_pdf`、`bidding.write_bid`；每个阶段调用 `task_store` 更新 DB，成功后写入 `result`、`doc_id`、`duration_ms`，失败写入 `error`。
- `src/zhibiao/job_store.py`：旧 Redis 任务登记表实现，API 已不再使用；保留供兼容/测试参考。
- `pipeline.parse_pdf_to_chunks()`：API/任务共用的“解析 + 分块 + 写 `chunks.jsonl`”服务；文件按内容 SHA1 前缀命名存入 `upload/files/`，保证同一 PDF 重复上传得到稳定 `doc_id`。
- `src/zhibiao/company.py`：`companies` 表及 CRUD 函数；`profile` 在 PostgreSQL 用 JSONB，测试时用 SQLite JSON。
- CORS 全开且无鉴权，仅适合本地开发。

### 数据库 MCP（PostgreSQL）

- 项目级配置 `.mcp.json` 注册名为 `postgres` 的 stdio MCP server，命令为 `uv run python tools/postgres_mcp.py`。
- `tools/postgres_mcp.py` 从 `.env` 读取 `DATABASE_URL`，把 `postgresql+asyncpg://` 转成 `postgresql://`，通过 `DATABASE_URI` 环境变量传给 `uvx postgres-mcp2 --access-mode=restricted`；连接串不会写入 `.mcp.json`，也不会出现在进程命令行里。
- 该 MCP 为只读模式：`execute_sql` 只能执行 SELECT，另有 `list_schemas`、`list_objects`、`get_object_details`、`explain_query` 等工具。新增/修改公司信息仍走 FastAPI 的 `/api/companies` 接口。
- 首次使用需在 Claude Code 中运行 `claude` 并批准项目 MCP server（`claude mcp list` 显示 `Pending approval`）；批准后可用 `/mcp` 查看工具，工具名形如 `mcp__postgres__execute_sql`。
- 当前 `DATABASE_URL` 指向本地 `bidding` 数据库；所有业务表由 Alembic 迁移管理，API 启动不会自动建表。

### 测试覆盖

`tests/` 使用 pytest，网络调用全部 mock（MinerU 的 `httpx`、DeepSeek 的 OpenAI client、智谱的 `ZhipuAiClient`、Chroma 客户端、Celery 投递），PyMuPDF 用临时生成的小 PDF。API/数据库测试使用临时 SQLite（`sqlite+aiosqlite:///...`），每个测试独立建表；任务测试默认禁用数据库回写。覆盖：TOC 解析、PDF 200 页分片、章节感知分块、表格清洗、抽取 schema 容错、JSON 解析（含代码围栏）、分片合并去重、页码/引用溯源核对、缓存复用、CLI 退出码、FastAPI 上传/任务状态映射/Celery 任务封装、数据库文档列表、任务历史与状态查询、公司信息 CRUD 与投标资料引用、投标人资料占位符、LangGraph 多 Agent 产物、评分覆盖报告、Markdown→Word 导出，以及 MinerU/DeepSeek/智谱/Chroma 的错误与重试路径。

### 前端 / Electron

- `frontend/` 是独立 npm 项目，不是 npm workspace；API 地址默认 `http://127.0.0.1:8001`，可用 `VITE_API_BASE` 覆盖。
- 界面为「左侧步骤导航 + 工作区」四步：上传与解析、投标文件编写、已解析文档库、历史投标产物。
- 投标人资料采用常用表单 + 可折叠高级 JSON 双视图，实时同步并保存到 localStorage；缺失字段提交后由后端填【待填写】。
- Markdown 预览使用 `react-markdown` + `remark-gfm`；产物支持下载 md/docx、预览与打开文件夹。
- TailwindCSS v4 走 `@tailwindcss/vite` 插件 + `frontend/src/index.css` 顶部的 `@import 'tailwindcss';`，没有 `tailwind.config.js`。
- `frontend/electron/main.cjs` 是 Electron 主进程，`preload.cjs` 暴露 `showItemInFolder` / `openPath` IPC（限制在项目目录内）；`npm run electron` 会先构建再加载 `dist/index.html`。因为通过 `file://` 加载，`vite.config.ts` 中必须保留 `base: './'`（否则 `/assets/...` 绝对路径会导致白屏）。

## 配置与环境

- 根目录 `.env` 保存密钥与运行配置（已 gitignore、已从 git 索引移除）。关键项：`LLM_PROVIDER=deepseek`、`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`ZHIPU_API_KEY`、`EMBEDDING_MODEL=embedding-3`、`EMBEDDING_DIMENSIONS=1024`、`CHROMA_DIR=./chroma_db`、`MINERU_MODE=cloud`、`MINERU_API_KEY`、`MINERU_ENDPOINT`、`MINERU_MODEL_VERSION=vlm`、`MINERU_MAX_POLLS`、`LANGSMITH_TRACING`、`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT=zhibiao`、`LANGSMITH_PROMPT_HUB`、`DATABASE_URL`（`postgresql+asyncpg://...`，当前数据库 `bidding`）。禁止把 `.env` 提交到 git。
- PostgreSQL schema 由 Alembic 管理：`uv run alembic upgrade head` 建表/升级；`uv run alembic check` 校验模型与迁移是否一致。本机现有 `bidding` 库已将 `companies` 基线标记为 `0001`，并升级到 `0002`。
- 运行时数据目录（均已 gitignore）：`chroma_db/`（向量库）、`data/parsed/`（解析缓存）、`upload/files/`（待解析 PDF，目前未忽略）。
- MinerU 精准解析是异步任务，200 页文档轮询可能需要 10–30 分钟；`MINERU_MAX_POLLS=360`（×5 秒）为轮询上限。
- 本机环境注意：全局 npm 缓存 `G:\nodejs\node_cache` 不可写，npm 命令需 `--cache G:/uv-project/zhibiao/.npm-cache`；Electron 二进制从 GitHub 下载会失败，需通过镜像安装：`cd frontend && ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/" node node_modules/electron/install.js`。
