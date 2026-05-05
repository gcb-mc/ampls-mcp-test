# VM Resize Analyst Agent

A multi-agent orchestrator that calls the `monitor-recommendations-agent` for Azure Monitor data, then analyzes VM metrics to provide actionable resize recommendations with cost and performance tradeoffs.

## Architecture

```
User → [vm-resize-analyst-agent]
         ├── call_monitor_agent() → invokes monitor-recommendations-agent via Foundry API
         ├── get_vm_resize_options() → valid resize targets per VM
         ├── get_available_vm_skus() → regional SKU specs
         └── estimate_cost_comparison() → pricing via Azure Retail Prices API
```

## Tools

| Tool | Purpose |
|------|---------|
| `call_monitor_agent` | Invokes the monitor agent to get VM list, metrics, Advisor recommendations |
| `get_available_vm_skus` | Lists VM sizes in a region with vCPUs, memory, disk specs |
| `get_vm_resize_options` | Gets valid resize targets for a specific VM (respects hardware constraints) |
| `estimate_cost_comparison` | Compares hourly/monthly costs between two SKUs via Azure Retail Prices API |

## Required RBAC Permissions

The agent's managed identity (principal ID from Foundry) needs:

| Role | Scope | Purpose |
|------|-------|---------|
| **Reader** | Subscription | List VMs, read compute SKUs |
| **Azure AI Developer** | AI Services account | Model inference and Foundry project access |
| **Cognitive Services User** | AI Services account | Data-plane access for `agents/read` — required to invoke connected agents via Foundry API |

```bash
# After deploying the agent, get its principal_id from the version details, then:
PRINCIPAL_ID="<agent-principal-id>"
SUB_ID="f6eb08ce-f112-4889-9891-829161ecbd66"
AI_ACCOUNT="/subscriptions/$SUB_ID/resourceGroups/rg-ampls-foundry-test02/providers/Microsoft.CognitiveServices/accounts/ai-account-uxluiilsxlu4w"

az role assignment create --assignee "$PRINCIPAL_ID" --role "Reader" --scope "/subscriptions/$SUB_ID"
az role assignment create --assignee "$PRINCIPAL_ID" --role "Azure AI Developer" --scope "$AI_ACCOUNT"
az role assignment create --assignee "$PRINCIPAL_ID" --role "Cognitive Services User" --scope "$AI_ACCOUNT"
```

## Deployment

```bash
# 1. Build container
az acr build --registry cruxluiilsxlu4w --image vm-resize-analyst-agent:latest .

# 2. Create/update agent version in Foundry (via SDK or CLI)
# The agent will pull the :latest image on version creation

# 3. Assign RBAC (see above)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint URL |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model deployment name (e.g., `gpt-4.1-mini`) |
| `AZURE_SUBSCRIPTION_ID` | Target Azure subscription for VM analysis |
| `MONITOR_AGENT_NAME` | Name of the monitor agent to invoke (default: `monitor-recommendations-agent`) |
