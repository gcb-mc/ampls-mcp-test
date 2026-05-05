# AMPLS + Azure AI Foundry Observability Setup

This repo provides Bicep templates and scripts to deploy a cross-subscription observability stack with Azure Monitor Private Link Scope (AMPLS) for Azure AI Foundry projects.

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
│  Azure AI Foundry Project → sends telemetry via AMPLS               │
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

### Step 3: Provision Azure AI Foundry Project

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
- AI Foundry account + project
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
├── infra/
│   ├── subA-observability.bicep     # Subscription-level Bicep (creates RG + resources)
│   └── modules/
│       └── observability.bicep      # Resource-group-level module
├── scripts/
│   └── deploy-subA.ps1              # Deployment script for Sub A
├── foundry-project/
│   └── README.md                    # Instructions for Foundry project setup
└── outputs/
    └── .gitkeep                     # Placeholder (actual outputs are gitignored)
```

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
