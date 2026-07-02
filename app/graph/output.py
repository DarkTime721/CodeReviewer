from langchain_core.messages import HumanMessage, SystemMessage
from ..model_factory import get_model
from .state import CodeReviewState
import json


OUTPUT_DIFF_PROMPT = """You are a code diff generator. Your job is to produce a clean unified diff based on the findings from a code review.

## Current Version
{after_content}

## Simple Findings With Fixes
{simple_findings}

## Your Task
Generate a unified diff in standard format that applies all the simple fixes from the findings above.

## Rules
- Only include changes that correspond to a finding with a fix_snippet
- Follow standard unified diff format exactly (--- a/, +++ b/, @@ ... @@)
- Do not invent fixes that are not in the findings
- If two fixes affect the same lines, merge them cleanly
- If no simple findings exist, return an empty string
"""

output_diff_llm = get_model(role="specialist")

def output_formatter(state: CodeReviewState):

    findings = state['final_findings'] or state['findings'] or []
    simple_findings = [f for f in findings if f['fix_complexity'] == 'Simple' and f['fix_snippet']]

    try:
        if not simple_findings:
            output_diff = 'No automated fixes available — review suggestions manually.'
        else:
            prompt_diff = OUTPUT_DIFF_PROMPT.format(
                after_content=state['input'][-1]['content'],
                simple_findings=json.dumps(simple_findings, indent=2, default=str)
            )
            output_diff = output_diff_llm.invoke([
                SystemMessage("You are a code diff generator which produces clean unified diff based on findings of the code review."),
                HumanMessage(prompt_diff)
            ]).content

        findings_json = json.dumps(findings, indent=2, default=str)

        output_markdown = output_diff_llm.invoke([
            SystemMessage('You are a markdown generator which reads the findings of agents [JSON format] along with judge verdict and generates a structured output of the findings in markdown format.'),
            HumanMessage(
                f"""
                ## Code Change Summary
                - Language: {state['language']}
                - Lines Changed: {state['lines_changed']} ({state['percent_changed']}%)
                - Functions Modified: {state['functions_modified']}
                - Functions Added: {state['functions_added']}
                - Agents Invoked: {state['agents_required']}

                ## Judge Evaluation
                - Judge Score: {state['judge_score']}
                - Judge Verdict: {state['judge_verdict']}
                - Coverage: {state['coverage']}
                - Accuracy: {state['accuracy']}
                - Fix Quality: {state['fix_quality']}
                - Consistency: {state['consistency']}
                - Retry Count: {state['retry_count']}
                - Forced Output: {state['forced']}

                ## Unresolved imports from the Cross-Taint Analysis
                - {state['unresolved_imports'] or "None"}

                ## Findings (JSON)
                {findings_json}

                ## NOTE:
                If 'Unresolved imports from the Cross-Taint Analysis' section has some values, 
                make sure to include a note that manual review of the unresolved imports is needed.
                """
            )
        ]).content

        return {
            'output_json': findings,
            'output_diff': output_diff,
            'output_markdown': output_markdown
        }

    except Exception as e:
        print(e)
        return {
            'output_json': "Error occured while generating findings",
            'output_diff': "Error occured while generating findings",
            'output_markdown': "Error occured while generating findings"
        }