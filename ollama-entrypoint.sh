#!/bin/bash

ollama serve &

until ollama list
do
    sleep 5
done

ollama pull nomic-embed-text

if [ "$LLM_PROVIDER" = "ollama" ]; then
    ollama pull "$OLLAMA_CLASSIFIER"
    ollama pull "$OLLAMA_JUDGE_MODEL"
    ollama pull "$OLLAMA_SPECIALIST_MODEL"
    ollama pull "$OLLAMA_DEFAULT_MODEL"
fi

wait