# Copilot Instructions — Azure AI Foundry Hosted Agents

## Deployment & Updates
- Pushing a new image to ACR does NOT auto-update a running Foundry agent — you must create a new agent version via the SDK (`client.agents.create_version()`) to trigger image pull.
- The full redeploy cycle is: code change → `az acr build` → `client.agents.create_version()` with the same image reference.
- Agent versions are immutable — each deploy creates a new version number (v1, v2, v3...) with its own status.
- Traffic routing uses `@latest` — the `version_selection_rules` route 100% traffic to `@latest` by default, so creating a new version automatically makes it live.
- When calling `create_version()`, you MUST include the header `headers={"Foundry-Features": "HostedAgents=V1Preview"}` — without it the API returns a `preview_feature_required` error.

## Agent Architecture
- Tools are Python functions decorated with `@tool` and registered in the `tools=[]` list passed to `Agent()`.
- Agent instructions (system prompt) are defined inline in `AGENT_INSTRUCTIONS` and should document all available tools.
- The agent uses `DefaultAzureCredential` — in Foundry it gets a managed identity (`instance_identity`) with a specific `principal_id`.

## RBAC & Permissions (Critical — assign BEFORE testing)
- Every new agent version gets a NEW managed identity `principal_id`. Check it via: `client.agents.get_version(agent_name, agent_version)._data['instance_identity']['principal_id']`
- **Required roles for agents that query Azure Monitor/Compute/Advisor:**
  - `Reader` on the subscription — for listing VMs, SKUs, Advisor recommendations
  - `Monitoring Reader` on the subscription — for querying Azure Monitor metrics (Reader alone is NOT enough for metrics data-plane)
- **If an agent needs to call other Foundry agents (connected agents pattern):**
  - `Azure AI Developer` on the AI Services account — for Foundry project access
  - `Cognitive Services User` on the AI Services account — for the `agents/read` data-plane action
- RBAC propagation takes 1-2 minutes after assignment. Don't test immediately.
- The `PermissionDenied: Principal does not have access to API/Operation` error almost always means a missing RBAC role on the subscription or resource.

## Multi-Agent Patterns
- **Hosted agents cannot easily call each other** — the Foundry "connected agents" API requires registering agents as "applications" (separate from agent registration) and uses a threads/runs API that is NOT available in the `azure-ai-projects` SDK v2 for hosted agents.
- **Recommended pattern:** Embed shared tools directly in each agent that needs them, rather than relying on inter-agent HTTP calls. This avoids permission complexity and latency.
- If you DO need inter-agent communication, the endpoint is: `POST /api/projects/{project}/applications/{appName}/protocols/openai/responses` with `Bearer` token (audience: `https://ai.azure.com/.default`) — but the agent must first be published as an "application."

## Code Patterns
- Use ISO 8601 duration strings for ALL Azure Monitor API parameters:
  - `timespan`: Use `"PT24H"` (not absolute timestamps) to avoid system clock issues.
  - `interval` (time grain): Use `"PT1H"` (not `timedelta(hours=1)`) — the SDK does NOT correctly serialize Python timedelta objects for this parameter.
- New SDK dependencies must be added to `requirements.txt` — the Dockerfile runs `pip install -r requirements.txt` at build time.
- Cap tool results (e.g., 25-50 items) to avoid oversized responses that confuse the LLM.

## Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `preview_feature_required: HostedAgents=V1Preview` | Missing preview header on SDK calls | Add `headers={"Foundry-Features": "HostedAgents=V1Preview"}` to `create_version()` |
| `Principal lacks data action AIServices/agents/read` | Missing Cognitive Services role | Assign `Cognitive Services User` on the AI Services account |
| `Principal does not have access to API/Operation` | Missing monitoring/compute role | Assign `Monitoring Reader` + `Reader` on the subscription |
| `Invalid time grain` / metrics query failure | `interval=timedelta(...)` instead of ISO string | Use `"PT1H"` not `timedelta(hours=1)` |
| Hosted agent cannot call another hosted agent | Threads/runs API doesn't exist for hosted agents | Embed tools directly, or publish agent as "application" first |

