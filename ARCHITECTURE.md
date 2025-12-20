# Architecture

## Purpose

The MCP Tool Server is a capability layer that exposes Python tools in a controlled and machine-readable way.
It separates business logic from transport concerns such as OpenAPI or MCP.

## Core Components

- Tool modules defining contracts and handlers
- ToolRegistry for validation and execution
- Loader for dynamic discovery
- OpenAPI server for LLM-facing access
- Optional MCP server for agent-based access

## Design Principles

- Contracts over conventions
- One responsibility per tool
- Deterministic behavior
- Transport-agnostic tool logic
