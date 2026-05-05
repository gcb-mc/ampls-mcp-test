# Copyright (c) Microsoft. All rights reserved.

import os
import json
import requests
from datetime import datetime, timedelta, timezone

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.advisor import AdvisorManagementClient
from dotenv import load_dotenv
from pydantic import Field
from typing_extensions import Annotated

load_dotenv(override=False)

SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
PROJECT_ENDPOINT = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")

credential = DefaultAzureCredential()


# ─── Data Gathering Tools (from monitor-recommendations-agent) ───────────────

@tool(approval_mode="never_require")
def list_vms(
    resource_group: Annotated[
        str,
        Field(
            description="Optional resource group name to filter VMs. Leave empty to list all VMs in the subscription."
        ),
    ] = "",
) -> str:
    """List virtual machines in the subscription (or a specific resource group). Returns VM name, resource group, location, size, OS type, and resource ID."""
    try:
        compute_client = ComputeManagementClient(credential, SUBSCRIPTION_ID)

        if resource_group:
            vms_iter = compute_client.virtual_machines.list(resource_group)
        else:
            vms_iter = compute_client.virtual_machines.list_all()

        vm_list = []
        for vm in vms_iter:
            rg = vm.id.split("/resourceGroups/")[1].split("/")[0] if vm.id else "N/A"

            vm_info = {
                "name": vm.name,
                "resource_group": rg,
                "location": vm.location,
                "vm_size": vm.hardware_profile.vm_size if vm.hardware_profile else "N/A",
                "os_type": vm.storage_profile.os_disk.os_type if vm.storage_profile and vm.storage_profile.os_disk else "N/A",
                "resource_id": vm.id,
            }

            if vm.instance_view and vm.instance_view.statuses:
                power_states = [s.display_status for s in vm.instance_view.statuses if s.code and s.code.startswith("PowerState/")]
                vm_info["power_state"] = power_states[0] if power_states else "Unknown"
            else:
                vm_info["power_state"] = "Unknown (use Azure Portal or request instance view)"

            vm_list.append(vm_info)
            if len(vm_list) >= 50:
                break

        if not vm_list:
            scope = f"resource group '{resource_group}'" if resource_group else f"subscription {SUBSCRIPTION_ID}"
            return f"No virtual machines found in {scope}."

        return json.dumps(vm_list, indent=2)
    except Exception as e:
        return f"Error listing VMs: {str(e)}"


@tool(approval_mode="never_require")
def get_monitor_metrics(
    resource_id: Annotated[
        str,
        Field(description="The full Azure resource ID to query metrics for."),
    ],
    metric_names: Annotated[
        str,
        Field(
            description="Comma-separated metric names to query (e.g., 'Percentage CPU,Available Memory Bytes')."
        ),
    ] = "",
    time_range_hours: Annotated[
        int, Field(description="How many hours back to query metrics. Default is 24.")
    ] = 24,
) -> str:
    """Get Azure Monitor metrics for a specific resource. Returns metric values over the specified time range."""
    try:
        monitor_client = MonitorManagementClient(credential, SUBSCRIPTION_ID)

        timespan = f"PT{time_range_hours}H"
        kwargs = {
            "resource_uri": resource_id,
            "timespan": timespan,
            "interval": "PT1H",
            "aggregation": "Average,Maximum,Minimum",
        }
        if metric_names:
            kwargs["metricnames"] = metric_names

        metrics_data = monitor_client.metrics.list(**kwargs)

        results = []
        for metric in metrics_data.value:
            metric_result = {
                "name": metric.name.value,
                "unit": metric.unit,
                "timeseries": [],
            }
            for ts in metric.timeseries:
                for data_point in ts.data[-5:]:
                    metric_result["timeseries"].append(
                        {
                            "timestamp": data_point.time_stamp.isoformat() if data_point.time_stamp else "N/A",
                            "average": data_point.average,
                            "maximum": data_point.maximum,
                            "minimum": data_point.minimum,
                        }
                    )
            results.append(metric_result)

        if not results:
            return f"No metrics found for resource: {resource_id}"

        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error fetching metrics: {str(e)}"


@tool(approval_mode="never_require")
def get_advisor_recommendations(
    category: Annotated[
        str,
        Field(
            description="Filter by category: Cost, Performance, Reliability, Security, OperationalExcellence, or 'all' for everything."
        ),
    ] = "all",
) -> str:
    """Get Azure Advisor recommendations for the configured subscription."""
    try:
        advisor_client = AdvisorManagementClient(credential, SUBSCRIPTION_ID)
        recommendations = []

        for rec in advisor_client.recommendations.list():
            rec_category = rec.category if rec.category else "Unknown"
            if category.lower() != "all" and rec_category.lower() != category.lower():
                continue

            recommendations.append(
                {
                    "name": rec.short_description.problem if rec.short_description else "N/A",
                    "solution": rec.short_description.solution if rec.short_description else "N/A",
                    "category": rec_category,
                    "impact": rec.impact if rec.impact else "Unknown",
                    "resource_id": rec.resource_metadata.resource_id if rec.resource_metadata else "N/A",
                }
            )
            if len(recommendations) >= 25:
                break

        if not recommendations:
            return f"No Advisor recommendations found for category '{category}'."

        return json.dumps(recommendations, indent=2)
    except Exception as e:
        return f"Error fetching Advisor recommendations: {str(e)}"


# ─── Analysis Tools (VM resize specific) ─────────────────────────────────────


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

## Your Workflow:
1. **Data Gathering** — Use your monitoring tools to collect data:
   - `list_vms` — Get VM inventory (names, current sizes, resource groups)
   - `get_monitor_metrics` — Get CPU and memory metrics for target VMs
   - `get_advisor_recommendations` — Get Advisor resize/cost recommendations
2. **Analysis** — Use your resize analysis tools:
   - `get_vm_resize_options` — List valid resize targets for a specific VM
   - `get_available_vm_skus` — Compare VM SKU specs in a region
   - `estimate_cost_comparison` — Get pricing difference between SKUs
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
- Always start by listing VMs, then get metrics for each.
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
        tools=[list_vms, get_monitor_metrics, get_advisor_recommendations, get_available_vm_skus, get_vm_resize_options, estimate_cost_comparison],
        default_options={"store": False},
    )

    server = ResponsesHostServer(agent)
    server.run()


if __name__ == "__main__":
    main()
