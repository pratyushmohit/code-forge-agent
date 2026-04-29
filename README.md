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
LangGraph ReAct Agent (Ollama / qwen3.6:27b)
    ↓
Step 1 — Discovery: agent calls get_service_schema(service_name) via AWS MCP server
    → botocore service model returned (operation names + input shapes, condensed)
    ↓
Step 2 — Code generation: agent writes Boto3 Python using exact signatures from schema
    ↓
Step 3 — Execution: agent calls execute_code(python_code) — lives in the agent, NOT in MCP
    → Monty sandbox executes with pre-authenticated boto3.Session in allowlist
    → Credentials come from MCP server (STS temporary tokens), never from agent env
    ↓
Structured result returned to agent
    ↓
Agent interprets and responds to user

---

## Tool Separation: Why execute_code Is Not in the MCP Server

The MCP server is a cloud-specific discovery and auth layer. execute_code is cloud-agnostic.

AWS MCP server tools (AWS-specific, read-only):
  - get_service_schema(service_name) — botocore service model, condensed
  - get_temp_credentials()           — STS short-lived tokens (never exposes long-lived creds)

Agent tools (cloud-agnostic, live in LangGraph agent):
  - execute_code(python_code)        — Monty sandbox, pre-authenticated session in allowlist

This separation means adding Azure tomorrow requires only a new Azure MCP server.
Zero changes to the agent. Zero changes to Monty. The execute_code tool stays identical.

---

## Authentication Flow

Long-lived AWS credentials live exclusively in the MCP server environment.
The agent never sees them.

1. Agent calls get_temp_credentials() from AWS MCP server at session start
2. MCP server calls AWS STS, returns short-lived access key + secret + session token
3. Agent builds boto3.Session from those tokens
4. Session is passed into Monty allowlist: {"session": boto3_session}
5. LLM writes code using session.client("ec2") — credentials are never in generated code
6. Tokens expire in 15–60 min; even if leaked, blast radius is minimal

---

## Architectural Vision: Why MCP Servers Are the Right Scaling Boundary

This project intentionally scopes to AWS + Boto3. But the architecture is designed
with multi-cloud in mind from the start.

MCP servers are the abstraction boundary between a unified agent and cloud-specific
implementations. Each cloud gets its own MCP server that encapsulates two things only:
  1. API discovery  — service schemas, operation signatures, parameter types
  2. Authentication — short-lived credentials via the cloud's STS equivalent

The agent and Monty sandbox remain unchanged regardless of how many clouds are connected.

The target multi-cloud architecture:

    User: "Find idle compute across all my clouds"
             ↓
    LangGraph Agent (one agent, one brain)
             ↓
    Discovery: agent queries whichever MCP servers are relevant
             → AWS MCP:   get_service_schema(), get_temp_credentials()
             → Azure MCP: get_service_schema(), get_temp_credentials()  [future]
             → GCP MCP:   get_service_schema(), get_temp_credentials()  [future]
             ↓
    LLM writes Python code using SDK signatures from the schema
             ↓
    execute_code → Monty sandbox (same sandbox, always, for every cloud)

Adding a new cloud = wire in a new FastMCP server. Zero changes to the agent or Monty.

Context at multi-cloud scale: the agent still carries exactly TWO tool schemas
(get_service_schema, get_temp_credentials) per connected cloud. Never the full API surface.

Separation of concerns:
- Monty:          secure execution runtime (cloud-agnostic)
- MCP servers:    cloud-specific discovery + auth contracts
- LangGraph agent: orchestration and reasoning
- LLM:            code generation

---

## Stack

- Agent: LangGraph (ReAct loop)
- LLM: Ollama / qwen3.6:27b (v1). AWS Bedrock (Claude or Nova) is the production target — swap via langchain-aws.
- Code execution: pydantic-monty (Rust-based secure Python interpreter)
- AWS SDK: Boto3 / botocore (service models shipped with SDK, no scraping)
- MCP server: FastMCP (AWS only, v1)
- API layer: FastAPI
- Observability: Langfuse (OTel session tracing) — deferred
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