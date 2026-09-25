"""CDIR schema — every PDF layout is reshaped into this standard form."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# Bump when canonicalize semantics change so cached indexes are invalidated.
CANONICAL_INDEX_VERSION = 1


class DocumentProfile(str, Enum):
    OUTLINE_KV = "outline_kv"
    STACKED_LABEL = "stacked_label"
    BROCHURE = "brochure"
    WEB_SCRAPE = "web_scrape"


class CanonicalSpec(BaseModel):
    parameter: str
    value: str
    unit: str | None = None
    qualifiers: list[str] = Field(default_factory=list)
    source_page: int | None = None
    source_section: str | None = None
    block_id: str | None = None


class CanonicalModule(BaseModel):
    id: str
    title: str
    specs: list[CanonicalSpec] = Field(default_factory=list)
    source_titles: list[str] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None


class CanonicalProduct(BaseModel):
    name: str | None = None
    maker: str | None = None
    variants: list[str] = Field(default_factory=list)


class RejectedChrome(BaseModel):
    title: str
    reason: str
    page: int | None = None


class CanonicalDocument(BaseModel):
    document_id: str
    profile: DocumentProfile
    index_version: int = CANONICAL_INDEX_VERSION
    product: CanonicalProduct = Field(default_factory=CanonicalProduct)
    modules: list[CanonicalModule] = Field(default_factory=list)
    rejected_chrome: list[RejectedChrome] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)
