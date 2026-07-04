from typing import Optional, Annotated

from pydantic import BaseModel, Field, ConfigDict


Slug = Annotated[str, Field(pattern="^[a-z0-9-]+$", max_length=50)]
HttpsUrl = Annotated[str, Field(pattern="^https://", examples=["https://hooks.zapier.com/hooks/catch/..."])]


class RouteCreate(BaseModel):
    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination_url: HttpsUrl
    method: str = Field(default="POST", pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    headers: dict[str, str] = Field(default_factory=dict)


class RouteUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    destination_url: Optional[HttpsUrl] = None
    method: Optional[str] = Field(None, pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    headers: Optional[dict[str, str]] = None
    is_active: Optional[bool] = None


class RouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    slug: Slug
    destination_url: HttpsUrl
    method: str
    headers: dict[str, str]
    is_active: bool
    requests_count: int
    last_used_at: Optional[str] = None
    created_at: str
    updated_at: str


class WebhookLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: str
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: str


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: Optional[str] = None
    created_at: str


class UserCreate(BaseModel):
    model_config = ConfigDict(strict=True, str_strip_whitespace=True)

    email: str = Field(..., pattern="^[^@]+@[^@]+\\.[^@]+$")
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=100)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
