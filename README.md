# Code Reviewer
 
A production-grade, multi-agent AI code review system built with **LangGraph**. It analyzes code diffs for bugs, security vulnerabilities, quality issues, and performance problems — including cross-file security vulnerability tracing — and returns a structured, confidence-scored review.
 
Fully containerized with Docker, with observability via LangSmith and persistent review memory via ChromaDB.
 
## Features
 
- **Multi-agent review pipeline** — four specialist agents (bug, security, quality, performance) analyze code in parallel, dispatched based on task classification and confidence routing
- **Cross-file taint tracing** — a custom static analysis engine that traces tainted data (e.g. user input) across file and module boundaries to catch security vulnerabilities that single-file analysis misses
- **Judge & retry loop** — a judge node evaluates specialist findings and can trigger targeted retries (`PASS` / `RETRY` / `FORCE_OUTPUT`) rather than accepting low-confidence output
- **Persistent memory** — ChromaDB stores review history so the system can reference prior findings across sessions
- **Streaming API** — FastAPI backend with `StreamingResponse` for real-time review output
- **Fully containerized** — Docker Compose setup with GPU passthrough, healthcheck-gated startup, and non-root privilege dropping
- **Multi-provider LLM support** — works with local models via Ollama (Llama, Qwen, Gemma, and others) or hosted providers (OpenAI, Groq)
## Architecture
 
```mermaid
flowchart TD
    START([START]) --> start
    start --> diff_parser
    diff_parser --> ast_parser
    ast_parser --> memory_reader
    memory_reader --> cross_taint["cross-taint"]
    cross_taint --> task_classifier
    task_classifier --> agent_dispatcher

    agent_dispatcher -.->|confidence_router| bug_agent
    agent_dispatcher -.->|confidence_router| security_agent
    agent_dispatcher -.->|confidence_router| quality_agent
    agent_dispatcher -.->|confidence_router| performance_agent
    agent_dispatcher -.->|confidence_router| trivial_output_node

    bug_agent --> aggregator
    security_agent --> aggregator
    quality_agent --> aggregator
    performance_agent --> aggregator

    aggregator --> judge_agent

    judge_agent -.->|PASS| output_formatter
    judge_agent -.->|RETRY| agent_dispatcher
    judge_agent -.->|FORCE_OUTPUT| output_formatter

    trivial_output_node --> memory_writer
    output_formatter --> memory_writer
    memory_writer --> END([END])
```
 
Review findings are deduplicated in the aggregator via a composite key, then passed through the judge before final markdown/diff output is generated.
 
## Tech Stack
 
| Layer | Tools |
|---|---|
| Agent orchestration | LangGraph |
| LLM inference | Ollama (local), OpenAI, Groq |
| Vector memory | ChromaDB |
| API | FastAPI |
| Observability | LangSmith |
| Containerization | Docker, Docker Compose |
 
## Getting Started
 
### Prerequisites
- Docker & Docker Compose
- NVIDIA GPU + drivers (for local Ollama inference; optional if using a hosted provider)
### Setup
 
1. Clone the repo and copy the environment template:
```bash
   git clone <repo-url>
   cd CodeReviewer
   cp .env.example .env
```
 
2. Fill in `.env` with your LangSmith API key and choose your `LLM_PROVIDER` (`ollama`, `openai`, or `groq`).
3. Build and run:
```bash
   docker compose up --build
```
   On first run, the Ollama container will pull the required models before the app becomes healthy — this can take a few minutes depending on model size.
 
4. The API is available at `http://localhost:8000`.
### Example request
 
```bash
curl -X POST http://localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{
    "repo_id": "my-repo",
    "input": [
      {
        "file": "app/utils.py",
        "version": "old",
        "content": "def foo():\n    pass\n"
      },
      {
        "file": "app/utils.py",
        "version": "new",
        "content": "def foo():\n    return True\n"
      }
    ]
  }'
```
 
Each file in `input` is tagged with `version` (`old` or `new`) so the reviewer can diff old vs. new content per file. Responses are streamed as findings are generated.
 
## Project Structure
 
```
app/
├── main.py              # FastAPI entrypoint
├── graph/                # LangGraph nodes and graph wiring
│   ├── agents/           # bug, security, quality, performance agents
│   └── ...
├── taint/                # cross-file taint tracing engine
├── memory.py              # ChromaDB read/write
├── model_factory.py       # provider-agnostic model loading
└── schemas.py
docker-compose.yml
Dockerfile
```
 
## Roadmap
 
- [x] Core multi-agent review pipeline
- [x] Cross-file taint tracing
- [x] Docker containerization
- [ ] Integration GitHub PR API to automatically fetch pull request code changes, eliminating manual file copying and simplifying code retrieval for automated code review.
- [ ] **MCP server** — expose `review_pr` and `check_cross_file_taint` as MCP tools so the reviewer can be called from any MCP client (Claude Desktop, IDEs, other agents), plus a GitHub Action for automatic PR review
- [ ] **Frontend** — lightweight UI for submitting diffs and viewing streamed review output
- [ ] QLoRA fine-tuning exploration
MCP integration and the frontend are both actively in progress.
 
## License
 
MIT
