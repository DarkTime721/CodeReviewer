from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage
from ...model_factory import get_model
from ..state import CodeReviewState, Finding, get_input_by_version, resolve_file_path
from ...schemas import invoke_with_retry_llm
import logging

logger = logging.getLogger(__name__)

class QualityFinding(BaseModel):
    description: str = Field(description="Clear explanation of the issues")
    severity: Literal["critical", "high", "medium", "low"] = Field(description="Impact severity of the issue")
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

class QualityAgentOutput(BaseModel):
    findings: list[QualityFinding] = Field(
        description="List of security vulnerabilities found, empty if none"
    )
    summary: str = Field(
        description="One sentence summary of the vulnerability review"
    )

QUALITY_AGENT_PROMPT = """You are a specialist code quality reviewer. Your job is to identify readability, maintainability, and structural issues in a code diff.

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
Identify any of the following quality issues:

### Quality Categories
- **Naming**: unclear variable/function names, inconsistent conventions
- **Structure**: functions doing too much, deep nesting, long parameter lists
- **Duplication**: repeated logic that should be extracted
- **Documentation**: missing docstrings, misleading comments, outdated docs
- **Dead code**: unused variables, unreachable branches, leftover debug code
- **Complexity**: overly complex logic that could be simplified
- **Consistency**: inconsistent patterns with the rest of the codebase

## Output Instructions
For each issue found, provide:
- `description`: what the issue is and why it matters
- `severity`: impact on maintainability
  - `high`: significantly harms readability or future maintainability
  - `medium`: noticeable issue, worth fixing soon
  - `low`: minor nitpick, fix when convenient
- `function_name`: which function has the issue
- `line_number`: exact line number in the current version
- `fix_complexity`: how hard is the fix
- `fix_snippet`: improved code snippet if applicable, otherwise null
- `suggestion`: concrete improvement suggestion
- `confidence`: confidence this is a genuine quality issue (0.0 - 1.0)

## Rules
- Do not report bugs or security issues (those go to other agents)
- Focus on what a senior engineer would flag in a code review
- If no issues found, return empty findings list
- Do not repeat the same issue twice
- `critical` severity does not exist for quality issues — max is `high`
- Take Retry Context if any into consideration while finalizing your output
- For `Simple` fix_complexity findings, `fix_snippet` is MANDATORY — always provide the corrected code snippet
- For `Moderate` or `Complex` findings, set `fix_snippet` to null
- If a function has been modified, you MUST provide at least one finding or explicitly justify why no issues exist
"""

quality_agent_llm = get_model(role="specialist").with_structured_output(QualityAgentOutput)

def quality_agent_node(state: CodeReviewState):

    hints = state['retry_hints'].get('quality', [])
    retry_hints_str = "\n".join(f"- {h}" for h in hints) or "None"

    old_input = get_input_by_version(state['input'], 'old')
    new_input = get_input_by_version(state['input'], 'new')
    file_path = resolve_file_path(new_input) if new_input else "unknown_file"
    past = state.get('past_findings') or {}
    past_str = "\n\n".join(past.get('Code quality', [])) or None

    try:

        prompt = QUALITY_AGENT_PROMPT.format(
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

        result = invoke_with_retry_llm(
            llm=quality_agent_llm,
            messages=[
            SystemMessage("You are a specialist code quality reviewer. Your job is to identify readability, maintainability, and structural issues in a code diff and return structured findings"),
            HumanMessage(prompt)
            ]
        )

        findings = [
            Finding(
                agent='Code quality',
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
        logger.debug(e)
        return {'findings': []}
