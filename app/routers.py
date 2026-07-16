from langgraph.types import Send
from .graph.state import CodeReviewState


def agent_dispatcher(state: CodeReviewState):
    return {}


def confidence_router(state: CodeReviewState):
    agents_required = state['agents_required']
    semantic_magnitude = state['semantic_magnitude']
    routes = []

    # Updated `trivial_output_node` to pass when the state's `parse_error` field is populated.
    if state['semantic_magnitude']  < 0.3 or state.get('parse_error'):
        return [Send('trivial_output_node', state)]
    
    if semantic_magnitude > 0.8:
        agents_required = ['bug', 'security', 'quality', 'performance']

    agent_node_map = {
        'bug': 'bug_agent',
        'security': 'security_agent',
        'quality': 'quality_agent',
        'performance': 'performance_agent',
        'cross_file': 'cross_file_agent'
    }
    
    for agent in agents_required:
        if agent in agent_node_map:
            routes.append(Send(agent_node_map[agent], state))

    return routes


def judge_router(state: CodeReviewState):
    return state['judge_verdict']
