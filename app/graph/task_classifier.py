from ..model_factory import get_model
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import HumanMessage, SystemMessage
from .state import CodeReviewState, get_input_by_version


class TaskClassifier(BaseModel):
    semantic_magnitude: float = Field(
        ge=0.0, le=1.0,
        description="How significant is this change, 0.0 trivial to 1.0 critical"
        )
    agents_required: list[Literal['bug', 'security', 'quality', 'performance']] = Field(
        ...,
        description="Which specialist agents must review this change")
    explanation: str = Field(
        ...,
        description="One to two sentences explaining why these agennts were selected"
    )
    

TASK_CLASSIFIER_PROMPT = """
## Change Summary
- Language: {language}
- Lines changed: {lines_changed} ({percent_changed}%)
- Structural type: {structural_type}
- Functions added: {functions_added}
- Functions modified: {functions_modified}
- Functions deleted: {functions_deleted}
- Entry points detected: {input_scanner}

## Diff Content
{diff_content}

## Retry Context (if applicable)
{retry_hints}

## Cross-Taint Analysis
{findings}


## Your Task
Based on the change summary and diff, determine:

1. `semantic_magnitude` (0.0 - 1.0): How significant is this change overall?
   0.0 - 0.2: cosmetic only — renaming, formatting, comments
    0.2 - 0.5: new utility functions, minor logic additions with no edge case risk
    0.5 - 0.8: modified existing behaviour, new async functions, added validation logic
    0.8 - 1.0: new entry points, auth logic, data flow changes, deletions

2. `agents_required`: Which agents must review this? Choose from:
   - `bug`: logic errors, edge cases, null checks, off-by-one
   - `security`: entry points, auth, input validation, injection risk
   - `quality`: readability, naming, structure, duplication
   - `performance`: loops, DB calls, caching, complexity
   - `cross_file`: imports changed, shared utilities modified, interface changes

3. `explanation`: One sentence explaining why these agents were selected.

## Rules
- Always include at least one agent
- If entry points are present, security is mandatory
- If functions are deleted, bug is mandatory
- If functions are modified, bug is mandatory
- If async functions are added, include bug
- If cross-taint analysis reports any source→sink flow, security is mandatory
- If a new source or sink was introduced, security is mandatory
- Taint findings are a strong signal and should be weighted heavily when selecting reviewers
- Be conservative — only add performance if there is a genuine signal
- Take retry_hints if any into consideration while finalizing your output
- If a function was modified and the change affects iteration patterns, loops, or data structures, include performance but make sure that it is a genuine signal

## Notes

Each taint finding represents a detected flow from a source to a sink and contains:
- source_file / source_lineno
- sink_file / sink_lineno
- source_call
- var_name
- score

A taint flow is a security signal, not proof of a vulnerability.
"""

task_classifier_llm = get_model(role="classifier").with_structured_output(TaskClassifier)

def task_classifier_node(state: CodeReviewState):

    new_input = get_input_by_version(state['input'], 'new')
    diff_content = new_input['content'] if new_input else ''

    hints = state['retry_hints'] or {}

    retry_hints_str = "\n".join(
        f"- [{agent}]: {hint}"
        for agent, hints_list in hints.items()
        for hint in hints_list
    ) or "None"

    input_scanner_str = "\n".join(
        f"  - {sc.get('route', 'unknown')} [{sc.get('method', '')}]"
        for sc in state["input_scanner"]
    ) or "None"

    try:

        prompt = TASK_CLASSIFIER_PROMPT.format(
            language=state["language"] or "Unknown",
            lines_changed=state["lines_changed"],
            percent_changed=state["percent_changed"],
            structural_type=state["structural_type"],
            functions_added=state["functions_added"] or [],
            functions_modified=state["functions_modified"] or [],
            functions_deleted=state["functions_deleted"] or [],
            input_scanner= input_scanner_str or "",
            diff_content=diff_content,
            retry_hints=retry_hints_str,
            findings = state['cross_file_findings'] or [],
        )

        result = task_classifier_llm.invoke([
            SystemMessage("You are a code review classifier. Your job is to analyze a code diff and determine which specialist reviewers are needed."),
            HumanMessage(prompt)
        ])

        """agents = result.agents_required

        if state['input_scanner'] and 'security' not in agents:
            agents.append('security')

        if state["functions_modified"] and "bug" not in agents:
            agents.append("bug")

        if state["functions_added"] and "bug" not in agents:
            agents.append("bug")
        
        if state["functions_modified"] and "performance" not in agents:
            # checking if semantic_magnitude warrants it
            if result.semantic_magnitude >= 0.4:
                agents.append("performance")"""

        return {
            'semantic_magnitude': result.semantic_magnitude,
            'agents_required': result.agents_required,
            'explanation': result.explanation
        }
    
    except Exception as e:
        print(e)
        return {
        'semantic_magnitude': 0.8,
        'agents_required': ['bug', 'security', 'quality', 'performance'],
        'explanation': 'Classifier failed, defaulting to full review'
    }
