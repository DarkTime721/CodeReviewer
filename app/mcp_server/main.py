from fastmcp import FastMCP, Context
from pydantic import BaseModel
from fastmcp.exceptions import ToolError
from collections import defaultdict
import uuid
import asyncio
import logging
import sys

# Logging added to replace the print statements in the files so JSON-RPC odes not get contaminated with the print statements
logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Imported to resolve the top level packages to make the server self-contained
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.graph.graph_builder import graph
from app.schemas import construct_review_req, GitHubPermanentError, GitHubRateLimitError, ConfigurationError, InvalidRequestError, FileEntry
from app.graph.state import CodeReviewState
from app.taint.taint_tracker import cross_file_tracer_node

mcp = FastMCP("CodeReviewer")

class FileReview(BaseModel):
    findings_json: str
    output_diff: str
    output_markdown: str

class ReviewResult(BaseModel):
    findings: list[FileReview]
    failed_files: dict[str, str] | None = None

class CrossFileTaint(BaseModel):
    file_name: str
    cross_file_findings: list[dict]
    unresolved_imports: list[dict] | None = None

class CrossFileResult(BaseModel):
    findings: list[CrossFileTaint]
    failed_traces: dict[str, str] | None = None


async def cross_file_taint(
        file: str,
        entries: list[FileEntry],
        repo_id: str,
        repo_url: str, 
        head_sha: str,
        repo_tree: set[str],
        semaphore: asyncio.Semaphore,
        ctx: Context,
        total: int,
        counter: list[int]
) -> CrossFileTaint:
    try:
        async with semaphore:
            state = CodeReviewState(
                id=file,
                repo_url_fetch=repo_url,
                repo_id=repo_id,
                head_sha=head_sha,
                input=[f.model_dump() for f in entries],
                repo_tree=repo_tree,
            )

            result = await asyncio.to_thread(
                cross_file_tracer_node,
                state,
            )

        return CrossFileTaint(
            file_name=file,
            cross_file_findings=result.get('cross_file_findings', None),
            unresolved_imports=result.get('unresolved_imports', None),
        )

    finally:
        counter[0] += 1
        await ctx.report_progress(
            progress=counter[0],
            total=total,
        )


async def cross_file_loop(
        repo_id: str, 
        input_dict: dict,
        repo_url: str, 
        repo_tree: set[str], 
        head_sha: str,
        ctx: Context
) -> CrossFileResult:
    counter = [0]
    semaphore = asyncio.Semaphore(3)
    total = len(input_dict)

    tasks = [
        cross_file_taint(file=file, entries=entries, repo_id=repo_id, repo_url=repo_url, head_sha=head_sha, repo_tree=repo_tree, semaphore=semaphore, ctx=ctx, total=total, counter=counter)
        for file, entries in input_dict.items()
    ]

    cross_file_reviews = await asyncio.gather(*tasks, return_exceptions=True)

    successful_traces : list[CrossFileTaint] = []
    failed_traces : dict = {}

    for (file, _), result in zip(input_dict.items(), cross_file_reviews):
        if isinstance(result, Exception):
            failed_traces[file] = str(result)
        else:
            successful_traces.append(result)

    return CrossFileResult(
        findings=successful_traces,
        failed_traces=failed_traces
    )


@mcp.tool
async def check_cross_file_taint(github_url: str, pull_no: str, ctx: Context) -> CrossFileResult:
    try:
        request = construct_review_req(url=github_url, pull_number=pull_no)
    except GitHubPermanentError as e:
        raise ToolError(f"Error: {e.args[0]} (url: {e.url})")
    except GitHubRateLimitError as e:
        raise ToolError(f"Error: {e.args[0]} (url: {e.url})")
    except ConfigurationError as e:
        raise ToolError(f"Error: {str(e)}")
    except InvalidRequestError as e:
        raise ToolError(f"Error: {str(e)}")
    
    grouped_by_filename = defaultdict(list)
    for entry in request.input:
        grouped_by_filename[entry.file].append(entry)

    return await cross_file_loop(
        repo_id=request.repo_id,
        input_dict=grouped_by_filename,
        repo_url=request.repo_url_fetch,
        head_sha=request.head_sha,
        repo_tree=request.repo_tree,
        ctx=ctx
    )

    

async def review_loop(
        repo_id: str, 
        input_dict: dict, 
        failed_files: dict, 
        repo_url: str, 
        repo_tree: set[str], 
        head_sha: str,
        ctx: Context
) -> ReviewResult:
    counter = [0]
    semaphore = asyncio.Semaphore(3)
    total = len(input_dict)

    tasks = [
        review_single_file(file=file, entries=entries, repo_id=repo_id, repo_url=repo_url, head_sha=head_sha, repo_tree=repo_tree, semaphore=semaphore, ctx=ctx, total=total, counter=counter)
        for file, entries in input_dict.items()
    ]

    file_reviews = await asyncio.gather(*tasks, return_exceptions=True)

    successful_reviews: list[FileReview] = []

    for (file, _), result in zip(input_dict.items(), file_reviews):
        if isinstance(result, Exception):
            failed_files[file] = str(result)
        else:
            successful_reviews.append(result)

    return ReviewResult(findings=successful_reviews, failed_files=failed_files)

"""

    for i, file in enumerate(input_dict):
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        state = await graph.ainvoke({
            'repo_id': repo_id,
            'input': [f.model_dump() for f in input_dict[file]],
            'repo_url_fetch': repo_url,
            'repo_tree': repo_tree,
            'head_sha': head_sha
        }, config = config)

        review.findings.append(
            FileReview(
                findings_json=state['output_json'],
                output_diff=state['output_diff'],
                output_markdown=state['output_markdown']
            )
        )

        await ctx.report_progress(progress= i+1, total=total)

    return review

"""

async def review_single_file(
        file: str,
        entries: list[FileEntry],
        repo_id: str,
        repo_url: str, 
        head_sha: str,
        repo_tree: set[str],
        semaphore: asyncio.Semaphore,
        ctx: Context,
        total: int,
        counter: list[int],
) -> FileReview:
    async with semaphore:
        config = {'configurable': {'thread_id': str(uuid.uuid4())}}
        state = await graph.ainvoke({
            'repo_id': repo_id,
            'input': [f.model_dump() for f in entries],
            'repo_url_fetch': repo_url,
            'repo_tree': repo_tree,
            'head_sha': head_sha
        }, config = config)

        file_review = FileReview(
            findings_json=state['output_json'],
            output_diff=state['output_diff'],
            output_markdown=state['output_markdown']
        )

    counter[0] += 1
    await ctx.report_progress(progress=counter[0], total=total)

    return file_review 

@mcp.tool
async def review_pr(github_url: str, pull_no: str, ctx: Context) -> ReviewResult:
    try:
        request = construct_review_req(url=github_url, pull_number=pull_no)
    except GitHubPermanentError as e:
        raise ToolError(f"Error: {e.args[0]} (url: {e.url})")
    except GitHubRateLimitError as e:
        raise ToolError(f"Error: {e.args[0]} (url: {e.url})")
    except ConfigurationError as e:
        raise ToolError(f"Error: {str(e)}")
    except InvalidRequestError as e:
        raise ToolError(f"Error: {str(e)}")
    
    grouped_by_filename = defaultdict(list)
    for entry in request.input:
        grouped_by_filename[entry.file].append(entry)

    return await review_loop(
        repo_id=request.repo_id,
        input_dict=grouped_by_filename,
        failed_files=request.failed_files,
        repo_url=request.repo_url_fetch,
        head_sha=request.head_sha,
        repo_tree=request.repo_tree,
        ctx=ctx
    )

if __name__ == "__main__":
    mcp.run(transport="stdio")

# Was using `streamable-http` for MCP inspector but changed to `stdio` for easier Claude desktop integration
