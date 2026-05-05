# Copilot Instructions — Microsoft Foundry Hosted Agents

> This file provides Copilot with persistent context about this repo's architecture, patterns, and gotchas.
> Read this before making any changes to agent code, infrastructure, or deployment scripts.

---

## Repo Overview

This repo is a **reference architecture** for building Microsoft Foundry hosted agents with MCP tool connections. It contains:
- Two hosted agents (`agent-monitor-recommendations`, `agent-vm-resize-analyst`) deployed as containers
- AMPLS infrastructure for private observability
- A reusable Jupyter evaluation notebook
- Foundry project scaffolding

**Key technologies:** Microsoft Foundry, Hosted Agents (Responses Protocol), Azure Monitor, Azure Compute, Azure Advisor, ACR, Managed Identity, RBAC, AMPLS

---

## Current Deployment State

| Agent | Version | Status | Principal ID | ACR Image |
|-------|---------|--------|--------------|-----------|
| `monitor-recommendations-agent` | v4 | active | `<monitor-agent-principal-id>` | `<your-acr>.azurecr.io/monitor-recommendations-agent:latest` |
| `vm-resize-analyst-agent` | v2 | active | `<resize-agent-principal-id>` | `<your-acr>.azurecr.io/vm-resize-analyst-agent:latest` |

**Project endpoint:** `https://<your-ai-account>.services.ai.azure.com/api/projects/<your-project-name>`  
**Subscription:** `<subscription-a-id>`  
**Resource group:** `<your-resource-group>`  
**Model deployment:** `gpt-4.1-mini`  
**ACR:** `<your-acr>`

---

## Deployment & Updates

- Pushing a new image to ACR does NOT auto-update a running agent — you must call `client.agents.create_version()` to trigger image pull.
- **Full redeploy cycle:** code change → `az acr build` → `client.agents.create_version()` → verify RBAC on new principal.
- Agent versions are immutable — each deploy creates a new version number (v1, v2, v3...).
- Traffic routing uses `@latest` — creating a new version automatically makes it live.
- `create_version()` MUST include `headers={"Foundry-Features": "HostedAgents=V1Preview"}` — without it you get `preview_feature_required` error.
- **After every new version:** check the new `principal_id` and re-assign RBAC roles. Each version gets a NEW managed identity.

### Deploy Script Pattern

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())

version = client.agents.create_version(
    agent_name="vm-resize-analyst-agent",
    headers={"Foundry-Features": "HostedAgents=V1Preview"},
    definition={
        "kind": "hosted",
        "container_protocol_versions": [{"protocol": "responses", "version": "1.0.0"}],
        "cpu": "0.5",
        "memory": "1Gi",
        "image": "<your-acr>.azurecr.io/vm-resize-analyst-agent:latest",
        "environment_variables": {
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
            "AZURE_SUBSCRIPTION_ID": "<subscription-a-id>",
        },
    },
)

# Get the new principal_id for RBAC
principal_id = version._data["instance_identity"]["principal_id"]
print(f"New principal_id: {principal_id}")
# Then assign roles:
# az role assignment create --assignee {principal_id} --role "Reader" --scope /subscriptions/{sub_id}
# az role assignment create --assignee {principal_id} --role "Monitoring Reader" --scope /subscriptions/{sub_id}
```

---

## Agent Architecture

- Tools are Python functions decorated with `@tool` and registered in `tools=[]` passed to `Agent()`.
- Agent instructions (system prompt) are defined inline in `AGENT_INSTRUCTIONS` — document all available tools there.
- The agent uses `DefaultAzureCredential` — in Foundry this resolves to the managed identity (`instance_identity`).
- Agents implement the **Responses Protocol** — the container receives prompts and returns structured responses.
- Agents do NOT expose a public HTTP endpoint. They are invoked through the Foundry portal/UI or via the Foundry SDK internally.

### Tool Design Guidelines

- Keep tool descriptions clear and action-oriented — the LLM uses these to decide which tool to call.
- Include required parameters in the description (e.g., "requires resource_id").
- Cap tool results to 25-50 items — oversized responses confuse the LLM.
- Return structured JSON from tools — the LLM formats this for the user.
- Use specific prompts in tests (include resource IDs, names) — vague prompts may not trigger tools.

---

## RBAC & Permissions (Critical — assign BEFORE testing)

### Required Roles

| Role | Scope | Purpose | When Needed |
|------|-------|---------|-------------|
| `Reader` | Subscription | List VMs, SKUs, Advisor recommendations | Always |
| `Monitoring Reader` | Subscription | Query Azure Monitor metrics data-plane | Always (Reader alone is NOT enough) |
| `Azure AI Developer` | AI Services account | Foundry project access | Only if agent calls other agents |
| `Cognitive Services User` | AI Services account | `agents/read` data-plane action | Only if agent calls other agents |

### RBAC Checklist for New Agent Versions

1. Deploy new version: `client.agents.create_version(...)`
2. Get principal_id: `version._data["instance_identity"]["principal_id"]`
3. Assign Reader: `az role assignment create --assignee {pid} --role "Reader" --scope /subscriptions/{sub}`
4. Assign Monitoring Reader: `az role assignment create --assignee {pid} --role "Monitoring Reader" --scope /subscriptions/{sub}`
5. **Wait 1-2 minutes** for RBAC propagation before testing
6. Verify with evaluation notebook

### Diagnosing Permission Errors

- `PermissionDenied: Principal does not have access to API/Operation` → Missing `Reader` or `Monitoring Reader` on subscription
- `Principal lacks data action AIServices/agents/read` → Missing `Cognitive Services User` on AI Services account
- Agent lists VMs but metrics return empty → Has `Reader` but missing `Monitoring Reader`
- Works in portal but not in agent → Check you assigned roles to the agent's principal_id, not your own

---

## Multi-Agent Patterns

### ❌ What Doesn't Work (in current SDK)

- Hosted agents cannot call each other via HTTP — there's no public endpoint for agent invocation.
- The "connected agents" API requires publishing agents as "applications" (separate from agent registration).
- The threads/runs API is NOT available in `azure-ai-projects` SDK v2 for hosted agents.
- The path `POST /agents/{name}/openai/responses` exists but requires an API version that isn't documented yet.

### ✅ Recommended Pattern: Embedded Tools

Embed shared tools directly in each agent. Trade-offs:
- ✅ No inter-agent auth complexity
- ✅ No latency from HTTP round-trips
- ✅ Each agent is independently deployable
- ⚠️ Some tool code duplication (acceptable for 5-10 tools)

### Future: When Inter-Agent Becomes Available

If Foundry adds a stable agent-to-agent API:
- The endpoint pattern will likely be `POST /agents/{name}/openai/responses` with a specific api-version
- The calling agent will need `Cognitive Services User` on the AI Services account
- Each agent will need to be published as an "application" in addition to being registered as an agent

---

## Code Patterns

### Azure Monitor API

```python
# ✅ CORRECT — ISO 8601 strings
metrics = monitor_client.metrics.list(
    resource_uri=resource_id,
    metricnames="Percentage CPU,Available Memory Bytes",
    timespan="PT24H",      # Duration, not absolute timestamps
    interval="PT1H",       # Time grain — MUST be string, not timedelta
    aggregation="Average",
)

# ❌ WRONG — causes "Invalid time grain" error
from datetime import timedelta
metrics = monitor_client.metrics.list(
    interval=timedelta(hours=1),  # SDK does NOT serialize this correctly
)
```

### Tool Result Formatting

```python
# Cap results and return structured data
vms = list(compute_client.virtual_machines.list_all())[:25]
return json.dumps([{
    "name": vm.name,
    "size": vm.hardware_profile.vm_size,
    "location": vm.location,
    "resource_group": vm.id.split("/")[4],
} for vm in vms])
```

### Container Dependencies

- All SDK dependencies go in `requirements.txt` — the Dockerfile runs `pip install -r requirements.txt` at build time.
- Key packages: `azure-identity`, `azure-mgmt-compute`, `azure-mgmt-monitor`, `azure-mgmt-advisor`, `azure-ai-projects`
- The container uses `DefaultAzureCredential()` which picks up the managed identity automatically.

---

## Evaluation Notebook

The `agent-evaluation-checklist.ipynb` tests 5 areas:

1. **Infrastructure** — ACR image exists, agent registered, version active
2. **Identity & RBAC** — principal_id retrieved, all roles assigned
3. **Tool Connectivity** — each Azure API is reachable with current credentials
4. **Tool Selection** — LLM picks the correct tool for test prompts (uses chat completions with tool definitions)
5. **End-to-End** — full agent loop: prompt → LLM tool_call → execute tool against live APIs → LLM final response

### Running After Changes

```powershell
# Quick headless validation
python -m nbconvert --to notebook --execute agent-evaluation-checklist.ipynb --output results.ipynb --ExecutePreprocessor.timeout=180

# Interactive in browser
python -m notebook agent-evaluation-checklist.ipynb
```

### Customizing for New Agents

Edit the `AGENT_CONFIG` cell — change `agent_name`, `expected_tools`, `required_roles`, and `tool_selection_tests`.

---

## Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `preview_feature_required: HostedAgents=V1Preview` | Missing preview header on SDK calls | Add `headers={"Foundry-Features": "HostedAgents=V1Preview"}` to `create_version()` |
| `Principal lacks data action AIServices/agents/read` | Missing Cognitive Services role | Assign `Cognitive Services User` on the AI Services account |
| `Principal does not have access to API/Operation` | Missing monitoring/compute role | Assign `Monitoring Reader` + `Reader` on the subscription |
| `Invalid time grain` / metrics query failure | `interval=timedelta(...)` instead of ISO string | Use `"PT1H"` not `timedelta(hours=1)` |
| `DeploymentNotFound` when using agent as model name | Hosted agents aren't OpenAI deployments | Use the Foundry portal to interact; agents don't have public endpoints |
| Hosted agent cannot call another hosted agent | Threads/runs API doesn't exist for hosted agents | Embed tools directly |
| Tool selection test fails (no tool called) | Prompt too vague for LLM to pick a tool | Make test prompts specific — include resource IDs, regions, VM names |
| `az acr build` timeout | Large context or slow network | Add `.dockerignore` to exclude `.venv`, `__pycache__`, `.git` |
| RBAC assigned but still getting errors | Propagation delay | Wait 1-2 minutes; also verify principal_id matches the ACTIVE version |
| Agent works, then stops after redeploy | New version = new principal_id | Re-assign RBAC to the new principal from `get_version()._data["instance_identity"]` |

---

## File Conventions

| Path | Purpose |
|------|---------|
| `agent-*/main.py` | Agent entry point with tool definitions |
| `agent-*/Dockerfile` | Python 3.12-slim based container |
| `agent-*/requirements.txt` | Pip dependencies |
| `agent-*/agent.yaml` | Hosted agent runtime config (CPU, memory) |
| `agent-*/agent.manifest.yaml` | Foundry registration manifest |
| `agent-*/.foundry/agent-metadata.yaml` | Development metadata |
| `agent-*/.env.example` | Required environment variables template |
| `infra/*.bicep` | AMPLS infrastructure as code |
| `scripts/*.ps1` | Deployment automation |

