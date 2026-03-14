from pydantic import BaseModel
from datetime import datetime


class ModelResult(BaseModel):
    model_id: str
    pipeline_tag: str
    likes: int
    downloads: int
    created_at: datetime
    url: str
    author: str
    description: str | None = None


class IncomingMessage(BaseModel):
    jid: str
    sender: str
    text: str
    quotedMessageId: str | None = None
    quotedText: str | None = None
