from .state import CodeReviewState

def trivial_output_node(state: CodeReviewState):
    return {
        'output_markdown': '## Code Review\n\n**Verdict:** No significant changes detected — review skipped.',
        'output_json': [],
        'output_diff': 'No automated fixes available',
        'judge_verdict': 'PASS',
        'forced': False
    }