# MCP Tool Server

## Core Documents

- [Architecture overview](ARCHITECTURE.md)
- [LLM instructions](LLM_INSTRUCTIONS.md)
- [Tool template](tool_template.py)


## Overview

This repository provides a structured, secure, and extensible **Tool Server architecture** for exposing Python-based tools to Large Language Models (LLMs) and agent systems.

The system is designed to:

- Define tool contracts explicitly in code
- Expose tools via **OpenAPI** for OpenWebUI
- Optionally expose the same tools via **MCP** for agent frameworks such as n8n
- Enforce strict input validation using **Pydantic**
- Secure access using **Bearer token authentication**
- Support clean separation of tools by capability domain

The guiding principle of this project is:

> **Tools are code-defined capabilities, not prompt-based logic.**

---

## High-Level Architecture

The system consists of the following core layers:

1. **Tool Layer**
   - Python modules defining tool inputs and behavior
   - No knowledge of transport or UI

2. **Registry Layer**
   - Central in-process registry of available tools
   - Handles validation and execution

3. **Transport Layer**
   - OpenAPI (FastAPI) for LLM-facing access
   - Optional MCP server for agent-based integrations

4. **Security Layer**
   - Bearer token authentication
   - Future-ready for RBAC and per-tool authorization

---

## Repository Structure

```text
.
├── README.md                # Entry point and high-level overview
├── ARCHITECTURE.md          # High-level architectural principles
├── LLM_INSTRUCTIONS.md      # Rules and guidance for LLM behavior
├── tool_template.py         # Template for implementing new tools
├── docs/                    # Extended documentation
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── openapi_app.py
├── main.py                  # Optional MCP server entrypoint
├── app/
│   ├── auth.py
│   ├── loader.py
│   ├── registry.py
│   ├── errors.py
│   └── server.py
└── tools/
    └── shared/
        └── example.py
```

---

## Root-Level Documentation

Some documents intentionally live in the repository root:

- **README.md**  
  Entry point for humans, tooling, and language models.

- **ARCHITECTURE.md**  
  High-level architectural intent, constraints, and design principles.

- **LLM_INSTRUCTIONS.md**  
  Explicit behavioral rules for language models and agents.

- **tool_template.py**  
  Developer-facing template for implementing new tools safely.

Detailed and evolving documentation lives under the `docs/` directory.

---

## Runtime Endpoints

| Endpoint | Description |
|--------|-------------|
| GET /health | Health check |
| GET /openapi.json | OpenAPI specification |
| GET /tools | List registered tools (authenticated) |
| POST /tools/{tool_name} | Execute a tool |

---

## Security Model

- Authentication is handled via **Bearer tokens**
- Tokens are provided via environment variables
- All tool execution endpoints are protected
- Secrets must never be committed to Git

Example environment configuration:

```bash
BEARER_TOKEN=change_me
```

---

## Running the Project

### Prerequisites

- Docker
- Docker Compose

### Start

```bash
docker compose up --build -d
```

### Basic Verification

```bash
curl http://localhost:8006/health
curl http://localhost:8006/tools \
  -H "Authorization: Bearer <TOKEN>"
```

---

## Adding a New Tool (Quick Summary)

1. Create a new Python file under `tools/<domain>/`
2. Define a Pydantic input model with `extra="forbid"`
3. Implement an async handler function
4. Register the tool using `register_tools(registry)`
5. Restart the container

A full step-by-step guide for an llm is available in:


- [LLM instruction guide](docs/tools/how-to-add-a-tool-with-a-llm.md)


---

## Tool Design Rules (Mandatory)

- Every tool must define an explicit input schema
- Additional parameters must be rejected
- Handlers must be asynchronous
- Tool logic must be deterministic and side-effect aware
- Transport concerns must not leak into tool code

---

## Intended Consumers

This project is designed to be consumed by:

- OpenWebUI (via OpenAPI)
- LLM-based agents
- Workflow engines such as n8n
- Internal automation systems

---

## Documentation Index

For detailed documentation, see:

- [Documentation index](docs/index.md)
- [Architecture](docs/architecture/)
- [Tool development](docs/tools/)
- [Security](docs/security/)
- [Operations](docs/operations/)
- [LLM & Agents](docs/llm/)

---

## Project Status

- Production-ready baseline
- OpenWebUI compatible
- MCP-compatible
- Designed for extension and governance
