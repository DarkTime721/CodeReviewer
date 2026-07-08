import ast
from pathlib import Path
from importlib.util import find_spec
from ..graph.state import CodeReviewState, get_input_by_version
from .taint_patterns import source_patterns, sink_patterns
from ..schemas import fetch_with_retry, github_token, GitHubPermanentError, ConfigurationError, GitHubAPIError
import base64
from typing import Optional


# Function added for fetching the required dependency files (from import) if present
def fetch_file(url: str):
    if github_token:
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json"
        }
    else:
        raise ConfigurationError("GitHub token is not configured")
    try:
        data = fetch_with_retry(url=url, headers=headers)

        code = base64.b64decode(
            data['content']
        ).decode("utf-8")

        return code

    except GitHubAPIError as e:
        raise e
        


def obj_and_attrs(node):
    if isinstance(node, ast.Call):
        current = node.func

        # Support standalone function calls so imported function returns can be tracked 
        # (e.g., data = get_input()) 
        if isinstance(current, ast.Name):
            return current.id, []
        
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

            arg_names = []

            if isinstance(node.args[0], ast.Name):
                arg_names.append(node.args[0].id)
            elif isinstance(node.args[0], (ast.Call, ast.Subscript)):
                obj, attrs = obj_and_attrs(node.args[0])
                arg_names.append(obj)
            
            # Added support for f-string (e.g. os.system(f"search-tool --query {query}") )
            elif isinstance(node.args[0], ast.JoinedStr):
                for value in node.args[0].values:
                    if (
                        isinstance(value, ast.FormattedValue)
                        and isinstance(value.value, ast.Name)
                    ):
                        arg_names.append(value.value.id)
            else:
                return
            for arg_name in arg_names:
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


    def resolve_module_paths(module: str, from_file: Path, level: int, repo_tree: set[str]) -> Optional[str]:
        """Resolve an import to a repo-root-relative path string, or None if
        it can't be found in the repo's tree (likely to be stdlib/third-party)."""
        parts = module.split('.') if module else []

        if level == 0:
            # Absolute import: resolved from repo root, not from from_file's directory
            anchor = Path('.')
        else:
            # Relative import: level=1 means "current package" (from_file's own dir),
            # each additional level climbs one more parent up
            anchor = Path(from_file).parent
            for _ in range(level - 1):
                anchor = anchor.parent

        base = anchor.joinpath(*parts) if parts else anchor

        # Try as a plain module file, then as a package's __init__.py
        candidate = str(base.with_suffix('.py')).replace('\\', '/').lstrip('./')
        candidate_init = str(base / '__init__.py').replace('\\', '/').lstrip('./')

        if candidate in repo_tree:
            return candidate
        if candidate_init in repo_tree:
            return candidate_init

        return None  # not found in repo; treaded as stdlib/third-party module


    def manage_imports(stmt, file_path: Path, head_sha=state['head_sha']):
        if isinstance(stmt, ast.Import):
            modules = [name.name for name in stmt.names]
            imported_fns = []
            level = 0
        else:
            modules = [stmt.module]
            imported_fns = [name.name for name in stmt.names]
            level = stmt.level  # 0 = absolute, 1+ = relative

        for module in modules:
            candidate_str = resolve_module_paths(module, file_path, level, state['repo_tree'])

            if candidate_str is None:
            # Not found anywhere in the repo tree, stdlib/third-party module considered
                if not find_spec(module):
                    unresolved_imports.append({
                        'module': module,
                        'imported_fns': imported_fns,
                        'file': file_path,
                        'lineno': stmt.lineno,
                        'error': ''
                    })
                continue

            # Checking if files are already fetched as part of this PR, no network call is required
            local_match = next(
                (entry for entry in state['input'] if entry['file'] == candidate_str),
                None
            )

            if local_match is not None:
                try:
                    tree = ast.parse(local_match['content'])
                    for stmt_import in tree.body:
                        dispatch(stmt_import, Path(candidate_str))
                except SyntaxError as e:
                    unresolved_imports.append(
                        {
                            'module': module,
                            'imported_fns': imported_fns,
                            'file': file_path,
                            'lineno': stmt.lineno,
                            'error': f"Invalid syntax:\nFile path: {candidate_str}\nLine no: {e.lineno}"
                        }
                    )
                continue

            # GitHub integration for fetching the code of the imported file from the repo for taint tracing
            # If not a part of this PR's diff, trying to fetch it live from GitHub
            url = f"{state['repo_url_fetch']}/{candidate_str}?ref={head_sha}"
            try:
                file = fetch_file(url=url)
                tree = ast.parse(file)
                for stmt_import in tree.body:
                    dispatch(stmt_import, Path(candidate_str))
                
            except GitHubAPIError as e:
                # rate limit exhausted (503 or worthy) or other API error

                unresolved_imports.append(
                    {
                        'module': module,
                        'imported_fns': imported_fns,
                        'file': file_path,
                        'lineno': stmt.lineno,
                        'error': e.args[0]
                    }
                )
                
            except SyntaxError as e:
                unresolved_imports.append(
                    {
                        'module': module,
                        'imported_fns': imported_fns,
                        'file': file_path,
                        'lineno': stmt.lineno,
                        'error': f"Invalid syntax:\nFile path: {candidate_str}\nLine no: {e.lineno}"
                    }
                )

                '''
                with open(candidate_path, 'r') as f:
                    file = f.read()
                    tree = ast.parse(file)
                    for stmt_import in tree.body:
                        dispatch(stmt_import, candidate_path)
                '''


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

    # AST-parser node has been updated to check if Syntax errors take place
    # If SyntaxError is present, skip the cross_file_findings
    if state.get('parse_error'):
        return {
        'cross_file_findings': [],
        'unresolved_imports': []
    }

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
