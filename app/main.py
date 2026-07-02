from .graph.graph_builder import graph
from .schemas import ReviewRequest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uuid

def stream_review(repo_id: str, input_files: list[dict]):
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    for token_chunk, metadata in graph.stream(
        {'repo_id': repo_id, 'input': input_files},
        config=config,
        stream_mode="messages"
    ):
        if metadata.get("langgraph_node") == "output_formatter":
            yield token_chunk.content

app = FastAPI()

@app.post("/review")
def review(request: ReviewRequest):
    return StreamingResponse(
        stream_review(repo_id=request.repo_id, input_files=[f.model_dump() for f in request.input]),
        media_type="text/plain"
    )