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
| `FOUNDRY_PROJECT_ENDPOINT` | Your Foundry project endpoint URL (auto-injected in hosted mode) |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Model deployment name (e.g., `gpt-4.1-mini`) |
| `AZURE_SUBSCRIPTION_ID` | Subscription to query for recommendations |
| `AZURE_TENANT_ID` | Entra tenant ID (for OBO flow) |
| `AZURE_CLIENT_ID` | App registration client ID (for OBO flow) |
| `AZURE_CLIENT_SECRET` | App registration client secret (for OBO flow) |

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
User → Caller App → Foundry Agent Service → This Agent (container)
                         │                       ├── Azure Advisor API (OBO credential)
                         │                       ├── Azure Monitor API (OBO credential)
                         │                       └── Azure Activity Log API (OBO credential)
                         │
                         └── x-client-authorization: Bearer <user-token>
```

The agent uses **On-Behalf-Of (OBO) flow** to access Azure APIs as the calling user. The caller's token is passed via the `x-client-authorization` header and exchanged for a downstream token scoped to `https://management.azure.com/.default`.

## Caller Identity Pass-Through (OBO)

This agent requires the caller to pass their identity token so it accesses Azure APIs with the caller's permissions (not a shared managed identity).

### How It Works

1. The calling application authenticates the user and obtains a token
2. The caller includes `x-client-authorization: Bearer <user-token>` in the request to the Foundry agent
3. The agent extracts the token from `context.client_headers` (the platform forwards `x-client-*` prefixed headers)
4. The agent uses `OnBehalfOfCredential` to exchange the user token for a downstream Azure Management token
5. Azure Monitor/Advisor APIs are called with the user's delegated identity

### Entra App Registration Setup

You need an Entra ID (Azure AD) app registration for the OBO exchange:

#### Step 1: Create the App Registration

```bash
az ad app create --display-name "monitor-recommendations-agent-obo"
```

Note the `appId` (client ID) from the output.

#### Step 2: Create a Client Secret

```bash
az ad app credential reset --id <app-id> --display-name "obo-secret"
```

Note the `password` (client secret) from the output.

#### Step 3: Add API Permissions

The app needs delegated permission to Azure Management:

```bash
# Azure Service Management - user_impersonation
az ad app permission add \
  --id <app-id> \
  --api 797f4846-ba00-4fd7-ba43-dac1f8f63013 \
  --api-permissions 41094075-9dad-400e-a0bd-54e686782033=Scope
```

Grant admin consent:

```bash
az ad app permission admin-consent --id <app-id>
```

#### Step 4: Expose an API (optional, for first-party callers)

If you want callers to request a token scoped to your agent app:

```bash
az ad app update --id <app-id> \
  --identifier-uris "api://<app-id>"

az ad app permission add \
  --id <caller-app-id> \
  --api <app-id> \
  --api-permissions <scope-id>=Scope
```

#### Step 5: Configure Environment

Set the following in your agent's environment variables (in Foundry deployment or `.env` locally):

| Variable | Value |
|----------|-------|
| `AZURE_TENANT_ID` | Your Entra tenant ID |
| `AZURE_CLIENT_ID` | The app registration's client ID |
| `AZURE_CLIENT_SECRET` | The client secret created in Step 2 |

### Calling the Agent with OBO

When invoking the agent, the caller must include the `x-client-authorization` header:

```python
import requests

# The user's access token (obtained via MSAL, az cli, etc.)
user_token = "<user-bearer-token>"

response = requests.post(
    "https://<foundry-endpoint>/agents/<agent-name>/responses",
    headers={
        "Authorization": "Bearer <platform-auth-token>",
        "x-client-authorization": f"Bearer {user_token}",
        "Content-Type": "application/json",
    },
    json={
        "input": "What are my Azure Advisor recommendations?",
        "session": {"id": "test-session"},
    }
)
```

> **Important:** The `Authorization` header authenticates to Foundry. The `x-client-authorization` header carries the user's token for downstream Azure API access.

### Token Requirements

The user token passed in `x-client-authorization` must:
- Be a valid Entra ID access token
- Be scoped to the agent's app registration (`api://<client-id>/.default`) OR to `https://management.azure.com/.default`
- The user must have appropriate RBAC on the target subscription (Monitoring Reader, Reader)

### Alternative: Pattern B (Invocations Protocol)

If you need full `Request` object access (e.g., to read the standard `Authorization` header directly), you can switch to the invocations protocol:

```python
from agent_framework_foundry_hosting import InvocationsHostServer
from starlette.requests import Request

app = InvocationsHostServer()

@app.invoke_handler
async def handle_invoke(request: Request):
    # Full access to all headers
    auth_header = request.headers.get("authorization")
    # ... process request with full control
```

This requires changing `container_protocol_versions` to `invocations` in the agent registration and gives you complete control over request handling.
