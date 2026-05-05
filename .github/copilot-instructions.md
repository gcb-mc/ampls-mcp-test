# Copilot Instructions — Azure AI Foundry Hosted Agents

## Deployment & Updates
- Pushing a new image to ACR does NOT auto-update a running Foundry agent — you must create a new agent version via the SDK (`client.agents.create_version()`) to trigger image pull.
- The full redeploy cycle is: code change → `az acr build` → `client.agents.create_version()` with the same image reference.
- Agent versions are immutable — each deploy creates a new version number (v1, v2, v3...) with its own status.
- Traffic routing uses `@latest` — the `version_selection_rules` route 100% traffic to `@latest` by default, so creating a new version automatically makes it live.

## Agent Architecture
- Tools are Python functions decorated with `@tool` and registered in the `tools=[]` list passed to `Agent()`.
- Agent instructions (system prompt) are defined inline in `AGENT_INSTRUCTIONS` and should document all available tools.
- The agent uses `DefaultAzureCredential` — in Foundry it gets a managed identity (`instance_identity`) with a specific `principal_id`.

## Code Patterns
- Use ISO 8601 duration (`PT24H`) for Monitor metrics timespan instead of absolute timestamps to avoid system clock issues.
- New SDK dependencies must be added to `requirements.txt` — the Dockerfile runs `pip install -r requirements.txt` at build time.
- Cap tool results (e.g., 25-50 items) to avoid oversized responses that confuse the LLM.
