Project: code-forge-agent
Repo: github.com/pratyushmohit/code-forge-agent

## Problem Statement

Traditional agentic AI systems expose external APIs as predefined tools — each tool is a
handcrafted wrapper around one API call. This works for small integrations but breaks down
at enterprise scale. AWS Boto3 alone covers 300+ services and thousands of methods. You
cannot manually build, maintain, and version a tool for every endpoint.

The result: agents are artificially limited to whatever tools a developer had time to
pre-build. The agent is only as capable as the wrappers someone wrote.

But there is a second, compounding problem: context bloat. Every predefined MCP tool
ships with a schema — name, description, parameters, types. At scale, these schemas
consume context before the user types a single character. Cloudflare's own REST/OpenAPI
spec for their products is 2.3 million tokens. Dumping that into an LLM context window
as tool definitions is not a configuration problem — it is a fundamental architectural
failure of the predefined-tool model.

Matt Carey (Cloudflare, April 2026) called this exactly: "MCP = Mega Context Problem."
https://www.youtube.com/watch?v=YBYUvGOuotE

This problem is real and personal: at Amgen, I hit it building MCP integrations for
Veeva Vault — 50+ APIs. You cannot wrap them all. And even if you could, the schema
cost alone would blow the context window before the agent does any useful work.

---

## The Insight

Independently validated by Cloudflare (Code Mode, Sept 2025), Anthropic (Programmatic
Tool Calling, 2026), and Matt Carey's "MCP = Mega Context Problem" (April 2026):
LLMs are significantly better at writing code to call APIs than at invoking predefined
tools. LLMs have seen millions of real-world Boto3 examples in training. Code is the
natural interface — not tool schemas.

Code execution eliminates both problems at once:
- No predefined tools = no tool maintenance burden
- No tool schemas in context = no context bloat

One `execute_code` tool replaces thousands of handcrafted wrappers and ships with
exactly one schema entry in the context window.

---

## The Solution

One execution tool. Infinite AWS operations.

Instead of N predefined Boto3 wrappers, the LangGraph agent receives a single
`execute_code` tool. When the user asks a question, the agent writes Python code
using Boto3 directly. That code is executed in a secure, minimal sandbox using Monty
(pydantic-monty) — a Python interpreter written in Rust, purpose-built for
LLM-generated code execution.

---

## Why Boto3 Over AWS CLI

- Monty runs Python natively — CLI would require subprocess, which introduces shell
  injection risk the moment LLM-generated strings touch a shell
- `shell=True` in subprocess means LLM-generated commands can smuggle in
  `;rm -rf /` or exfiltration payloads — unacceptable
- Boto3 returns structured Python dicts, not strings requiring fragile parsing
- Python is the natural language for both the agent and the execution environment —
  no context switching, no serialization overhead

---

## Why Monty Over subprocess or Docker

- subprocess: zero isolation, shell injection risk, full host filesystem access
- Docker: ~195ms cold start per execution, container lifecycle management,
  networking complexity, heavyweight for what should be a microsecond operation
- Monty: microsecond startup, explicitly allowlisted external function access,
  no filesystem or network unless you grant it, trust-nothing-enforce-everything
  at the interpreter level

Monty's model: you pass it a Python string and a dict of allowed callables.
It executes only what you explicitly permit. The LLM cannot escape the sandbox
because there is no shell — only a Rust interpreter with a controlled function registry.

---

## Architecture

User Query (natural language)
    ↓
LangGraph ReAct Agent (AWS Bedrock / Claude)
    ↓
ONE tool: execute_code(python_code: str)
    ↓
Agent writes Boto3 Python code to answer the query
    ↓
Monty sandbox executes — only allowlisted Boto3 calls go through
    ↓
Structured result returned to agent
    ↓
Agent interprets and responds to user

---

## Architectural Vision: Why MCP Servers Are the Right Scaling Boundary

This project intentionally scopes to AWS + Boto3. But the architecture is designed
with multi-cloud in mind from the start.

The key insight: MCP servers are not just tool registries — they are the abstraction
boundary between a unified agent and cloud-specific implementations. Each cloud gets
its own MCP server that encapsulates its SDK, auth, and quirks. The agent and the
sandbox remain unchanged.

The target multi-cloud architecture looks like this:

    User: "Find idle compute across all my clouds"
             ↓
    LangGraph Agent (one agent, one brain)
             ↓
    LLM writes Python code
             ↓
    Monty sandbox executes
             ↓
    Code calls into → AWS MCP server   (Boto3 under the hood)
                    → Azure MCP server (Azure SDK under the hood)
                    → GCP MCP server   (google-cloud SDK under the hood)

The LLM writes cloud-agnostic Python. Each MCP server handles credentials,
rate limits, and SDK-specific behaviour for its cloud. You can add a new cloud
by wiring in a new FastMCP server — zero changes to the agent or the sandbox.

This also solves the context bloat problem at multi-cloud scale: regardless of how
many clouds are connected, the agent context carries exactly ONE tool schema —
`execute_code`. The MCP servers are implementation detail, invisible to the LLM.

This is the correct separation of concerns:
- Monty: secure execution runtime
- MCP servers: cloud-specific portability contracts
- LangGraph agent: orchestration and reasoning
- LLM: code generation

aws-code-agent proves this pattern works on AWS first. The architecture scales
horizontally to any cloud that has a Python SDK.

---

## Stack

- Agent: LangGraph (ReAct loop)
- LLM: AWS Bedrock (Claude or Nova)
- Code execution: pydantic-monty (Rust-based secure Python interpreter)
- AWS SDK: Boto3
- MCP server: FastMCP (AWS only, v1)
- API layer: FastAPI
- Observability: Langfuse (OTel session tracing)
- Packaging: Docker Compose

---

## Scope

Boto3 only. Single AWS account. One execution tool. No Azure, no GCP.
The constraint is intentional — prove the pattern works cleanly before expanding.
The multi-cloud MCP architecture is the natural next step, not an afterthought.

---

## Prior Art & Sources

- Matt Carey (Cloudflare), "MCP = Mega Context Problem", April 2026
  https://www.youtube.com/watch?v=YBYUvGOuotE
  → Cloudflare's own OpenAPI spec is 2.3M tokens; predefined tools don't scale

- Cloudflare Code Mode, September 2025
  → Same code-first pattern, TypeScript + V8 isolates

- Anthropic, "Programmatic Tool Calling", 2026
  → Native Claude API implementation; LLMs write code, not tool invocations

- Anthropic, "MCP Scaling: Tool Search", 2026
  https://www.youtube.com/watch?v=6x5G5Lam1Wk
  → Anthropic's own acknowledgment that MCP tool bloat is a solved-wrong problem

- This project: open source, AWS-native, Python, Monty sandbox, fully observable

---

## What Success Looks Like

User: "Which EC2 instances in us-east-1 have been running for more than 7 days?"
Agent writes Boto3 code → Monty executes → structured result → natural language answer.

No tool schema. No hardcoded filter. No context bloat.
The agent figures out the right Boto3 calls itself.