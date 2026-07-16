from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage
from ...model_factory import get_model
from ..state import CodeReviewState, Finding, get_input_by_version, resolve_file_path
from ...schemas import invoke_with_retry_llm
import logging

logger = logging.getLogger(__name__)

class SecurityFinding(BaseModel):
    description: str = Field(description="Clear explanation of the vulnerability")
    severity: Literal["critical", "high", "medium", "low"] = Field(description="Impact severity of the vulnerability")
    function_name: Optional[str] = Field(default=None, description="Which function contains the vulnerability")
    line_number: int = Field(description="Line number where the vulnerability occurs")
    fix_complexity: Literal['Simple', 'Moderate', 'Complex'] = Field(description="How complex is the fix")
    fix_snippet: Optional[str] = Field(default=None, description="Corrected code snippet. REQUIRED for Simple fixes, null for Moderate/Complex")
    @field_validator('fix_snippet')
    @classmethod
    def fix_snippet_required_for_simple(cls, v, info):
        if info.data.get('fix_complexity') == 'Simple' and not v:
            raise ValueError('fix_snippet is required for Simple fixes')
        return v
    suggestion: str = Field(description="Actionable suggestion to fix the vulnerability")
    confidence: float = Field(ge=0.0, le=1.0, description="confidence in this finding")

class SecurityAgentOutput(BaseModel):
    findings: list[SecurityFinding] = Field(
        description="List of security vulnerabilities found, empty if none"
    )
    summary: str = Field(
        description="One sentence summary of the vulnerability review"
    )


SECURITY_AGENT_PROMPT = """You are a specialist security reviewer. Your job is to identify security vulnerabilities in a code diff.

## Change Context
- Language: {language}
- Semantic Magnitude: {semantic_magnitude}
- Entry Points Detected: {input_scanner}
- Functions Modified: {functions_modified}
- Functions Added: {functions_added}
- Functions Deleted: {functions_deleted}

## Cross-Taint Findings
{findings}

The findings list contains source→sink flows detected by static taint analysis.

Each finding contains:
- source_file
- source_lineno
- source_call
- sink_file
- sink_lineno
- var_name
- score

Interpretation:
- source_call identifies where potentially tainted data originated.
- sink_file/sink_lineno identify where the data reaches a sensitive operation.
- score is a taint-analysis confidence/risk score.
- Findings are indicators of potential security risk, not proof of a vulnerability.

Use these findings as additional context while reviewing the code.
Prioritize investigation of any modified code that participates in a reported source→sink flow.
Verify whether the flow is actually exploitable by examining validation, sanitization, parameterization, escaping, authorization checks, or other mitigations present in the current code before reporting a vulnerability.

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
Identify any of the following vulnerabilities:

### Vulnerability Categories
- **Injection**: SQL, command, LDAP, XPath injection risks
- **Authentication**: broken auth, missing auth checks, hardcoded credentials
- **Input validation**: unsanitized user input, missing bounds checks
- **Sensitive data**: secrets in code, unencrypted sensitive fields, logging PII
- **Access control**: missing permission checks, privilege escalation paths
- **Dependency risks**: unsafe deserialization, insecure direct object reference
- **Async risks**: race conditions, TOCTOU vulnerabilities

## Output Instructions
For each vulnerability found, provide:
- `description`: what the vulnerability is, why it is dangerous, and source→sink flow if cross-file taint exists
- `severity`: impact level
  - `critical`: exploitable without authentication, data breach risk
  - `high`: exploitable with minimal access, significant impact
  - `medium`: requires specific conditions to exploit
  - `low`: minimal exploitability, low impact
- `function_name`: which function contains the vulnerability
- `line_number`: exact line number in the current version
- `fix_complexity`: how hard is the fix
- `fix_snippet`: corrected code snippet if applicable, otherwise null
- `suggestion`: concrete remediation steps
- `confidence`: confidence this is a real vulnerability (0.0 - 1.0)

## Rules
- If entry points are present, always scrutinize input handling
- Hardcoded secrets are always critical regardless of context
- Do not report style or performance issues
- If no vulnerabilities found, return empty findings list
- Do not repeat the same vulnerability twice
- Take Retry Context if any into consideration while finalizing your output
- For `Simple` fix_complexity findings, `fix_snippet` is MANDATORY — always provide the corrected code snippet
- For `Moderate` or `Complex` findings, set `fix_snippet` to null
- If a function has been modified, you MUST provide at least one finding or explicitly justify why no issues exist
"""

security_agent_llm = get_model(role="specialist").with_structured_output(SecurityAgentOutput)

def security_agent_node(state: CodeReviewState):

    hints = state['retry_hints'].get('security', [])
    retry_hints_str = "\n".join(f"- {h}" for h in hints) or "None"

    old_input = get_input_by_version(state['input'], 'old')
    new_input = get_input_by_version(state['input'], 'new')
    file_path = resolve_file_path(new_input) if new_input else "unknown_file"
    past = state.get('past_findings') or {}
    past_str = "\n\n".join(past.get('Security', [])) or None

    try:

        prompt = SECURITY_AGENT_PROMPT.format(
            language=state['language'] or 'Unknown',
            semantic_magnitude=state['semantic_magnitude'],
            input_scanner=state['input_scanner'],
            functions_modified=state['functions_modified'] or [],
            functions_added=state['functions_added']or [],
            functions_deleted=state['functions_deleted'] or [],
            findings = state['cross_file_findings'] or [],
            before_content=old_input['content'] if old_input else "",
            after_content=new_input['content'] if new_input else "",
            retry_hints=retry_hints_str,
            past_findings=past_str
        )

        result = invoke_with_retry_llm(
            llm=security_agent_llm,
            messages=[
            SystemMessage("You are a specialist security reviewer. Your job is to identify security vulnerabilities in a code diff and return structured findings."),
            HumanMessage(prompt)
            ]
        )

        findings = [
            Finding(
                agent='Security',
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
