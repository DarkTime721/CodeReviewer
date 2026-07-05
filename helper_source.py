"""
Test file for Code Reviewer's cross-file taint tracing.

This file defines a function that pulls in attacker-controllable input
(a classic taint "source") and returns it unmodified. `handler_sink.py`
imports this function and passes the result into a dangerous sink,
so the taint should be traceable across the two files.
"""

from flask import request


def get_user_query():
    # request.args.get(...) is a common taint source pattern
    # (attacker-controlled query parameter)
    query = request.args.get("q")
    return query


def get_user_query_cleaned():
    # pass-through case: still tainted, since .strip() doesn't sanitize anything
    raw = request.args.get("q")
    cleaned = raw.strip()
    return cleaned
