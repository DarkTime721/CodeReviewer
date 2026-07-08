import difflib
from typing import Literal, Optional
import ast
from .state import CodeReviewState, Input, get_input_by_version, resolve_file_path
from pathlib import Path

EXTENSION_MAP = {
    '.py': 'Python',
    '.js': 'JavaScript/TypeScript',
    '.ts': 'JavaScript/TypeScript',
    '.jsx': 'JavaScript/TypeScript',
    '.tsx': 'JavaScript/TypeScript',
    '.java': 'Java',
    '.c': 'C/C++',
    '.cpp': 'C/C++',
    '.h': 'C/C++',
    '.hpp': 'C/C++',
    '.go': 'Go',
    '.rs': 'Rust',
}

def detect_language(inputs: list[Input]) -> Optional[str]:
    detected = set()
    for inp in inputs:
        if inp.get('filename'):
            ext = Path(inp['filename']).suffix.lower()
            if ext in EXTENSION_MAP:
                detected.add(EXTENSION_MAP[ext])
        
    if len(detected) == 1:
        return detected.pop()
    elif len(detected) == 0:
        return None
    else: 
        return None


def _classify(percent_changed: float, lines_changed: int) -> Literal["trivial", "moderate", "complex"]:
    if percent_changed < 10 and lines_changed <= 10:
        return "trivial"
    if percent_changed < 40 and lines_changed <= 100:
        return "moderate"
    return "complex"

def _extract_functions(source: str) -> dict[str, ast.FunctionDef]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    return {
        node.name: node 
        for node in ast.walk(tree) 
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) 
    }

def _ast_body_equal(a: ast.FunctionDef, b: ast.FunctionDef) -> bool:
    return ast.dump(a) == ast.dump(b)

def _classify_param(arg: ast.arg, default):
    if isinstance(arg.annotation, ast.Name):
        if arg.annotation.id == "Request":
            return "Request"

    if isinstance(default, ast.Call):
        if isinstance(default.func, ast.Name):
            if default.func.id == "Query":
                return "Query"
            if default.func.id == "Body":
                return "Body"

    return "Other"

def _extract_decorators(node) -> list[dict]:
    decorators = []
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Attribute):
                decorators.append({
                    'object': getattr(decorator.func.value, 'id', None),
                    'method': decorator.func.attr
                })
            elif isinstance(decorator.func, ast.Name):
                decorators.append({'name': decorator.func.id})
        elif isinstance(decorator, ast.Name):
            decorators.append({'name': decorator.id})
        elif isinstance(decorator, ast.Attribute):
            decorators.append({
                'object': getattr(decorator.value, 'id', None),
                'method': decorator.attr
            })
    return decorators

ROUTE_METHODS = {'get', 'post', 'put', 'delete', 'patch', 'route'}

def _extract_entry_points(source: str) -> list[dict]:
    try:
        tree = ast.parse(source)
        results = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            
            decorators = _extract_decorators(node)
            # print(f"decorators for {node.name}: {decorators}")
            is_entry_point = any(
                d.get('method', '').lower() in ROUTE_METHODS
                for d in decorators
            )

            if not is_entry_point: 
                continue

            args = node.args.args
            defaults = node.args.defaults
            paddeed_defaults = [None] * (len(args) - len(defaults)) + defaults

            for arg, default in zip(args, paddeed_defaults):

                results.append({
                    'function': node.name,
                    'parameter': arg.arg,
                    'type': _classify_param(arg, default),
                    'line_number': node.lineno
                })

        return results

    except SyntaxError:
        return []
    

def diff_parser(state: CodeReviewState) -> dict:
    inputs = state['input']

    old_input = get_input_by_version(inputs, 'old')
    new_input = get_input_by_version(inputs, 'new')

    if new_input is None:
        print(f"diff_parser: no 'new' version found among {len(inputs)} input(s) - skipping diff")
        return {
            'lines_changed': 0,
            'percent_changed': 0.0,
            'structural_type': 'trivial'
        }
    
    prev_lines = (old_input['content'] if old_input else '').splitlines()
    new_lines = new_input['content'].splitlines()

    diff = difflib.unified_diff(prev_lines, new_lines, lineterm="")

    lines_added = 0
    lines_removed = 0

    for line in diff:
        if line.startswith(('+++', '---', '@@')):
            continue
        if line.startswith('+'):
            lines_added += 1
        elif line.startswith('-'):
            lines_removed += 1

    lines_changed = lines_added + lines_removed

    total_lines = max(len(prev_lines), len(new_lines), 1)
    percent_changed = round(min((lines_changed / total_lines) * 100, 100.0), 2)

    return {
        "lines_changed":   lines_changed,
        "percent_changed": percent_changed,
        "structural_type": _classify(percent_changed, lines_changed),
        'language': detect_language(state['input']) 
    }

def ast_parser(state: CodeReviewState):
    inputs = state['input']

    old_input = get_input_by_version(inputs, 'old')
    new_input = get_input_by_version(inputs, 'new')

    if new_input is None:
        return {
            'functions_added': [],
            'functions_deleted': [],
            'functions_modified': [],
            'input_scanner': []
        }
    
    prev_code = old_input['content'] if old_input else ''
    new_code = new_input['content']
    
    # Authoritative syntax check
    try:
        ast.parse(new_code)
    except SyntaxError as e:
        return {
            'functions_added': [],
            'functions_deleted': [],
            'functions_modified': [],
            'input_scanner': [],
            'parse_error': f"File could not be parsed — invalid syntax at line {e.lineno}: {e.text.strip() if e.text else ''}"
        }
    
    
    prev_funcs = _extract_functions(prev_code)
    new_funcs = _extract_functions(new_code)

    prev_names = set(prev_funcs)
    new_names = set(new_funcs)

    functions_added = sorted(new_names - prev_names)
    functions_deleted = sorted(prev_names - new_names)

    functions_modified = sorted(
        name for name in prev_names & new_names
        if not _ast_body_equal(prev_funcs[name], new_funcs[name])
    )
    # print(f"entry points: {_extract_entry_points(new_code)}")
    return {
        'functions_added': functions_added,
        'functions_deleted': functions_deleted,
        'functions_modified': functions_modified,
        'input_scanner': _extract_entry_points(new_code)
    }
