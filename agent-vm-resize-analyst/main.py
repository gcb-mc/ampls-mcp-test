# Copyright (c) Microsoft. All rights reserved.

import os
import json
import requests

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv
from pydantic import Field
from typing_extensions import Annotated

load_dotenv(override=False)

SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
MONITOR_AGENT_NAME = os.environ.get("MONITOR_AGENT_NAME", "monitor-recommendations-agent")
PROJECT_ENDPOINT = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")

credential = DefaultAzureCredential()


@tool(approval_mode="never_require")
def call_monitor_agent(
    query: Annotated[
        str,
        Field(
            description="Natural language query to send to the monitor-recommendations-agent. "
            "Examples: 'list all VMs', 'get CPU and memory metrics for VM myvm in resource group myrg', "
            "'show Advisor recommendations for cost optimization'."
        ),
    ],
) -> str:
    """Invoke the monitor-recommendations-agent to gather Azure Monitor data, VM inventory, metrics, or Advisor recommendations. Use this tool to collect raw data before performing analysis."""
    try:
        client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)

        # Create a thread and run the monitor agent
        thread = client.agents.threads.create()
        client.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content=query,
        )

        run = client.agents.runs.create_and_process(
            thread_id=thread.id,
            agent_id=MONITOR_AGENT_NAME,
            headers={"Foundry-Features": "HostedAgents=V1Preview"},
        )

        if run.status != "completed":
            return f"Monitor agent run failed with status: {run.status}. Error: {getattr(run, 'last_error', 'unknown')}"

        # Get the agent's response
        messages = client.agents.messages.list(thread_id=thread.id)
        for msg in messages:
            if msg.role == "assistant":
                text_parts = [block.text.value for block in msg.content if hasattr(block, "text")]
                if text_parts:
                    return "\n".join(text_parts)

        return "Monitor agent returned no response."
    except Exception as e:
        return f"Error calling monitor agent: {str(e)}"


@tool(approval_mode="never_require")
def get_available_vm_skus(
    location: Annotated[
        str,
        Field(description="Azure region to list VM sizes for (e.g., 'eastus2', 'westus3')."),
    ],
    filter_family: Annotated[
        str,
        Field(
            description="Optional VM family prefix to filter results (e.g., 'Standard_D', 'Standard_E', 'Standard_B'). "
            "Leave empty to return all families."
        ),
    ] = "",
) -> str:
    """List available VM SKUs in a given Azure region with their specs (vCPUs, memory, disk). Use this to understand what resize options exist."""
    try:
        compute_client = ComputeManagementClient(credential, SUBSCRIPTION_ID)
        sizes = compute_client.virtual_machine_sizes.list(location)

        results = []
        for size in sizes:
            if filter_family and not size.name.startswith(filter_family):
                continue

            results.append({
                "name": size.name,
                "vcpus": size.number_of_cores,
                "memory_gb": round(size.memory_in_mb / 1024, 1),
                "max_data_disks": size.max_data_disk_count,
                "os_disk_size_mb": size.os_disk_size_in_mb,
                "temp_disk_size_mb": size.resource_disk_size_in_mb,
            })

            if len(results) >= 40:
                break

        if not results:
            return f"No VM sizes found in {location}" + (f" matching '{filter_family}'" if filter_family else "")

        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error listing VM SKUs: {str(e)}"


@tool(approval_mode="never_require")
def get_vm_resize_options(
    resource_group: Annotated[
        str,
        Field(description="Resource group containing the VM."),
    ],
    vm_name: Annotated[
        str,
        Field(description="Name of the VM to get resize options for."),
    ],
) -> str:
    """Get the list of valid resize targets for a specific VM. Not all SKUs are available for every VM due to hardware cluster constraints."""
    try:
        compute_client = ComputeManagementClient(credential, SUBSCRIPTION_ID)

        # Get current VM info
        vm = compute_client.virtual_machines.get(resource_group, vm_name)
        current_size = vm.hardware_profile.vm_size if vm.hardware_profile else "Unknown"

        # Get available sizes for this VM
        available = compute_client.virtual_machines.list_available_sizes(resource_group, vm_name)

        options = []
        for size in available:
            options.append({
                "name": size.name,
                "vcpus": size.number_of_cores,
                "memory_gb": round(size.memory_in_mb / 1024, 1),
                "max_data_disks": size.max_data_disk_count,
            })

            if len(options) >= 40:
                break

        result = {
            "vm_name": vm_name,
            "current_size": current_size,
            "current_location": vm.location,
            "available_resize_options": options,
        }

        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error getting resize options for {vm_name}: {str(e)}"


@tool(approval_mode="never_require")
def estimate_cost_comparison(
    current_sku: Annotated[
        str,
        Field(description="Current VM SKU name (e.g., 'Standard_D2s_v3')."),
    ],
    target_sku: Annotated[
        str,
        Field(description="Target VM SKU name to compare against (e.g., 'Standard_D4s_v3')."),
    ],
    region: Annotated[
        str,
        Field(description="Azure region for pricing (e.g., 'eastus2')."),
    ],
) -> str:
    """Compare estimated hourly costs between two VM SKUs using the Azure Retail Prices API. Returns pricing for Linux and Windows pay-as-you-go."""
    try:
        base_url = "https://prices.azure.com/api/retail/prices"
        results = {}

        for sku in [current_sku, target_sku]:
            # Query retail prices API (no auth required)
            filter_str = (
                f"armSkuName eq '{sku}' and "
                f"armRegionName eq '{region}' and "
                f"priceType eq 'Consumption' and "
                f"contains(meterName, 'Spot') eq false"
            )
            params = {"$filter": filter_str}
            response = requests.get(base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            sku_prices = {"linux": None, "windows": None}
            for item in data.get("Items", []):
                if "Low Priority" in item.get("skuName", ""):
                    continue
                if item.get("unitOfMeasure") != "1 Hour":
                    continue

                os_type = "windows" if "Windows" in item.get("productName", "") else "linux"
                if sku_prices[os_type] is None:
                    sku_prices[os_type] = {
                        "price_per_hour": item["retailPrice"],
                        "currency": item["currencyCode"],
                        "meter": item.get("meterName", ""),
                    }

            results[sku] = sku_prices

        # Calculate comparison
        comparison = {
            "current_sku": current_sku,
            "target_sku": target_sku,
            "region": region,
            "pricing": results,
        }

        # Add savings/cost delta if both prices available
        for os_type in ["linux", "windows"]:
            current_price = results.get(current_sku, {}).get(os_type)
            target_price = results.get(target_sku, {}).get(os_type)
            if current_price and target_price:
                delta = target_price["price_per_hour"] - current_price["price_per_hour"]
                monthly_delta = delta * 730  # ~730 hours/month
                comparison[f"{os_type}_monthly_delta_usd"] = round(monthly_delta, 2)
                comparison[f"{os_type}_direction"] = "more expensive" if delta > 0 else "cheaper"

        return json.dumps(comparison, indent=2)
    except Exception as e:
        return f"Error estimating costs: {str(e)}"


AGENT_INSTRUCTIONS = """You are a VM Resize Analyst Agent. You help users determine the best VM size for their workloads by analyzing current metrics and providing actionable resize recommendations.

## Your Multi-Agent Workflow:
1. **Data Gathering** — Use `call_monitor_agent` to invoke the monitor-recommendations-agent for:
   - VM inventory (names, current sizes, resource groups)
   - CPU and memory metrics for target VMs
   - Azure Advisor resize recommendations
2. **Analysis** — Use your own tools to:
   - List available resize targets for specific VMs (`get_vm_resize_options`)
   - Compare VM SKU specs (`get_available_vm_skus`)
   - Estimate cost differences (`estimate_cost_comparison`)
3. **Recommendation** — Synthesize findings into clear options for the user.

## How to Analyze:
- **Underutilized VMs**: Average CPU < 20% and available memory > 60% → recommend downsizing
- **Constrained VMs**: Average CPU > 80% or available memory < 20% → recommend upsizing
- **Right-sized VMs**: CPU 20-80% and memory usage moderate → confirm current size is appropriate

## Response Format:
Present recommendations as a structured comparison:

### VM: [name] (Current: [size])
| Metric | Current Value | Assessment |
|--------|--------------|------------|
| CPU Avg | X% | Under/Over/OK |
| Memory Available | X GB | Under/Over/OK |

**Resize Options:**
| Option | SKU | vCPUs | Memory | Monthly Cost Delta | Recommendation |
|--------|-----|-------|--------|-------------------|----------------|
| Downsize | ... | ... | ... | -$XX/mo | ✅ Recommended |
| Stay | ... | ... | ... | $0 | Current |
| Upsize | ... | ... | ... | +$XX/mo | If growth expected |

## Guidelines:
- Always start by calling the monitor agent to list VMs and get their metrics.
- For resize recommendations, always check what sizes are actually available for that specific VM (hardware constraints).
- Include cost impact in every recommendation.
- If Advisor already has a resize recommendation, highlight it and validate with metrics.
- Present at most 3 resize options per VM (downsize, stay, upsize) unless the user asks for more.
- Warn about potential impacts: resizing requires a VM restart, check for availability sets/zones constraints.
"""


def main():
    client = FoundryChatClient(
        project_endpoint=PROJECT_ENDPOINT,
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    )

    agent = Agent(
        client=client,
        instructions=AGENT_INSTRUCTIONS,
        tools=[call_monitor_agent, get_available_vm_skus, get_vm_resize_options, estimate_cost_comparison],
        default_options={"store": False},
    )

    server = ResponsesHostServer(agent)
    server.run()


if __name__ == "__main__":
    main()
