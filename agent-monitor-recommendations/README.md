# Azure Monitor Recommendations Agent

A hosted Foundry agent that analyzes Azure Advisor recommendations and Azure Monitor metrics to provide prioritized, actionable recommendations for your Azure subscription.

## Capabilities

| Tool | Description |
|------|-------------|
| `get_advisor_recommendations` | Fetches Azure Advisor recommendations (Cost, Performance, Reliability, Security, OperationalExcellence) |
| `get_monitor_alerts` | Lists active Azure Monitor alert rules |
| `get_monitor_metrics` | Queries resource-level metrics (CPU, memory, etc.) |
| `get_activity_log` | Reviews recent errors/warnings in the activity log |

## Setup

### Prerequisites

- Python 3.12+
- Azure CLI authenticated (`az login`)
- Access to the target Azure subscription
- A deployed model in your Foundry project (e.g., `gpt-4.1-mini`)

### Local Development

```bash
cd agent-monitor-recommendations

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your values

# Run locally
python main.py
```

The agent starts on `http://localhost:8088`. Send requests to `POST http://localhost:8088/responses`.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `FOUNDRY_PROJECT_ENDPOINT` | Your Foundry project endpoint URL |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model deployment name (e.g., `gpt-4.1-mini`) |
| `AZURE_SUBSCRIPTION_ID` | Subscription to query for recommendations |

### Deploy to Foundry

#### 1. Build & Push Image (ACR Cloud Build — recommended)

```bash
cd agent-monitor-recommendations

az acr build \
  --registry <your-acr-name> \
  --resource-group <your-rg> \
  --image monitor-recommendations-agent:latest \
  --platform linux/amd64 .
```

Or with local Docker:

```bash
docker build --platform linux/amd64 -t <your-acr>.azurecr.io/monitor-recommendations-agent:latest .
az acr login --name <your-acr>
docker push <your-acr>.azurecr.io/monitor-recommendations-agent:latest
```

#### 2. Register the Agent in Foundry

```python
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

client = AIProjectClient(
    endpoint="<your-project-endpoint>",
    credential=DefaultAzureCredential(),
    allow_preview=True
)

client.agents.create_version(
    agent_name="monitor-recommendations-agent",
    definition={
        "kind": "hosted",
        "image": "<your-acr>.azurecr.io/monitor-recommendations-agent:latest",
        "cpu": "1",
        "memory": "2Gi",
        "container_protocol_versions": [{"protocol": "responses", "version": "1.0.0"}],
        "environment_variables": {
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
            "AZURE_SUBSCRIPTION_ID": "<your-subscription-id>"
        }
    },
    description="Azure Monitor Recommendations Agent"
)
```

> **Note:** `FOUNDRY_PROJECT_ENDPOINT` is automatically injected by the platform — do not include it in `environment_variables`.

#### 3. Assign RBAC (Required)

The agent's managed identity needs these roles to access Azure Monitor and Advisor data:

| Role | Scope | Purpose |
|------|-------|---------|
| **Azure AI User** | AI Services account | Invoke LLM models |
| **AcrPull** | Container Registry | Pull container image |
| **Monitoring Reader** | Target subscription | Read metrics, alerts, activity logs |
| **Reader** | Target subscription | Read Advisor recommendations |

```bash
# Get the agent's principal ID from the create_version response (instance_identity.principal_id)
AGENT_PRINCIPAL_ID=<from-agent-response>
SUBSCRIPTION_ID=<your-subscription-id>
AI_ACCOUNT_ID=<your-ai-services-resource-id>
ACR_ID=<your-acr-resource-id>

# LLM access
az role assignment create --assignee-object-id $AGENT_PRINCIPAL_ID \
  --assignee-principal-type ServicePrincipal \
  --role "Azure AI User" --scope $AI_ACCOUNT_ID

# ACR pull
az role assignment create --assignee-object-id $AGENT_PRINCIPAL_ID \
  --assignee-principal-type ServicePrincipal \
  --role "AcrPull" --scope $ACR_ID

# Monitor & Advisor access
az role assignment create --assignee-object-id $AGENT_PRINCIPAL_ID \
  --assignee-principal-type ServicePrincipal \
  --role "Monitoring Reader" --scope /subscriptions/$SUBSCRIPTION_ID

az role assignment create --assignee-object-id $AGENT_PRINCIPAL_ID \
  --assignee-principal-type ServicePrincipal \
  --role "Reader" --scope /subscriptions/$SUBSCRIPTION_ID
```

> **Important:** Also assign the same roles to the **blueprint identity** (from the agent response `blueprint.principal_id`).

#### 4. Wait & Test

RBAC propagation takes 2–5 minutes. Then test in the [Foundry Playground](https://ai.azure.com) or via the SDK.

## Example Prompts

- "Give me all recommendations for my subscription"
- "What are the top cost optimization opportunities?"
- "Show me any critical reliability or security issues"
- "Check the metrics for my VM `/subscriptions/.../Microsoft.Compute/virtualMachines/myVM`"
- "What errors happened in the last 12 hours?"
- "Give me a prioritized action plan for this subscription"

## Architecture

```
User → Foundry Agent Service → This Agent (container)
                                    ├── Azure Advisor API (recommendations)
                                    ├── Azure Monitor API (metrics, alerts)
                                    └── Azure Activity Log API (events)
```

The agent uses `DefaultAzureCredential` for authentication, supporting managed identity in production and Azure CLI/VS Code credentials locally.
