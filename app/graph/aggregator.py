from .state import CodeReviewState


def aggregator_node(state: CodeReviewState):
    seen = set()
    unique_findings = []

    for finding in state['findings']:
        key = (finding['agent'], finding['line_number'], finding['suggestion'][:50])
        if key not in seen:
            seen.add(key)
            unique_findings.append(finding)
    return {'final_findings': unique_findings}
