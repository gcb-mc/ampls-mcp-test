# Azure AI Foundry Project Setup

This directory is where you initialize the Azure AI Foundry project using `azd`.

## Steps

### 1. Initialize the project

```powershell
cd foundry-project
azd init -t https://github.com/Azure-Samples/azd-ai-starter-basic -e <project-name> --no-prompt
```

### 2. Configure environment

```powershell
# Set the Azure region (must match your observability resources)
azd env set AZURE_LOCATION eastus2

# Enable hosted agents (provisions capability host + Container Registry)
azd env set ENABLE_HOSTED_AGENTS true
```

### 3. Provision infrastructure

```powershell
azd provision --no-prompt
```

This takes approximately 5 minutes and creates:

| Resource | Purpose |
|----------|---------|
| AI Foundry Account | Parent account for projects |
| AI Foundry Project | Workspace for agents and models |
| Container Registry | Stores hosted agent container images |
| Capability Host | Runtime for hosted agents |
| Application Insights | Project-level telemetry |
| Log Analytics Workspace | Project-level log storage |

### 4. Retrieve project details

```powershell
azd env get-values
```

Key values to note:
- `AZURE_AI_PROJECT_ENDPOINT` — endpoint for SDK/agent connections
- `AZURE_CONTAINER_REGISTRY_ENDPOINT` — ACR for pushing agent images
- `AZURE_RESOURCE_GROUP` — resource group name

### 5. Verify in portal

- [AI Foundry Portal](https://ai.azure.com) — manage agents and models
- [Azure Portal](https://portal.azure.com) — view resources and diagnostics

## Next Steps

After Sub B deploys the AMPLS private endpoint:
1. Configure the Foundry project's App Insights to route telemetry through the AMPLS
2. Deploy a test agent and verify traces appear in Sub A's Log Analytics workspace
3. Use the `observe` and `trace` workflows to validate end-to-end observability
