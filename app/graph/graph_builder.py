from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from .state import CodeReviewState
from .start_node import start_node
from ..memory import memory_reader, memory_writer
from .parsers import diff_parser, ast_parser
from ..taint.taint_tracker import cross_file_tracer_node
from .task_classifier import task_classifier_node
from .agents.bug_agent import bug_agent_node
from .agents.security_agent import security_agent_node
from .agents.quality_agent import quality_agent_node
from .agents.performance_agent import performance_agent_node
from ..routers import agent_dispatcher, judge_router, confidence_router
from .aggregator import aggregator_node
from .judge import judge_node
from .trivial_output import trivial_output_node
from .output import output_formatter


checkpointer = MemorySaver()

main_graph = StateGraph(CodeReviewState)
main_graph.add_node('start', start_node)
main_graph.add_node('memory_reader', memory_reader)
main_graph.add_node('diff_parser', diff_parser)
main_graph.add_node('ast_parser', ast_parser)
main_graph.add_node('cross-taint', cross_file_tracer_node)
main_graph.add_node('task_classifier', task_classifier_node)
main_graph.add_node('agent_dispatcher', agent_dispatcher)
main_graph.add_node('bug_agent', bug_agent_node)
main_graph.add_node('security_agent', security_agent_node)
main_graph.add_node('quality_agent', quality_agent_node)
main_graph.add_node('performance_agent', performance_agent_node)
main_graph.add_node('trivial_output_node', trivial_output_node)
main_graph.add_node('aggregator', aggregator_node)
main_graph.add_node('judge_agent', judge_node)
main_graph.add_node('output_formatter', output_formatter)
main_graph.add_node('memory_writer', memory_writer)

main_graph.add_edge(START, 'start')
main_graph.add_edge('start', 'diff_parser')
main_graph.add_edge('diff_parser', 'ast_parser')
main_graph.add_edge('ast_parser', 'memory_reader')
main_graph.add_edge('memory_reader', 'cross-taint')
main_graph.add_edge('cross-taint', 'task_classifier')
main_graph.add_edge('task_classifier', 'agent_dispatcher')
main_graph.add_conditional_edges('agent_dispatcher',confidence_router)
main_graph.add_edge('bug_agent', 'aggregator')
main_graph.add_edge('security_agent', 'aggregator')
main_graph.add_edge('quality_agent', 'aggregator')
main_graph.add_edge('performance_agent', 'aggregator')
main_graph.add_edge('aggregator', 'judge_agent')
main_graph.add_edge('trivial_output_node', 'memory_writer')
main_graph.add_conditional_edges(
    'judge_agent',
    judge_router,
    {
        'PASS': 'output_formatter',
        'RETRY': 'agent_dispatcher',
        'FORCE_OUTPUT': 'output_formatter'
    }
)
main_graph.add_edge('output_formatter', 'memory_writer')
main_graph.add_edge('memory_writer', END)

graph = main_graph.compile(checkpointer = checkpointer)