"""Request and response models for the demo apps' APIs (``/api/apps``).

``app/api/admin_schemas.py`` documents the management surface; this module does
the same for the two demo apps, whose routes return plain dicts built by
``app/apps/kb/store.py`` rather than pydantic objects. Same rule as there: these
models describe the wire format, they do not validate it -- except for the four
*request* bodies, which are what FastAPI validates anyway.

Field names are a contract with the console (``web/src/apps.ts``), which is why
the store's builders spell every key out. A rename here must match that file.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_DOC = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# knowledge base
# ---------------------------------------------------------------------------
class KbOut(BaseModel):
    model_config = _DOC
    id: str = Field(description="知识库 id", examples=["kb_7f3a1c2e"])
    name: str = Field(description="名字", examples=["产品手册"])
    created_at: float = Field(description="创建时间（epoch 秒）")
    created_at_iso: str | None = Field(default=None, description="同上，本地时区 ISO8601")
    doc_count: int = Field(description="文档数", examples=[3])
    chunk_count: int = Field(description="切片数", examples=[412])
    embedding_model: str | None = Field(
        default=None, description="建库用的 embedding 模型 id；空库为 null")
    dims: int = Field(default=0, description="向量维度", examples=[1024])
    needs_reindex: bool = Field(
        default=False, description="向量与切片已不一致，需要点「重建索引」")


class KbListOut(BaseModel):
    model_config = _DOC
    kbs: list[KbOut] = Field(description="全部知识库，最新创建的在前")


class CreateKbBody(BaseModel):
    name: str = Field(default="", max_length=200, description="知识库名字；可留空",
                      examples=["产品手册"])


class CreateKbOut(BaseModel):
    model_config = _DOC
    kb: KbOut = Field(description="新建的知识库")


class DocOut(BaseModel):
    model_config = _DOC
    id: str = Field(description="文档 id")
    name: str = Field(description="原文件名", examples=["manual.pdf"])
    type: Literal["txt", "md", "pdf", "image"] = Field(description="解析类型")
    bytes: int = Field(description="文件大小（字节）")
    pages: int = Field(description="页数；图片与纯文本为 1")
    status: Literal["queued", "parsing", "embedding", "ready", "failed"] = Field(
        description="索引进度状态", examples=["ready"])
    progress: dict[str, Any] | None = Field(
        default=None, description="进度：`stage` / `done` / `total`")
    error: str | None = Field(default=None, description="失败原因；只有 `failed` 时有值")
    warnings: list[str] = Field(default_factory=list,
                                description="解析告警（不阻断入库），如某页没有文本层")
    chunks: int = Field(description="切出的片段数")
    text_pages: int = Field(description="走文本层解析的页数")
    ocr_pages: int = Field(description="走 OCR 的页数")
    created_at: float = Field(description="上传时间（epoch 秒）")


class DocListOut(BaseModel):
    model_config = _DOC
    docs: list[DocOut] = Field(description="知识库里的文档，最新的在前")


class UploadDocsOut(BaseModel):
    model_config = _DOC
    docs: list[DocOut] = Field(
        description="刚排进队列的文档。**解析是异步的**：用 `GET .../docs` 轮询 `status`，"
                    "`ready` 之后才可检索")


class ChunkOut(BaseModel):
    model_config = _DOC
    id: str = Field(description="切片 id")
    page: int | None = Field(default=None, description="所在页（从 1 开始）")
    source: str | None = Field(default=None, description="来源标签，如 `页 3`")
    text: str = Field(description="切片正文")
    char_start: int | None = Field(default=None, description="在原文中的起始字符下标")
    char_end: int | None = Field(default=None, description="在原文中的结束字符下标")
    boxes: list[list[float]] = Field(
        default_factory=list,
        description="版面框 `[[x0,y0,x1,y1], ...]`，像素坐标；文档识别页用它把片段框在预览图上")


class ChunkListOut(BaseModel):
    model_config = _DOC
    chunks: list[ChunkOut] = Field(description="该文档的切片，按原文顺序")


class SearchBody(BaseModel):
    model_config = _DOC
    query: str = Field(description="检索问题", examples=["怎么升级固件"])
    top_k: int = Field(default=5, description="返回几条；不能大于 `candidates`")
    candidates: int = Field(default=20, description="进入精排的候选数，上限 100")
    use_bm25: bool = Field(default=True, description="是否用 BM25 召回")
    use_vector: bool = Field(default=True, description="是否用向量召回")
    use_rerank: bool = Field(default=True, description="是否用 reranker 精排")


class SearchHitOut(BaseModel):
    model_config = _DOC
    chunk_id: str = Field(description="切片 id，可直接传给 `/answer`")
    doc_id: str | None = Field(default=None, description="所属文档 id")
    doc_name: str | None = Field(default=None, description="所属文档名")
    page: int | None = Field(default=None, description="页码")
    text: str = Field(description="切片正文")
    score: float = Field(description="最终得分（精排后的相关度）")
    stages: dict[str, Any] | None = Field(
        default=None, description="各阶段得分（bm25 / vector / rrf / rerank），用于解释排序")


class SearchOut(BaseModel):
    model_config = _DOC
    query: str = Field(description="原查询")
    hits: list[SearchHitOut] = Field(description="排序后的命中，最相关的在前")
    skipped: dict[str, str] = Field(
        default_factory=dict,
        description="被跳过的阶段及原因，例如 `{\"vector\": \"模型未加载\"}`。"
                    "**降级会说明，不会静默**")


class AnswerBody(BaseModel):
    model_config = _DOC
    query: str = Field(description="问题", examples=["怎么升级固件"])
    chunk_ids: list[str] = Field(
        description="用哪些切片作为依据。先调 `/search`，把它的 `chunk_id` 传进来")
    model: str | None = Field(
        default=None, description="指定回答用的模型 id；省略则用当前已加载的 chat 模型")
    max_tokens: int = Field(default=1024, description="最多生成多少 token")


class ReindexJobOut(BaseModel):
    model_config = _DOC
    ok: bool = Field(default=True, description="任务已排入队列")
    job: dict[str, Any] = Field(
        description="`documents`（参与重建的文档数）、`chunks`（切片数）、`model`（用的模型）",
        examples=[{"documents": 3, "chunks": 412, "model": "qwen3-embedding-0.6b"}])


class RetryDocOut(BaseModel):
    model_config = _DOC
    ok: bool = Field(default=True, description="已重新排队")
    doc: DocOut = Field(description="重试后的文档状态（`queued`）")
