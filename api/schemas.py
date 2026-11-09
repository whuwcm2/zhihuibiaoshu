from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ChunkPreview(BaseModel):
    index: int
    page_start: int
    page_end: int
    heading: str = ""
    text: str


class ParseResult(BaseModel):
    doc_id: str
    filename: str
    page_count: int
    parser: str
    block_count: int
    chunk_count: int
    markdown_path: str
    chunks_path: str
    chunks_preview: list[ChunkPreview] = Field(default_factory=list)
    extraction_path: str | None = None
    extraction_summary: dict[str, Any] | None = None
    ingested: bool = False


class ParseJobCreated(BaseModel):
    job_id: str
    status: str
    filename: str
    status_url: str


class ParseJobStatus(BaseModel):
    job_id: str
    filename: str
    status: Literal["pending", "running", "succeeded", "failed"]
    stage: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: ParseResult | None = None
    error: str | None = None


class CompanyCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str = Field(..., min_length=1, max_length=255, description="公司名称")
    profile: dict[str, Any] = Field(
        default_factory=dict,
        description="投标人资料，结构同 bidder_profile.json",
    )

    @field_validator("company_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("公司名称不能为空")
        return value


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_name: str
    contact_person: str | None = None
    contact_phone: str | None = None
    created_at: datetime
    updated_at: datetime


class CompanyDetail(CompanySummary):
    profile: dict[str, Any] = Field(default_factory=dict)


class BidRequest(BaseModel):
    doc_id: str = Field(..., description="已解析并抽取的文档 ID")
    profile: dict[str, Any] | None = Field(
        default=None,
        description="投标人资料；与 company_id 二选一，都为空时使用服务端 bidder_profile.json",
    )
    company_id: uuid.UUID | None = Field(
        default=None,
        description="已录入的公司信息 ID；与 profile 二选一",
    )
    export_docx: bool = True

    @model_validator(mode="after")
    def _one_profile_source(self) -> BidRequest:
        if self.company_id is not None and self.profile is not None:
            raise ValueError("company_id 与 profile 不能同时提供")
        return self


class BidJobCreated(BaseModel):
    job_id: str
    status: str
    doc_id: str
    status_url: str


class BidResult(BaseModel):
    job_id: str | None = None
    doc_id: str
    output_dir: str
    markdown_path: str
    docx_path: str | None = None
    agent_dir: str
    placeholder_count: int
    review: dict[str, Any] = Field(default_factory=dict)
    scoring_report: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None


class BidJobStatus(BaseModel):
    job_id: str
    doc_id: str | None = None
    status: Literal["pending", "running", "succeeded", "failed"]
    stage: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: BidResult | None = None
    error: str | None = None


class DocumentItem(BaseModel):
    doc_id: str
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    source: str | None = None
    page_count: int = 0
    parser: str | None = None
    created_at: datetime | None = None
    chunk_count: int = 0
    has_extraction: bool = False
    root: str


class TaskHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_type: str
    status: str
    stage: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    doc_id: str | None = None
    project_id: uuid.UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None


class BidHistoryItem(BaseModel):
    doc_id: str
    project_name: str | None = None
    company_name: str | None = None
    generated_at: str | None = None
    placeholder_count: int = 0
    review_summary: str = ""
    has_docx: bool = False
    output_dir: str
    markdown_path: str
    docx_path: str | None = None
