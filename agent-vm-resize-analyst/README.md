# VM Resize Analyst Agent

A multi-agent orchestrator that calls the `monitor-recommendations-agent` for Azure Monitor data, then analyzes VM metrics to provide actionable resize recommendations with cost and performance tradeoffs.

## Architecture

```
User → [vm-resize-analyst-agent]
         ├── list_vms() → VM inventory from Azure Compute
         ├── get_monitor_metrics() → CPU, memory metrics from Azure Monitor
         ├── get_advisor_recommendations() → Advisor resize/cost suggestions
         ├── get_vm_resize_options() → valid resize targets per VM
         ├── get_available_vm_skus() → regional SKU specs
         └── estimate_cost_comparison() → pricing via Azure Retail Prices API
```

## Tools

| Tool | Purpose |
|------|---------|
| `list_vms` | Lists VMs in the subscription with size, location, OS, and resource ID |
| `get_monitor_metrics` | Queries Azure Monitor for CPU, memory, and other metrics |
| `get_advisor_recommendations` | Gets Advisor recommendations (cost, performance, etc.) |
| `get_available_vm_skus` | Lists VM sizes in a region with vCPUs, memory, disk specs |
| `get_vm_resize_options` | Gets valid resize targets for a specific VM (respects hardware constraints) |
| `estimate_cost_comparison` | Compares hourly/monthly costs between two SKUs via Azure Retail Prices API |

## Required RBAC Permissions

The agent's managed identity (principal ID from Foundry) needs:

| Role | Scope | Purpose |
|------|-------|---------|
| **Reader** | Subscription | List VMs, read compute SKUs, read Advisor recommendations |
| **Monitoring Reader** | Subscription | Query Azure Monitor metrics (CPU, memory, etc.) |

```bash
# After deploying the agent, get its principal_id from the version details, then:
PRINCIPAL_ID="<agent-principal-id>"
SUB_ID="<subscription-a-id>"

az role assignment create --assignee "$PRINCIPAL_ID" --role "Reader" --scope "/subscriptions/$SUB_ID"
az role assignment create --assignee "$PRINCIPAL_ID" --role "Monitoring Reader" --scope "/subscriptions/$SUB_ID"
```

> **Note:** `Monitoring Reader` is required to access Azure Monitor metrics data-plane. `Reader` alone is not sufficient for metric queries.

## Placeholders

Replace these values before deploying:

| Placeholder | Description |
|-------------|-------------|
| `<subscription-a-id>` | Your Azure subscription ID |
| `<your-acr>` | Your ACR name (e.g., `myregistry`) |
| `<agent-principal-id>` | Principal ID from `create_version()` output |

## Deployment

```bash
# 1. Build container
az acr build --registry <your-acr> --image vm-resize-analyst-agent:latest .

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
