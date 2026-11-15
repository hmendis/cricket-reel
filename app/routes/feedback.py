"""Provide feedback: the redacted bundle."""
from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from .. import feedback

router = APIRouter()


class FeedbackIn(BaseModel):
    message: str = ""
    screen: dict = {}
    match_id: str | None = None
    include: dict[str, bool] = {}


@router.post("/api/feedback")
def save_feedback(body: FeedbackIn):
    """Save a redacted feedback bundle (screen, logs, environment, match data) in the settings folder."""
    return feedback.build(body.message[:5000], body.screen, body.match_id, body.include)


@router.post("/api/feedback/open-folder")
def open_feedback_folder():
    feedback.folder().mkdir(parents=True, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(str(feedback.folder()))  # noqa: S606 - the user's own folder
    return {"folder": str(feedback.folder())}
