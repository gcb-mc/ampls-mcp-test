# AMPLS + Microsoft Foundry Observability Setup

This repo provides Bicep templates and scripts to deploy a cross-subscription observability stack with Azure Monitor Private Link Scope (AMPLS) for Foundry projects.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│ Subscription A (Observability Owner)                                │
│                                                                     │
│  rg-observability-eastus2                                           │
│  ├── Log Analytics Workspace (log-foundry-mcp-eastus2)              │
│  ├── Application Insights (appi-foundry-mcp-eastus2)                │
│  └── Data Collection Endpoint (dce-foundry-mcp-eastus2)             │
└─────────────────────────────────────────────────────────────────────┘
        │
        │  Resource IDs shared via outputs/subA-outputs.json
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Subscription B (Workload Owner)                                     │
│                                                                     │
│  AMPLS + Private Endpoint → connects to Sub A resources             │
│  Azure Microsoft Foundry Project → sends telemetry via AMPLS               │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- [Azure CLI](https://aka.ms/installazurecli) (v2.60+)
- [Azure Developer CLI (azd)](https://aka.ms/azure-dev/install)
- PowerShell 7+ (`pwsh`)
- Owner or Contributor role on both subscriptions
- Both subscriptions must be in the same Azure AD tenant

## Quick Start

### Step 1: Deploy Observability Resources (Subscription A)

```powershell
# Login to your tenant
az login --tenant <your-tenant-id>

# Run the deployment script
pwsh -ExecutionPolicy Bypass -File ./scripts/deploy-subA.ps1 -SubA "<subscription-a-id>" -Location "eastus2"
```

This deploys:
- **Log Analytics Workspace** — centralized log storage
- **Application Insights** (workspace-based) — APM telemetry
- **Data Collection Endpoint** — ingestion endpoint for AMPLS

Outputs are saved to `./outputs/subA-outputs.json`. Share the three resource IDs with the Sub B owner:
- `workspaceId`
- `appInsightsId`
- `dceId`

### Step 2: Deploy AMPLS & Private Endpoint (Subscription B)

> ⚠️ This step is performed by the Subscription B owner using `deploy-subB.ps1` (not included yet — pending Sub B setup).

The Sub B owner will:
1. Create an Azure Monitor Private Link Scope (AMPLS)
2. Link Sub A's workspace, App Insights, and DCE to the AMPLS
3. Create a private endpoint in their VNet pointing to the AMPLS

### Step 3: Provision Azure Microsoft Foundry Project

```powershell
cd foundry-project

# Initialize from the azd starter template
azd init -t https://github.com/Azure-Samples/azd-ai-starter-basic -e <project-name> --no-prompt

# Set location and enable hosted agents
azd env set AZURE_LOCATION eastus2
azd env set ENABLE_HOSTED_AGENTS true

# Provision (takes ~5 minutes)
azd provision --no-prompt
```

This creates:
- Microsoft Foundry account + project
- Container Registry (for hosted agents)
- Capability host (agent runtime)
- Application Insights (project-level)
- Log Analytics workspace (project-level)

### Step 4: Verify End-to-End

Once Sub B deploys the AMPLS private endpoint:
1. Go to **Azure Portal → AMPLS resource → Private endpoint connections**
2. Verify the connection is auto-approved (same tenant)
3. Deploy a test agent to the Foundry project and confirm traces flow to Sub A's App Insights

## Repository Structure

```
ampls-mcp-test/
├── README.md                        # This file
├── .github/
│   └── copilot-instructions.md     # Lessons learned & patterns for hosted agents
├── infra/
│   ├── subA-observability.bicep     # Subscription-level Bicep (creates RG + resources)
│   └── modules/
│       └── observability.bicep      # Resource-group-level module
├── scripts/
│   └── deploy-subA.ps1              # Deployment script for Sub A
├── foundry-project/
│   └── README.md                    # Instructions for Foundry project setup
├── agent-monitor-recommendations/   # Hosted agent: Azure Monitor & Advisor data collector
│   ├── main.py                      # 5 tools (list_vms, get_monitor_metrics, etc.)
│   ├── Dockerfile                   # Python 3.12-slim container
│   ├── requirements.txt
│   └── README.md
├── agent-vm-resize-analyst/         # Hosted agent: VM resize analysis & cost comparison
│   ├── main.py                      # 6 tools (list_vms, get_monitor_metrics, get_advisor_recommendations, get_available_vm_skus, get_vm_resize_options, estimate_cost_comparison)
│   ├── Dockerfile
│   ├── agent.yaml                   # Hosted agent config (CPU/memory)
│   ├── agent.manifest.yaml          # Foundry registration manifest
│   ├── .foundry/agent-metadata.yaml # Dev environment metadata
│   ├── .env.example
│   └── README.md
├── agent-evaluation-checklist.ipynb  # Reusable Jupyter notebook for agent validation
├── outputs/
│   └── .gitkeep                     # Placeholder (actual outputs are gitignored)
└── .gitignore
```

## Hosted Agents

This repo includes two Azure AI Foundry hosted agents that work together to help users analyze and resize VMs:

### agent-monitor-recommendations (v4)
Collects Azure Monitor metrics, activity logs, alerts, and Advisor recommendations. Deployed as a hosted agent container in ACR.

**Tools:** `list_vms`, `get_monitor_metrics`, `get_monitor_alerts`, `get_activity_log`, `get_advisor_recommendations`

### agent-vm-resize-analyst (v2)
Analyzes VM metrics and recommendations to provide resize options with cost comparisons. Embeds monitor tools directly for self-contained operation.

**Tools:** `list_vms`, `get_monitor_metrics`, `get_advisor_recommendations`, `get_available_vm_skus`, `get_vm_resize_options`, `estimate_cost_comparison`

### Deployment

```powershell
# Build and push to ACR
az acr build --registry cruxluiilsxlu4w --image <agent-name>:latest ./agent-<folder>/

# Register/update agent version via Python SDK (see agent README for details)
```

### Required RBAC for Agent Identities

| Role | Scope | Purpose |
|------|-------|---------|
| Reader | Subscription | List VMs, SKUs, Advisor recommendations |
| Monitoring Reader | Subscription | Query Azure Monitor metrics |
| Azure AI Developer | AI Services account | Agent-to-agent communication (if needed) |
| Cognitive Services User | AI Services account | Foundry API access |

---

## Agent Evaluation Checklist

A reusable Jupyter notebook (`agent-evaluation-checklist.ipynb`) to validate any hosted agent across 5 areas:

| Section | What it tests |
|---------|---------------|
| 1️⃣ Infrastructure | ACR image exists, agent registered, version active |
| 2️⃣ Identity & RBAC | Managed identity has all required role assignments |
| 3️⃣ Tool Connectivity | Each tool's backend API (Compute, Monitor, Advisor, Pricing) is reachable |
| 4️⃣ Tool Selection | LLM picks the correct tool for test prompts (accuracy %) |
| 5️⃣ End-to-End | Full agent response via deployed endpoint |

### Running the Evaluation Locally

```powershell
# Install dependencies
pip install jupyter azure-identity azure-ai-projects azure-mgmt-compute azure-mgmt-monitor azure-mgmt-advisor

# Make sure you're logged in
az login

# Option 1: Run in browser
python -m notebook agent-evaluation-checklist.ipynb

# Option 2: Run headless and get output
python -m nbconvert --to notebook --execute agent-evaluation-checklist.ipynb --output results.ipynb
```

### Customizing for a Different Agent

Edit the `AGENT_CONFIG` cell at the top of the notebook:
- `agent_name` — your agent's registered name
- `expected_tools` — list of tool function names
- `required_roles` — RBAC roles to validate
- `tool_selection_tests` — (prompt, expected_tool) pairs

---

## Customization

Edit the default parameters in `infra/subA-observability.bicep`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `location` | `eastus2` | Azure region |
| `rgName` | `rg-observability-eastus2` | Resource group name |
| `workspaceName` | `log-foundry-mcp-eastus2` | Log Analytics workspace name |
| `appInsightsName` | `appi-foundry-mcp-eastus2` | Application Insights name |
| `dceName` | `dce-foundry-mcp-eastus2` | Data Collection Endpoint name |

## Cleanup

```powershell
# Remove Sub A observability resources
az group delete --name rg-observability-eastus2 --yes --no-wait

# Remove Foundry project (from the foundry-project directory)
cd foundry-project && azd down --force --purge
```

## License

MIT
