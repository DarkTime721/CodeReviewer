import json
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from ..model_factory import get_model
from .state import CodeReviewState
from ..schemas import invoke_with_retry_llm
import logging

logger = logging.getLogger(__name__)

class JudgeOutput(BaseModel):
    coverage: float = Field(ge=0.0, le=1.0, description="How well did agents cover all changed functions and lines")
    accuracy: float = Field(ge=0.0, le=1.0, description="Are the findings factually correct and not false positives")
    severity_weighted: float = Field(ge=0.0, le=1.0, description="Normalized weight of severity across all findings")
    fix_quality: float = Field(ge=0.0, le=1.0, description="How actionable and correct are the fix suggestions")
    consistency: float = Field(ge=0.0, le=1.0, description="Do agents agree where they overlap, no contradictions")
    agent_feedback: dict[str, list[str]] = Field(description="Agent-specific retry hints. Keys must be agent names from: 'bug', 'security', 'quality', 'performance'. Only include agents that need improvement.")
    

JUDGE_PROMPT = """You are a senior code review judge. Your job is to evaluate the quality of findings produced by specialist agents and score them objectively.

## Change Context
- Language: {language}
- Semantic Magnitude: {semantic_magnitude}
- Functions Modified: {functions_modified}
- Functions Added: {functions_added}
- Functions Deleted: {functions_deleted}
- Agents Invoked: {agents_required}

## Current Version
{after_content}

## Agent Findings (JSON format)
{findings}

## Your Task
Score the overall quality of the agent findings across these dimensions:

### Scoring Dimensions
- `coverage` (0.0 - 1.0): Did agents examine all changed functions and lines?
  - 1.0: every changed function has at least one finding or explicit clearance
  - 0.5: some changed functions were ignored
  - 0.0: agents missed the majority of changes

- `accuracy` (0.0 - 1.0): Are the findings factually correct?
  - 1.0: all findings are genuine issues backed by code evidence
  - 0.5: some findings are questionable or misread the code intent
  - 0.0: most findings are false positives

- `severity_weighted` (0.0 - 1.0): What is the normalized severity across findings?
  - 1.0: critical or high severity findings dominate
  - 0.5: mix of medium and low findings
  - 0.0: all findings are low severity or negligible

- `fix_quality` (0.0 - 1.0): How actionable and correct are the suggestions?
  - 1.0: every fix is concrete, correct, and immediately actionable
  - 0.5: some fixes are vague or partially correct
  - 0.0: fixes are missing, wrong, or too generic to act on

- `consistency` (0.0 - 1.0): Do agents agree where they overlap?
  - 1.0: no contradictions, complementary findings
  - 0.5: minor overlaps or redundancies
  - 0.0: agents contradict each other on the same issue

- `agent_feedback`: If findings have gaps or errors, list specific instructions for improvement. Examples:
  - "Bug agent missed negative user_id check in fetch_user"
  - "Quality agent incorrectly flagged valid defensive check as unnecessary"
  - Leave empty if findings are satisfactory

## Rules
- Be objective — score based on evidence in the findings, not assumptions
- A finding that contradicts clear code intent should penalize accuracy
- If all agents returned empty findings on a significant change, coverage must be low
- agent_feedback must be specific enough for an agent to act on, not generic advice
- Findings are provided in JSON format — parse each finding's description, severity, suggestion, and confidence when scoring
- Only include agents in agent_feedback that have genuine gaps or errors in their findings
- If an agent performed well, omit it from agent_feedback entirely — do not include it with an empty list
- agent_feedback keys MUST be agent names only: 'bug', 'security', 'quality', 'performance'
- Never use metric names like 'accuracy', 'coverage' as keys
- Only include agents in agent_feedback that were actually invoked — check Agents Invoked list before adding hints
- Never add retry hints for agents not in the Agents Invoked list

Note: Previous version of the code is provided to the agents, you only have access to the final/current version of the code.
"""

judge_agent_llm = get_model(role="judge").with_structured_output(JudgeOutput)

def judge_node(state: CodeReviewState):

    retry_count = state['retry_count'] or 0
    findings = state['final_findings'] or state['findings'] or []

    try:

        prompt = JUDGE_PROMPT.format(
            language=state['language'] or "Unknown",
            semantic_magnitude=state['semantic_magnitude'],
            functions_modified=state['functions_modified'] or [],
            functions_added=state['functions_added'] or [],
            functions_deleted=state['functions_deleted'] or [],
            agents_required=state['agents_required'],
            after_content=state['input'][-1]['content'],
            findings= json.dumps(
                findings,
                indent=2,
                default=str
            )
        )

        result = invoke_with_retry_llm(
            llm=judge_agent_llm,
            messages=[
            SystemMessage("You are a senior code review judge. Your job is to evaluate the quality of findings produced by specialist agents and score them objectively and return structured findings."),
            HumanMessage(prompt)
            ]
        )

        judge_score = (
          result.coverage * 0.25 +
          result.accuracy * 0.30 +
          result.fix_quality * 0.25 +
          result.consistency * 0.20
        )

        # 'strict_judge' is a parameter that can be passed at invocation time if the user wishes for a higher threshold for complex/security-critical code review
        threshold = 0.85 if state['strict_judge'] else 0.7

        if judge_score > threshold:
            judge_verdict = "PASS"
        elif retry_count >= 1:
            judge_verdict = "FORCE_OUTPUT"
        else:
            retry_count += 1
            judge_verdict = "RETRY"

        return {
        'coverage': result.coverage,
        'accuracy': result.accuracy,
        'severity_weighted': result.severity_weighted,
        'fix_quality': result.fix_quality,
        'consistency': result.consistency,
        'retry_hints': result.agent_feedback,
        'judge_score': judge_score,
        'retry_count': retry_count,
        'judge_verdict': judge_verdict,
        'forced': judge_verdict == 'FORCE_OUTPUT'
    }

    except Exception as e:
        logger.debug(e)
        return {
            'coverage': 0.0,
            'accuracy': 0.0,
            'severity_weighted': 0.0,
            'fix_quality': 0.0,
            'consistency': 0.0,
            'retry_hints': {},
            'judge_score': 0.0,
            'judge_verdict': 'FORCE_OUTPUT',
            'retry_count': retry_count,
            'forced': True
        }
