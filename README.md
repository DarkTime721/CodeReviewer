# Code Reviewer

A production-grade, multi-agent AI code review system built with **LangGraph**. It analyzes GitHub pull requests for bugs, security vulnerabilities, quality issues, and performance problems — including cross-file, security vulnerability tracing — and returns a structured, confidence-scored review.

Fully containerized with Docker, with observability via LangSmith and persistent review memory via ChromaDB.

## Features

- **Multi-agent review pipeline** — four specialist agents (bug, security, quality, performance) analyze code in parallel, dispatched based on task classification and confidence routing
- **GitHub PR integration** — submit a PR URL and pull number; Code Reviewer fetches the diff, changed files, and PR metadata directly via the GitHub API, with automatic retry-with-backoff on rate limits and clear error responses for auth/config issues
- **Cross-file, cross-repo taint tracing** — a custom static analysis engine that traces tainted data (e.g. user input) across file and module boundaries, resolving imports against the PR's full repo tree and fetching non-diff files live from GitHub when needed, rather than relying on local-disk lookups
- **Judge & retry loop** — a judge node evaluates specialist findings and can trigger targeted retries (`PASS` / `RETRY` / `FORCE_OUTPUT`) rather than accepting low-confidence output
- **Persistent memory** — ChromaDB stores review history so the system can reference prior findings across sessions
- **Streaming API** — FastAPI backend with `StreamingResponse` for real-time, per-file review output
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

Review findings are deduplicated in the aggregator via a composite key, then passed through the judge before final markdown/diff output is generated. Reviews are streamed back **per file** — each changed file in the PR runs through its own graph execution with a fresh `thread_id`, so output for one file doesn't block on another.

## Tech Stack

| Layer | Tools |
|---|---|
| Agent orchestration | LangGraph |
| LLM inference | Ollama (local), OpenAI, Groq |
| Vector memory | ChromaDB |
| API | FastAPI |
| Source integration | GitHub REST API |
| Observability | LangSmith |
| Containerization | Docker, Docker Compose |

## GitHub API Setup

Code Reviewer fetches PR file contents, metadata, and any cross-file imports directly
from the GitHub API, so it needs a GitHub **personal access token** to authenticate its
requests. Without one, requests to `/review` will fail immediately with a clear
`500 Configuration Error` rather than attempting the fetch.

### 1. Generate a token

1. Go to **github.com** → click your profile picture (top right) → **Settings**.
2. In the left sidebar, scroll to **Developer settings**.
3. Go to **Personal access tokens → Fine-grained tokens → Generate new token**.
4. Give it a descriptive name (e.g. `code-reviewer-local`) and an expiration — shorter
   is safer for a token used in local development.
5. Under **Repository access**, choose:
   - **Only select repositories** — pick whichever repos you want Code Reviewer to be
     able to review, or
   - **All repositories** — needed if you want to point Code Reviewer at arbitrary
     public repos, not just your own.
6. Under **Permissions → Repository permissions**, grant:
   - **Pull requests: Read-only** — required to list PR files and fetch PR metadata.
   - **Contents: Read-only** — required to fetch file contents (old/new versions, the
     full repo tree, and any imported files used during cross-file taint tracing that
     aren't part of the PR diff itself).
7. Click **Generate token** and **copy it immediately** — GitHub only shows the full
   token once.

### 2. Configure it

Add the token to your `.env` file at the project root:

```
GITHUB_TOKEN=github_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

If you're running via Docker Compose, make sure this `.env` file is either loaded via
`env_file:` in `docker-compose.yml` or the variable is passed through under
`environment:` — otherwise the container won't see it even if it's set on your host.

### Error handling

Requests fail fast and clearly rather than hanging or returning ambiguous errors:

| Situation | Status | Response |
|---|---|---|
| No token configured | `500` | Configuration error |
| Malformed GitHub URL / bad pull number | `400` | Invalid request error |
| Token invalid/expired, or PR/repo not found | passthrough (`401`/`404`) | GitHub's own error message |
| Rate limit hit, retries exhausted | `503` | Rate limit error |

### Notes on rate limits

Authenticated requests get a much higher GitHub API rate limit than unauthenticated
ones (5,000 requests/hour vs. 60/hour), which matters here since a single PR review
can trigger several calls — one for the file list, one for PR metadata, one or two per
changed file for content, plus additional calls per cross-file import resolved against
the repo tree during taint tracing. If you hit a rate limit anyway, Code Reviewer
retries automatically with backoff (reading the `retry-after` header) and returns a
`503` only if retries are exhausted — no action needed on your end beyond waiting.

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

2. Fill in `.env` with your LangSmith API key, `GITHUB_TOKEN`, and choose your `LLM_PROVIDER` (`ollama`, `openai`, or `groq`).
3. Build and run:
```bash
docker compose up --build
```
   On first run, the Ollama container will pull the required models before the app becomes healthy — this can take a few minutes depending on model size.

4. The API is available at `http://localhost:8000` (Swagger UI at `http://localhost:8000/docs`).

### Example request

Submit a real GitHub PR by URL and pull number — Code Reviewer fetches everything else
(diff, file contents, repo tree) itself:

```bash
curl -X POST http://localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{
    "github_url": "https://github.com/your-org/your-repo",
    "pull_number": "12"
  }'
```

Or via Swagger UI at `http://localhost:8000/docs`: open the `POST /review` endpoint,
click **Try it out**, and fill in the same two fields (`github_url`, `pull_number`).

The response streams back per changed file — each file's section is separated by a
`--- {filename} ---` header, with any files that failed to fetch or process (e.g. a
syntax error, or a GitHub fetch failure) surfaced first under a `Failed:` block before
the successful reviews stream in.

## Project Structure

```
app/
├── main.py               # FastAPI entrypoint, PR-fetch orchestration, per-file streaming
├── graph/                 # LangGraph nodes and graph wiring
│   ├── agents/             # bug, security, quality, performance agents
│   └── ...
├── taint/                  # cross-file, cross-repo taint tracing engine
├── memory.py               # ChromaDB read/write
├── model_factory.py        # provider-agnostic model loading
└── schemas.py              # request models, GitHub error hierarchy, PR-fetch construction
docker-compose.yml
Dockerfile
```

## Roadmap

- [x] Core multi-agent review pipeline
- [x] Cross-file taint tracing
- [x] Docker containerization
- [x] GitHub PR API integration — automatic fetching of PR diffs, file contents, and cross-repo imports, replacing manual file copying
- [ ] Model-aware prompt optimization to reduce token usage by dynamically adjusting prompt complexity based on the selected model, improving efficiency for high-token code review runs.
- [ ] **MCP server** — expose `review_pr` and `check_cross_file_taint` as MCP tools so the reviewer can be called from any MCP client (Claude Desktop, IDEs, other agents), plus a GitHub Action for automatic PR review
- [ ] **Frontend** — lightweight UI for submitting a PR link and viewing streamed review output
- [ ] QLoRA fine-tuning exploration

MCP integration and the frontend are both actively in progress.

## License

MIT
