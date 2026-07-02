#!/bin/bash
set -e

mkdir -p /app/chroma
chown -R appuser:appuser /app/chroma

exec gosu appuser "$@"