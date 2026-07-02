import ast
from pathlib import Path
from importlib.util import find_spec
from ..graph.state import CodeReviewState, get_input_by_version
from .taint_patterns import source_patterns, sink_patterns


def obj_and_attrs(node):
    if isinstance(node, ast.Call):
        current = node.func
    elif isinstance(node, ast.Subscript):
        current = node.value
    else:
        return (None, [])
    attrs = []
    while isinstance(current, ast.Attribute):
        attrs.append(current.attr)
        current = current.value
    
    if isinstance(current, ast.Name):
        object_name = current.id
    else:
        return None, attrs[::-1]

    return (object_name, attrs[::-1])


def find_source_or_sink(c: tuple):

    for obj, attrs, trust in source_patterns:
        if (obj, attrs) == c:
            print("Matched as Source", c, trust)
            return {'type': 'source', 'score': trust}

    for obj, attrs, severity in sink_patterns:
        if (obj, attrs) == c:
            print("Matched as Sink", c, severity)
            return {'type': 'sink', 'score': severity}
        
    print("No match found")
    return {'type': 'unknown', 'score': 0}


def cross_file_tracer_node(state: CodeReviewState) -> dict:
    
    tainted_vars = {}
    function_returns = {}
    unresolved_imports = []
    findings = []


    def taint(node, file_path: Path):
        var_name = node.targets[0].id

        if isinstance(node.value, (ast.Call, ast.Subscript)):
            obj, attrs = obj_and_attrs(node.value)
            result = find_source_or_sink((obj, attrs))

            if result['type'] == 'source':
                tainted_vars[var_name] = {
                    "file": file_path,
                    "lineno": node.value.lineno,
                    "score": result['score'],
                    "origin": {
                        'file': file_path,
                        'obj_and_attrs': ((obj, attrs)),
                        'lineno': node.value.lineno
                    }
                }
            elif obj in tainted_vars:
                # pass-through: cleaned = raw.strip() — raw is tainted, so cleaned inherits it
                tainted_vars[var_name] = {
                    "file": file_path,
                    "lineno": node.value.lineno,
                    "score": tainted_vars[obj]['score'],
                    "origin": {
                        "file": tainted_vars[obj]['file'],
                        'obj_and_attrs': tainted_vars[obj]['origin']['obj_and_attrs'],
                        'lineno': tainted_vars[obj]['origin']['lineno']
                    }
                }
            elif obj in function_returns:
                tainted_vars[var_name] = {
                    "file": file_path,
                    "lineno": node.value.lineno,
                    "score": function_returns[obj]['score'],
                    'origin': {
                        'file': function_returns[obj]['origin']['file'],
                        'obj_and_attrs': function_returns[obj]['origin']['obj_and_attrs'],
                        'lineno': function_returns[obj]['origin']['lineno']
                    }
                }
            else:
                # neither a known source, nor a pass-through from something tainted
                if var_name in tainted_vars:
                    del tainted_vars[var_name]
        else:
            # RHS is a Constant, Name, BinOp, etc — definitely not tainted via this assignment
            if var_name in tainted_vars:
                del tainted_vars[var_name]


    def check_sink(node, file_path: Path):
        obj_source, attrs_source = obj_and_attrs(node)
        result = find_source_or_sink((obj_source, attrs_source))

        if result['type'] == 'sink':
            if isinstance(node.args[0], ast.Name):
                arg_name = node.args[0].id
            elif isinstance(node.args[0], (ast.Call, ast.Subscript)):
                obj, attrs = obj_and_attrs(node.args[0])
                arg_name = obj
            else:
                return
            if arg_name in tainted_vars:
                    findings.append({
                        "sink_file": file_path,
                        "sink_lineno": node.lineno,
                        "var_name": arg_name,
                        "source_file": tainted_vars[arg_name]['origin']["file"],
                        "source_lineno": tainted_vars[arg_name]['origin']["lineno"],
                        "source_call": tainted_vars[arg_name]['origin']['obj_and_attrs'],
                        "score": tainted_vars[arg_name]["score"],
                    })

    
    def handle_return(node, file_path: Path, function_name: str):
        if isinstance(node.value, ast.Name):
            arg_name = node.value.id
        elif isinstance(node.value, (ast.Call, ast.Subscript)):
            obj, attrs = obj_and_attrs(node.value)
            arg_name = obj
        else:
            return
        if arg_name in tainted_vars:
                function_returns[function_name] = {
                    'file': file_path,
                    'lineno': node.value.lineno,
                    'score': tainted_vars[arg_name]['score'],
                    'origin': {
                        'file': tainted_vars[arg_name]['origin']['file'],
                        'obj_and_attrs': tainted_vars[arg_name]['origin']['obj_and_attrs'],
                        'lineno': tainted_vars[arg_name]['origin']['lineno']
                    }
                }
        else:
            if function_name in function_returns:
                del function_returns[function_name]


    def resolve_module_paths(module: str, from_file: Path):
        parts = module.split('.')
        base = Path(from_file).resolve().parent
        while True:
            candidate = base.joinpath(*parts).with_suffix('.py')
            if candidate.exists():
                return candidate
            parent = base.parent
            if parent == base:
                return Path("None")   # Will always be false
            base = parent

    def manage_imports(stmt, file_path: Path):
        if isinstance(stmt, ast.Import):
            modules = [name.name for name in stmt.names]
            imported_fns = []
        else:
            modules = [stmt.module]
            imported_fns = [name.name for name in stmt.names]
        for module in modules:
            candidate_path = resolve_module_paths(module, file_path)
            
            if candidate_path.exists():
                with open(candidate_path, 'r') as f:
                    file = f.read()
                    tree = ast.parse(file)
                    for stmt_import in tree.body:
                        dispatch(stmt_import, candidate_path) 
            else:
                if find_spec(module):
                    continue
                else:
                    unresolved_imports.append(
                        {
                            'module': module,
                            'imported_fns': imported_fns,
                            'file': file_path,
                            'lineno': stmt.lineno
                        }
                    )


    def dispatch(stmt, file_path: Path, function_name= None):
        if isinstance(stmt, (ast.ImportFrom, ast.Import)):
            manage_imports(stmt, file_path)    # update may be required if changes are done
        elif isinstance(stmt, ast.Assign):
            taint(stmt, file_path)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            check_sink(stmt.value, file_path)
        elif isinstance(stmt, ast.FunctionDef):
            function_name = stmt.name
            for stmt_body in stmt.body:
                dispatch(stmt_body, file_path, function_name)  # recursive call because we are basically going to check the if else and call the same two functions [taint/check_sink]
                if isinstance(stmt_body, ast.Return):
                    handle_return(stmt_body, file_path, function_name)

    new_input = get_input_by_version(state['input'], 'new')

    if new_input is None:
        return {}
    
    code = new_input['content']
    tree = ast.parse(code)
    for stmt in tree.body:
        dispatch(stmt, new_input['file'])

    return {
        'cross_file_findings': findings,
        'unresolved_imports': unresolved_imports
    }
