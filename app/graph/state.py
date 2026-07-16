from typing import TypedDict, Literal, Optional, Annotated
import operator

def merge_retry_hints(old: dict, new: dict) -> dict:
    return {**old, **new}

class Question(TypedDict):
    target_agent: Optional[Literal['Bug detector', 'Security', 'Code quality', 'Performance']]
    focus: Optional[str]
    findings_addressed: Optional[bool]

class InputScanner(TypedDict):
    function: Optional[str]
    parameter: Optional[str]
    type: Optional[Literal['Request', 'Query', 'Body', 'Other']]
    line_number: int

class Finding(TypedDict):
    agent: Optional[Literal['Security', 'Bug detector', 'Code quality', 'Performance']]
    file_path: str
    severity: Optional[Literal["critical", "high", "medium", "low"]]
    description: str
    line_number: int
    fix_complexity: Optional[Literal['Simple', 'Moderate', 'Complex']]
    fix_snippet: str | None
    suggestion: str
    search_term: str | None
    confidence: float

class Input(TypedDict):
    version: Literal['old', 'new']
    file: str
    file_directory: str
    content: str
    filename: Optional[str]

def get_input_by_version(inputs: list['Input'], version: Literal['old', 'new']) -> Optional['Input']:
    """Find the old or new Input entry by its explicit tag instead of trusting
    list position. Returns None if no entry carries that tag, so callers can
    fail loudly/gracefully instead of silently reading the wrong file version."""

    return next((inp for inp in inputs if inp.get('version') == version), None)


def resolve_file_path(input_item: 'Input') -> str:
    """Best-effort unique identifier for the file an Input entry refers to.
    Input has three overlapping fields (file, file_directory, filename) and
    callers have been inconsistent about which they populate, so this picks
    the most specific one available rather than assuming a single field is
    always set."""

    if input_item.get('file'):
        return input_item['file']
    directory = input_item.get('file_directory')
    filename = input_item.get('filename')
    if directory and filename:
        return f"{directory}/{filename}"
    return filename or directory or "unknown_file"    

class CodeReviewState(TypedDict):

    # UUID 
    id: Optional[str]

    # Identifies which project/repo this run belongs to. Drives the ChromaDB
    # collection name in memory_writer / memory_reader. Set this at invoke 
    # time — start_node deliberately does NOT reset this field, since it's
    # caller-supplied per run rather than generated like `id`.
    repo_id: Optional[str]

    # Added for cross-file taint tracing to work using GitHub URLs instead of the system just relying on local paths
    repo_url_fetch: Optional[str]

    # Added for managing the imports if any [for cross-file taint tracking] using the SHA and GitHub API to provide the tree of the repo (every path)
    repo_tree: Optional[set[str]]

    head_sha: Optional[str]
    
    # Input
    input: Annotated[list[Input], operator.add]

    # Agent router
    agents_required: Optional[list[Literal['bug', 'security', 'quality', 'performance', 'cross_file']]]

    # Map production regarding how all the files relate
    system_map: Optional[dict]

    language: Optional[Literal['Python', 'JavaScript/TypeScript', 'Java', 'C/C++', 'Go', 'Rust']]
    router_decision: Optional[Literal['trivial', 'moderate', 'complex']]

    # Diff and AST Parser
    lines_changed: int
    percent_changed: float
    functions_added: Optional[list[str]]
    functions_deleted: Optional[list[str]]
    functions_modified: Optional[list[str]]
    structural_type: Optional[Literal['trivial', 'moderate', 'complex']]
    input_scanner: Annotated[list[InputScanner], operator.add]

    # LLM fields
    explanation: Optional[str]
    semantic_magnitude: float
    audit_check: Annotated[list[Question], operator.add]

    # Judge Node
    coverage: Optional[float]
    accuracy: Optional[float]
    severity_weighted: Optional[float]
    fix_quality: Optional[float]
    consistency: Optional[float]
    judge_score: Optional[float]
    judge_verdict: Optional[Literal["PASS", "RETRY", "FORCE_OUTPUT"]]
    retry_count: Optional[int]
    retry_hints: Annotated[dict, merge_retry_hints]
    forced: Optional[bool]
    strict_judge: Optional[bool]

    # Memory output sections
    previously_found: Optional[str]
    past_findings: Optional[dict[str, list[str]]]
    resolved_since_last: Optional[str]
    trend : Optional[Literal['improving', 'stable', 'degrading']]

    # Added to avoid errors in case the main files to check have Syntax Error
    # If the main file cannot be parsed, there is no use of calling any agent to check as the main file/code has a major flaw (SyntaxError)
    parse_error: Optional[str]

    # Cross-file findings
    cross_file_findings: Optional[list[dict]]
    unresolved_imports: Optional[list[dict]]

    # Agent findings
    findings: Annotated[list[Finding], operator.add]
    final_findings: Optional[list[Finding]]

    # Output
    output_json: Optional[dict]
    output_diff: Optional[str]
    output_markdown: Optional[str]