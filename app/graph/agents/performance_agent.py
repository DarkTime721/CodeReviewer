from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage
from ...model_factory import get_model
from ..state import CodeReviewState, Finding, get_input_by_version, resolve_file_path


class PerformanceFinding(BaseModel):
    description: str = Field(description="Clear explanation of the issue and the performance impact")
    severity: Literal["critical", "high", "medium", "low"] = Field(description="Impact severity cause by the issue")
    function_name: Optional[str] = Field(default=None, description="Which function contains the issue")
    line_number: int = Field(description="Line number where the issue occurs")
    fix_complexity: Literal['Simple', 'Moderate', 'Complex'] = Field(description="How complex is the fix")
    fix_snippet: Optional[str] = Field(default=None, description="Corrected code snippet. REQUIRED for Simple fixes, null for Moderate/Complex")
    @field_validator('fix_snippet')
    @classmethod
    def fix_snippet_required_for_simple(cls, v, info):
        if info.data.get('fix_complexity') == 'Simple' and not v:
            raise ValueError('fix_snippet is required for Simple fixes')
        return v
    suggestion: str = Field(description="Actionable suggestion to fix the issues")
    confidence: float = Field(ge=0.0, le=1.0, description="confidence in this finding")

class PerformanceAgentOutput(BaseModel):
    findings: list[PerformanceFinding] = Field(
        description="List of security performance bottlenecks and inefficiencies found, empty if none"
    )
    summary: str = Field(
        description="One sentence summary of the performance bottlenecks and inefficiencies review"
    )

PERFORMANCE_AGENT_PROMPT = """You are a specialist performance reviewer. Your job is to identify performance bottlenecks and inefficiencies in a code diff.

## Change Context
- Language: {language}
- Semantic Magnitude: {semantic_magnitude}
- Functions Modified: {functions_modified}
- Functions Added: {functions_added}
- Functions Deleted: {functions_deleted}

## Previous Version
{before_content}

## Current Version
{after_content}

## Retry Context (if applicable)
{retry_hints}

## Previously Found Issues (this file, past reviews)
{past_findings}
Note: these may already be fixed in the current version — verify against
the current code before re-flagging something that's no longer there.

## Your Task
Identify any of the following performance issues:

### Performance Categories
- **Complexity**: O(n²) or worse algorithms where better exists
- **Database**: N+1 queries, missing pagination, unindexed lookups
- **Memory**: unnecessary copies, large object retention, unbounded growth
- **I/O**: blocking calls in async context, missing connection pooling
- **Caching**: repeated expensive computation that could be cached
- **Loops**: unnecessary iterations, recomputation inside loops

## Output Instructions
For each issue found, provide:
- `description`: what the issue is and its performance impact
- `severity`: impact level
  - `critical`: will cause timeouts or OOM in production
  - `high`: significant degradation under normal load
  - `medium`: noticeable only under heavy load
  - `low`: minor inefficiency, negligible real-world impact
- `function_name`: which function has the issue
- `line_number`: exact line number in the current version
- `fix_complexity`: how hard is the fix
- `fix_snippet`: optimized code snippet if applicable, otherwise null
- `suggestion`: concrete optimization suggestion
- `confidence`: confidence this is a real performance issue (0.0 - 1.0)

## Rules
- Compare the current version against the previous version — flag cases where 
  the new version is less efficient than what it replaced
- A verbose loop replacing a list comprehension is a performance regression worth flagging
- Only report genuine performance issues, not style preferences
- Be conservative — do not flag micro-optimizations unless they compound
- If no issues found, return empty findings list
- Do not repeat the same issue twice
- Take Retry Context if any into consideration while finalizing your output
- For `Simple` fix_complexity findings, `fix_snippet` is MANDATORY — always provide the corrected code snippet
- For `Moderate` or `Complex` findings, set `fix_snippet` to null
- If a function has been modified, you MUST provide at least one finding or explicitly justify why no issues exist
- Do NOT flag security vulnerabilities as performance issues
- Do NOT flag functional bugs (wrong return value, missing execution) as performance issues  
- Only flag genuine performance bottlenecks — complexity, memory, I/O, caching, loops
"""

performance_agent_llm = get_model(role="specialist").with_structured_output(PerformanceAgentOutput)

def performance_agent_node(state: CodeReviewState):

    hints = state['retry_hints'].get('performance', [])
    retry_hints_str = "\n".join(f"- {h}" for h in hints) or "None"

    old_input = get_input_by_version(state['input'], 'old')
    new_input = get_input_by_version(state['input'], 'new')
    file_path = resolve_file_path(new_input) if new_input else "unknown_file"
    past = state.get('past_findings') or {}
    past_str = "\n\n".join(past.get('Performance', [])) or None

    try:

        prompt = PERFORMANCE_AGENT_PROMPT.format(
            language=state['language'] or 'Unknown',
            semantic_magnitude=state['semantic_magnitude'],
            functions_modified=state['functions_modified'] or [],
            functions_added=state['functions_added']or [],
            functions_deleted=state['functions_deleted'] or [],
            before_content=old_input['content'] if old_input else "",
            after_content=new_input['content'] if new_input else "",
            retry_hints=retry_hints_str,
            past_findings=past_str
        )
        
        result = performance_agent_llm.invoke([
            SystemMessage("You are a specialist performance reviewer. Your job is to identify performance bottlenecks and inefficiencies in a code diff and return structured findings"),
            HumanMessage(prompt)
        ])

        findings = [
            Finding(
                agent='Performance',
                file_path=file_path,
                severity=r.severity,
                description=r.description,
                line_number=r.line_number,
                fix_complexity=r.fix_complexity,
                fix_snippet=r.fix_snippet,
                suggestion=r.suggestion,
                confidence=r.confidence,
                search_term=None,
                propagation_chain=None
            )
            for r in result.findings
        ]

        return {'findings': findings}

    except Exception as e:
        print(e)
        return {'findings': []}
