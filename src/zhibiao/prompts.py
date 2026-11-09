from __future__ import annotations

import os
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate
from langsmith import Client

SYSTEM_WRITER = """你是资深投标文件编写专家。必须严格遵守：
1. 只使用给定的招标文件事实和投标人资料；
2. 任何未提供的信息一律写【待填写】，严禁编造公司名称、资质、业绩、人员、设备、证书编号、金额、日期；
3. 输出 Markdown，不要输出解释、代码围栏或与投标文件无关的内容。"""

SYSTEM_REVIEWER = """你是投标文件合规审查专家。只输出一个合法 JSON 对象，不要输出解释或 Markdown 代码块。
审查重点：评分因素覆盖、资格材料覆盖、缺失信息是否保留【待填写】、是否存在无依据编造的具体事实。"""

TECHNICAL_HUMAN = """任务：编写投标文件技术部分《施工组织设计》的指定章节，只编写本批次列出的评分因素。

【项目概况】
{overview}

【关键时间与工期】
{key_dates}

【本批次必须逐项响应的评分因素】
{scoring}

【投标人资料】（【待填写】表示未提供，禁止编造）
{profile_json}

【写作要求】
1. 只输出本批次评分因素对应的三级标题章节（以 "###" 开头），不要输出 "## 施工组织设计" 总标题。
2. 对每个评分因素说明编制思路、措施和对应得分点。
3. 章节编号从 1 开始连续编号，标题中不要写分值。
4. 每个评分因素正文控制在 250–400 字，总输出不超过 3000 字，避免长篇论述。
5. 可以使用招标文件给定的工期、质量、范围等信息；不得编造投标人业绩、人员、设备数量、证书、金额。
6. 缺失的投标人信息一律写【待填写】。"""

COMMERCIAL_QUALIFICATION_HUMAN = """任务：编写投标文件商务部分“资格审查资料”的指定批次。

【项目概况】
{overview}

【本批次资格条件】
{conditions}
{documents_text}
【投标人资料】（【待填写】表示未提供，禁止编造）
{profile_json}

【写作要求】
1. 只输出本批次“资格审查资料”的子章节（以 "###" 开头），不要输出 "## 商务部分" 总标题。
2. 每条条件给出“招标要求—投标人响应—证明材料”的对应关系，可用 Markdown 表格。
3. 投标人响应只能来自资料；缺失写【待填写】。
4. 每条不超过 150 字，总输出不超过 3000 字。
5. 不编造业绩、人员、财务数据、证书编号、信用等级。"""

COMMERCIAL_SCORING_HUMAN = """任务：编写投标文件商务部分“项目管理机构与商务评分响应”。

【项目概况】
{overview}

【商务评分因素】
{factors}

【投标人资料】（【待填写】表示未提供，禁止编造）
{profile_json}

【写作要求】
1. 只输出本批次子章节（以 "###" 开头），不要输出 "## 商务部分" 总标题。
2. 项目管理机构按项目经理、技术负责人、质量负责人、安全负责人等岗位列出。
3. 对业绩、财务、信用、体系认证逐项响应。
4. 每个因素不超过 200 字，总输出不超过 3000 字。
5. 不编造业绩、人员、财务数据、证书编号、信用等级；缺失写【待填写】。"""

FORMAT_HUMAN = """任务：编写投标文件格式部分的指定章节，只编写本批次列出的格式项。

【项目概况】
{overview}

【本批次格式清单】
{items}

【关键时间】
{key_dates}

【投标人资料】（【待填写】表示未提供，禁止编造）
{profile_json}

【写作要求】
1. 只输出本批次格式项对应的三级标题章节（以 "###" 开头），不要输出 "## 投标文件格式" 总标题。
2. 按清单逐项生成可直接编辑的格式文本或表格。
3. 每个格式项不超过 300 字，总输出不超过 3000 字。
4. 金额、日期、证书编号、人员姓名等缺失信息写【待填写】，不得编造。
5. 使用标准格式措辞，不要编造具体承诺金额或日期。"""

REVIEW_TECHNICAL_HUMAN = """任务：审查投标文件技术标的结构与覆盖情况。不要复述草稿。

【施工组织设计评分因素】
{scoring}

【草稿章节标题】
{headings}

【缺失的投标人字段】
{missing}

【占位符数量】{placeholder_count}

只输出 JSON：
{{
  "issues": [
    {{"section": "", "issue": "", "severity": "high|medium|low", "suggestion": ""}}
  ],
  "placeholder_count": 0,
  "fabrication_risk": false,
  "summary": ""
}}

要求：最多 5 条 issues；每条 issue/suggestion 不超过 30 字；summary 不超过 80 字；只输出 JSON。"""

REVIEW_COMMERCIAL_HUMAN = """任务：审查投标文件商务部分与格式文件的结构与覆盖情况。不要复述草稿。

【资格审查条件】
{conditions}

【第八章格式清单】
{formats}

【草稿章节标题】
{headings}

【缺失的投标人字段】
{missing}

【占位符数量】{placeholder_count}

只输出 JSON：
{{
  "issues": [
    {{"section": "", "issue": "", "severity": "high|medium|low", "suggestion": ""}}
  ],
  "placeholder_count": 0,
  "fabrication_risk": false,
  "summary": ""
}}

要求：最多 5 条 issues；每条 issue/suggestion 不超过 30 字；summary 不超过 80 字；只输出 JSON。"""


def _template(human: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [("system", SYSTEM_WRITER), ("human", human)]
    )


def _review_template(human: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [("system", SYSTEM_REVIEWER), ("human", human)]
    )


@dataclass(frozen=True)
class PromptSpec:
    name: str
    template: ChatPromptTemplate
    description: str
    tags: tuple[str, ...]


PROMPT_SPECS: dict[str, PromptSpec] = {
    "zhibiao-technical-writer": PromptSpec(
        name="zhibiao-technical-writer",
        template=_template(TECHNICAL_HUMAN),
        description="标书技术标施工组织设计分批写作提示词",
        tags=("zhibiao", "bid-writer", "technical"),
    ),
    "zhibiao-commercial-qualification": PromptSpec(
        name="zhibiao-commercial-qualification",
        template=_template(COMMERCIAL_QUALIFICATION_HUMAN),
        description="标书商务标资格审查资料写作提示词",
        tags=("zhibiao", "bid-writer", "commercial"),
    ),
    "zhibiao-commercial-scoring": PromptSpec(
        name="zhibiao-commercial-scoring",
        template=_template(COMMERCIAL_SCORING_HUMAN),
        description="标书商务标项目管理机构与商务评分响应提示词",
        tags=("zhibiao", "bid-writer", "commercial"),
    ),
    "zhibiao-format-writer": PromptSpec(
        name="zhibiao-format-writer",
        template=_template(FORMAT_HUMAN),
        description="标书第八章格式文件写作提示词",
        tags=("zhibiao", "bid-writer", "format"),
    ),
    "zhibiao-reviewer-technical": PromptSpec(
        name="zhibiao-reviewer-technical",
        template=_review_template(REVIEW_TECHNICAL_HUMAN),
        description="标书技术标结构审查提示词",
        tags=("zhibiao", "bid-writer", "review"),
    ),
    "zhibiao-reviewer-commercial": PromptSpec(
        name="zhibiao-reviewer-commercial",
        template=_review_template(REVIEW_COMMERCIAL_HUMAN),
        description="标书商务/格式结构审查提示词",
        tags=("zhibiao", "bid-writer", "review"),
    ),
}


PERMISSION_ERROR = (
    "ERROR: 当前 LANGSMITH_API_KEY 是 tracing-only key，无法访问 Prompt Hub；"
    "请更换为具备 prompts:read/write 权限的 LangSmith key"
)


class PromptHub:
    """优先从 LangSmith Prompt Hub 拉取最新版本，失败时回退本地模板。

    每次 write_bid 运行创建新实例，因此 Hub 中发布新版本后下一轮任务即可热更新。
    """

    def __init__(
        self,
        enabled: bool | None = None,
        client: Client | None = None,
    ) -> None:
        if enabled is None:
            enabled = (
                os.getenv("LANGSMITH_PROMPT_HUB", "true").strip().lower()
                in {"1", "true", "yes", "on"}
            )
        self.enabled = enabled
        self.client = client
        if self.client is None and self.enabled:
            if os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"):
                try:
                    self.client = Client()
                except Exception as exc:  # noqa: BLE001
                    print(f"[prompt-hub] 初始化 LangSmith Client 失败：{exc}", flush=True)
        self._cache: dict[str, ChatPromptTemplate] = {}
        self._warned: set[str] = set()
        self._hub_denied = False

    @staticmethod
    def _is_permission_error(exc: Exception) -> bool:
        text = str(exc)
        return (
            "not allowed for tracing keys" in text
            or "prompts:read" in text
            or "prompts:write" in text
        )

    def _get_template(self, name: str) -> ChatPromptTemplate:
        if name in self._cache:
            return self._cache[name]
        if self.client is not None and not self._hub_denied:
            try:
                template = self.client.pull_prompt(name, skip_cache=True)
                self._cache[name] = template
                return template
            except Exception as exc:  # noqa: BLE001
                if self._is_permission_error(exc):
                    # tracing-only key 无法访问 Prompt Hub，本实例不再尝试其余提示词
                    self._hub_denied = True
                    print(
                        "[prompt-hub] 当前 LangSmith key 无 Prompt Hub 权限，"
                        "本次运行使用本地模板；请更换具备 prompts 读写权限的 key。",
                        flush=True,
                    )
                elif name not in self._warned:
                    self._warned.add(name)
                    print(
                        f"[prompt-hub] 拉取 {name} 失败，使用本地模板：{exc}",
                        flush=True,
                    )
        spec = PROMPT_SPECS.get(name)
        if spec is None:
            raise KeyError(f"未知提示词：{name}")
        self._cache[name] = spec.template
        return spec.template

    def render(self, name: str, **variables: object) -> tuple[str, str]:
        template = self._get_template(name)
        messages = template.format_messages(**variables)
        system_parts: list[str] = []
        human_parts: list[str] = []
        for message in messages:
            text = message.content if isinstance(message.content, str) else str(message.content)
            if message.type == "system":
                system_parts.append(text)
            else:
                human_parts.append(text)
        return "\n\n".join(system_parts), "\n\n".join(human_parts)

    def push_all(self) -> dict[str, str]:
        if self._hub_denied:
            return {name: PERMISSION_ERROR for name in PROMPT_SPECS}
        client = self.client
        if client is None:
            try:
                client = Client()
            except Exception as exc:  # noqa: BLE001
                return {name: f"ERROR: {exc}" for name in PROMPT_SPECS}
        results: dict[str, str] = {}
        for name, spec in PROMPT_SPECS.items():
            try:
                commit = client.push_prompt(
                    name,
                    object=spec.template,
                    description=spec.description,
                    tags=list(spec.tags),
                )
                results[name] = str(commit)
            except Exception as exc:  # noqa: BLE001
                if self._is_permission_error(exc):
                    # 同一个 key 的其余提示词也会 403，直接给出明确结论
                    for other in PROMPT_SPECS:
                        results.setdefault(other, PERMISSION_ERROR)
                    break
                results[name] = f"ERROR: {exc}"
        return results


def push_prompts() -> dict[str, str]:
    return PromptHub().push_all()
