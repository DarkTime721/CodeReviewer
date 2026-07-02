from pydantic import BaseModel, Field
from typing import Literal

class FileEntry(BaseModel):
    version: Literal['new', 'old']
    content: str
    file: str

class ReviewRequest(BaseModel):
    repo_id: str
    input: list[FileEntry]
