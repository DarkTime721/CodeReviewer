from .graph.graph_builder import graph
from .schemas import GitReviewInfo, construct_review_req, GitHubPermanentError, GitHubRateLimitError, ConfigurationError, InvalidRequestError
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import uuid
from collections import defaultdict


def stream_review(repo_id: str, input_dict: dict, failed_files: dict, repo_url_fetch: str, repo_tree: set[str], head_sha: str):
    if failed_files:
        for f in failed_files:
            yield f"""Failed:\n{f}\n{failed_files[f]}"""
            yield "\n\n------\n\n"
    for file in input_dict:
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}

        yield f"\n\n--- {file} ---\n\n"
        for token_chunk, metadata in graph.stream(
            {'repo_id': repo_id, 'input': [f.model_dump() for f in input_dict[file]], 'repo_url_fetch': repo_url_fetch, 'repo_tree': repo_tree, 'head_sha': head_sha},
            config=config,
            stream_mode="messages"
        ):
            if metadata.get("langgraph_node") == "output_formatter":
                yield token_chunk.content

app = FastAPI()

@app.post("/review")
def review(info: GitReviewInfo):
    try:
        request = construct_review_req(url=info.github_url, pull_number=info.pull_number)
    except GitHubPermanentError as e:
        raise HTTPException(status_code=e.status_code, detail=f"{e.args[0]} (url: {e.url})")
    except GitHubRateLimitError as e:
        raise HTTPException(status_code=503, detail=f"{e.args[0]} (url: {e.url})")
    except ConfigurationError as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    except InvalidRequestError as e:
        raise HTTPException(status_code=400, detail=f"Error: {str(e)}")
    
    grouped_by_filename = defaultdict(list)
    for entry in request.input:
        grouped_by_filename[entry.file].append(entry)
    
    return StreamingResponse(
        stream_review(repo_id=request.repo_id, input_dict=grouped_by_filename, failed_files=request.failed_files, repo_url_fetch=request.repo_url_fetch, repo_tree=request.repo_tree, head_sha=request.head_sha),
        media_type="text/plain"
    )