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

```bash
# Build container (must be linux/amd64)
docker build --platform linux/amd64 -t monitor-recommendations-agent .

# Tag and push to your ACR
docker tag monitor-recommendations-agent <your-acr>.azurecr.io/monitor-recommendations-agent:latest
docker push <your-acr>.azurecr.io/monitor-recommendations-agent:latest
```

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
