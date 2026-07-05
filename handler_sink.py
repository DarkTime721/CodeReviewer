"""
Test file for Code Reviewer's cross-file taint tracing.

Imports `get_user_query` from helper_source.py (the source) and passes
its return value straight into os.system (a sink) — this should register
as a cross-file finding: source in helper_source.py -> sink in this file.
"""

import os
from helper_source import get_user_query, get_user_query_cleaned


def run_search():
    query = get_user_query()
    # deliberately unsafe — tainted input flowing into a shell command
    os.system(f"search-tool --query {query}")


def run_search_cleaned():
    query = get_user_query_cleaned()
    # still tainted even though it went through .strip() upstream
    os.system(f"search-tool --query {query}")
