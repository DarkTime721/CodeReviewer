from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage
from ...model_factory import get_model
from ..state import CodeReviewState, Finding, get_input_by_version, resolve_file_path
from ...schemas import invoke_with_retry_llm

class BugFinding(BaseModel):
    description: str = Field(description="Clear explanation of the bug")
    severity: Literal["critical", "high", "medium", "low"] = Field(description="Impact severity of the bug")
    function_name: Optional[str] = Field(default=None, description="Which function contains the bug")
    line_number: int = Field(description="Line number where the bug occurs")
    fix_complexity: Literal['Simple', 'Moderate', 'Complex'] = Field(description="How complex is the fix")
    fix_snippet: Optional[str] = Field(default=None, description="Corrected code snippet. REQUIRED for Simple fixes, null for Moderate/Complex")
    @field_validator('fix_snippet')
    @classmethod
    def fix_snippet_required_for_simple(cls, v, info):
        if info.data.get('fix_complexity') == 'Simple' and not v:
            raise ValueError('fix_snippet is required for Simple fixes')
        return v
    suggestion: str = Field(description="Actionable suggestion to fix the bug")
    confidence: float = Field(ge=0.0, le=1.0, description="confidence in this finding")

class BugAgentOutput(BaseModel):
    findings: list[BugFinding] = Field(
        description="List of bugs found, empty if none"
    )
    summary: str = Field(
        description="One sentence summary of the bug review"
    )

BUG_AGENT_PROMPT = """You are a specialist bug reviewer. Your job is to analyze a code diff and identify potential bugs, logic errors, and edge cases.

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
Carefully analyze the diff and identify any of the following:

### Bug Categories
- **Logic errors**: incorrect conditions, wrong operators, inverted boolean logic
- **Edge cases**: null/None checks missing, empty list handling, zero division
- **Off-by-one errors**: loop bounds, index access, slice ranges
- **Type errors**: incorrect type assumptions, missing type coercion
- **Async issues**: missing await, unhandled coroutines, race conditions
- **Return value errors**: missing return, returning wrong type, implicit None
- **Exception handling**: bare except, swallowed exceptions, missing finally

## Output Instructions
For each bug found, provide:
- `description`: clear explanation of what the bug is
- `severity`: how bad is it
  - `critical`: data loss, security bypass, crashes in normal flow
  - `high`: crashes in edge cases, incorrect results for valid inputs
  - `medium`: crashes only on unusual inputs, minor incorrect behaviour
  - `low`: unlikely edge cases, negligible impact
- `function_name`: which function contains the bug
- `line_number`: exact line number in the current version where the bug exists
- `fix_complexity`: how hard is the fix
  - `Simple`: one or two line change
  - `Moderate`: requires restructuring a block
  - `Complex`: requires rethinking the approach
- `fix_snippet`: a concrete corrected code snippet if possible, otherwise null
- `suggestion`: actionable description of how to fix it
- `confidence`: your confidence in this being a real bug (0.0 - 1.0)

## Rules
- Only report genuine bugs, not style issues (those go to the quality agent)
- If a function was deleted, check if its callers are handled
- For async functions, always check for missing await
- If no bugs are found, return an empty findings list
- Be conservative — a false positive is worse than a missed low confidence bug
- Do not repeat the same bug twice
- Take Retry Context if any into consideration while finalizing your output
- For `Simple` fix_complexity findings, `fix_snippet` is MANDATORY — always provide the corrected code snippet
- For `Moderate` or `Complex` findings, set `fix_snippet` to null
- If a function has been modified, you MUST provide at least one finding or explicitly justify why no issues exist
"""

bug_agent_llm = get_model(role="specialist").with_structured_output(BugAgentOutput)

def bug_agent_node(state: CodeReviewState):

    hints = state['retry_hints'].get('bug', [])
    retry_hints_str = "\n".join(f"- {h}" for h in hints) or "None"
    old_input = get_input_by_version(state['input'], 'old')
    new_input = get_input_by_version(state['input'], 'new')
    file_path = resolve_file_path(new_input) if new_input else "unknown_file"
    past = state.get('past_findings') or {}
    past_str = "\n\n".join(past.get('Bug Detector', [])) or None
    

    try:

        prompt = BUG_AGENT_PROMPT.format(
            language=state['language'] or 'Unknown',
            semantic_magnitude = state['semantic_magnitude'],
            functions_modified = state['functions_modified'] or [],
            functions_added = state['functions_added'] or [],
            functions_deleted = state['functions_deleted'] or [],
            before_content = old_input['content'] if old_input else "",
            after_content = new_input['content'] if new_input else "",
            retry_hints=retry_hints_str,
            past_findings=past_str
        )

    
        result = invoke_with_retry_llm(
            llm=bug_agent_llm,
            messages=[
            SystemMessage("You are a specialist bug reviewer. Analyze the diff and return structured findings."),
            HumanMessage(prompt)
            ]
        )

        findings = [
            Finding(
                agent='Bug detector',
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
