"""Typed models used by the Listmonk MCP bridge."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class SubscriberStatusEnum(StrEnum):
    enabled = "enabled"
    disabled = "disabled"
    blocklisted = "blocklisted"


class CampaignStatusEnum(StrEnum):
    draft = "draft"
    scheduled = "scheduled"
    running = "running"
    paused = "paused"
    finished = "finished"
    cancelled = "cancelled"


class CampaignTypeEnum(StrEnum):
    regular = "regular"
    optin = "optin"


class ContentTypeEnum(StrEnum):
    richtext = "richtext"
    html = "html"
    markdown = "markdown"
    plain = "plain"


class ListTypeEnum(StrEnum):
    public = "public"
    private = "private"


class OptinTypeEnum(StrEnum):
    single = "single"
    double = "double"


class TemplateTypeEnum(StrEnum):
    campaign = "campaign"
    campaign_visual = "campaign_visual"
    tx = "tx"


class TimestampedModel(BaseModel):
    created_at: datetime
    updated_at: datetime | None = None


class UUIDModel(BaseModel):
    uuid: str


class MailingList(TimestampedModel, UUIDModel):
    id: int
    name: str = Field(..., min_length=1, max_length=200)
    type: ListTypeEnum = ListTypeEnum.public
    optin: OptinTypeEnum = OptinTypeEnum.single
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    subscriber_count: int | None = Field(default=None, ge=0)


class Subscriber(TimestampedModel, UUIDModel):
    id: int
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=200)
    status: SubscriberStatusEnum = SubscriberStatusEnum.enabled
    lists: list[dict[str, Any]] = Field(default_factory=list)
    attribs: dict[str, Any] = Field(default_factory=dict)


class Campaign(TimestampedModel, UUIDModel):
    id: int
    name: str
    subject: str
    from_email: EmailStr | None = None
    body: str | None = None
    altbody: str | None = None
    send_at: datetime | None = None
    status: CampaignStatusEnum = CampaignStatusEnum.draft
    type: CampaignTypeEnum = CampaignTypeEnum.regular
    content_type: ContentTypeEnum = ContentTypeEnum.richtext
    tags: list[str] = Field(default_factory=list)
    views: int = 0
    clicks: int = 0
    to_send: int = 0
    sent: int = 0
    started_at: datetime | None = None
    lists: list[dict[str, Any]] = Field(default_factory=list)
    template_id: int | None = None
    messenger: str | None = None


class Template(TimestampedModel):
    id: int
    name: str
    subject: str
    body: str
    type: TemplateTypeEnum = TemplateTypeEnum.campaign
    is_default: bool = False


def _positive_ids(value: list[int] | None) -> list[int] | None:
    if value is not None and any(item <= 0 for item in value):
        raise ValueError("IDs must be positive integers")
    return value


class CreateSubscriberModel(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=200)
    status: SubscriberStatusEnum = SubscriberStatusEnum.enabled
    lists: list[int] = Field(default_factory=list)
    attribs: dict[str, Any] = Field(default_factory=dict)
    preconfirm_subscriptions: bool = False

    @field_validator("lists")
    @classmethod
    def validate_lists(cls, value: list[int]) -> list[int]:
        return _positive_ids(value) or []


class UpdateSubscriberModel(BaseModel):
    email: EmailStr | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: SubscriberStatusEnum | None = None
    lists: list[int] | None = None
    list_uuids: list[str] | None = None
    attribs: dict[str, Any] | None = None
    preconfirm_subscriptions: bool | None = None

    @field_validator("lists")
    @classmethod
    def validate_lists(cls, value: list[int] | None) -> list[int] | None:
        return _positive_ids(value)


class CreateListModel(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: ListTypeEnum = ListTypeEnum.public
    optin: OptinTypeEnum = OptinTypeEnum.single
    tags: list[str] = Field(default_factory=list)
    description: str | None = None


class UpdateListModel(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: ListTypeEnum | None = None
    optin: OptinTypeEnum | None = None
    tags: list[str] | None = None
    description: str | None = None


class CreateCampaignModel(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(..., min_length=1, max_length=500)
    lists: list[int] = Field(..., min_length=1)
    type: CampaignTypeEnum = CampaignTypeEnum.regular
    from_email: EmailStr | None = None
    body: str | None = None
    content_type: ContentTypeEnum = ContentTypeEnum.richtext
    auto_convert_plain_to_html: bool = True
    altbody: str | None = None
    template_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    send_later: bool | None = None
    send_at: datetime | None = None
    messenger: str | None = None
    headers: list[dict[str, Any]] | None = None

    @field_validator("lists")
    @classmethod
    def validate_lists(cls, value: list[int]) -> list[int]:
        return _positive_ids(value) or []

    @model_validator(mode="after")
    def require_body_or_template(self) -> CreateCampaignModel:
        if not self.body and not self.template_id:
            raise ValueError("Either body or template_id is required")
        return self


class UpdateCampaignModel(BaseModel):
    name: str | None = None
    subject: str | None = None
    lists: list[int] | None = None
    from_email: EmailStr | None = None
    body: str | None = None
    altbody: str | None = None
    template_id: int | None = None
    tags: list[str] | None = None
    send_later: bool | None = None
    send_at: datetime | None = None
    messenger: str | None = None
    content_type: ContentTypeEnum | None = None
    headers: list[dict[str, Any]] | None = None


class CreateTemplateModel(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)
    body_source: str | None = None
    type: TemplateTypeEnum = TemplateTypeEnum.campaign
    is_default: bool = False


class UpdateTemplateModel(BaseModel):
    name: str | None = None
    subject: str | None = None
    body: str | None = None
    body_source: str | None = None
    type: TemplateTypeEnum | None = None
    is_default: bool | None = None


class TransactionalEmailModel(BaseModel):
    template_id: int = Field(..., gt=0)
    subscriber_email: EmailStr | None = None
    subscriber_id: int | None = Field(default=None, gt=0)
    subscriber_emails: list[EmailStr] | None = None
    subscriber_ids: list[int] | None = None
    subscriber_mode: str | None = None
    from_email: EmailStr | None = None
    subject: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    headers: list[dict[str, Any]] | None = None
    messenger: str | None = None
    content_type: ContentTypeEnum = ContentTypeEnum.html
    altbody: str | None = None


class MCPToolResult(BaseModel):
    success: bool
    data: Any | None = None
    error: dict[str, Any] | None = None
    message: str | None = None


class MCPResourceContent(BaseModel):
    uri: str
    mimeType: str = "text/markdown"
    text: str


class SubscriberListResponse(BaseModel):
    results: list[Subscriber]
    query: str = ""
    total: int
    per_page: int
    page: int


class CampaignListResponse(BaseModel):
    results: list[Campaign]
    total: int
    per_page: int
    page: int


class ListListResponse(BaseModel):
    results: list[MailingList]


class TemplateListResponse(BaseModel):
    results: list[Template]


class HealthCheckResponse(BaseModel):
    status: str
    version: str | None = None
    build: str | None = None
