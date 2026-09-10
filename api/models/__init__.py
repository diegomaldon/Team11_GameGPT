"""Pydantic request/response models — the wire contract for GameGPT.

Every API body and internal DTO lives here so routers, services, and the
frontend's generated types all agree on one shape.
"""

from api.models.schemas import (
    FeedbackRequest,
    GameCandidate,
    LibraryItem,
    LibraryResponse,
    LibrarySyncRequest,
    LibrarySyncResponse,
    Recommendation,
    RecommendRequest,
    RecommendResponse,
    Vote,
)

__all__ = [
    "FeedbackRequest",
    "GameCandidate",
    "LibraryItem",
    "LibraryResponse",
    "LibrarySyncRequest",
    "LibrarySyncResponse",
    "Recommendation",
    "RecommendRequest",
    "RecommendResponse",
    "Vote",
]
