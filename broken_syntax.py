"""
Test file for Code Reviewer's parse_error routing.

This file is deliberately invalid Python — an unclosed function
definition, as if a merge went wrong. Pushing this in the PR should
trigger `ast_parser`'s SyntaxError branch, set `parse_error` in state,
and route this file straight to `trivial_output_node` instead of
running the bug/security/quality/performance agents on it.
"""

def broken_function(
    query = get_user_query()
    return query
