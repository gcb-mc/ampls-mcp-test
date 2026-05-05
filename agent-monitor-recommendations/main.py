# Copyright (c) Microsoft. All rights reserved.

import os
import json
from datetime import datetime, timedelta, timezone

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from azure.mgmt.advisor import AdvisorManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from dotenv import load_dotenv
from pydantic import Field
from typing_extensions import Annotated

# Load environment variables from .env file
load_dotenv(override=False)

SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
credential = DefaultAzureCredential()


@tool(approval_mode="never_require")
def get_advisor_recommendations(
    category: Annotated[
        str,
        Field(
            description="Filter by category: Cost, Performance, Reliability, Security, OperationalExcellence, or 'all' for everything."
        ),
    ] = "all",
) -> str:
    """Get Azure Advisor recommendations for the configured subscription. Returns recommendations with impact, category, and suggested actions."""
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
                    "description": rec.extended_properties.get("annContent", "") if rec.extended_properties else "",
                }
            )

            if len(recommendations) >= 25:
                break

        if not recommendations:
            return f"No Advisor recommendations found for category '{category}' in subscription {SUBSCRIPTION_ID}."

        return json.dumps(recommendations, indent=2)
    except Exception as e:
        return f"Error fetching Advisor recommendations: {str(e)}"


@tool(approval_mode="never_require")
def get_monitor_alerts(
    time_range_hours: Annotated[
        int, Field(description="How many hours back to look for alerts. Default is 24.")
    ] = 24,
) -> str:
    """Get recent Azure Monitor alerts for the configured subscription."""
    try:
        monitor_client = MonitorManagementClient(credential, SUBSCRIPTION_ID)
        alerts = []

        # List alert rules
        for rule in monitor_client.alert_rules.list_by_subscription():
            alerts.append(
                {
                    "name": rule.name,
                    "description": rule.description if rule.description else "N/A",
                    "condition": str(rule.condition) if rule.condition else "N/A",
                    "is_enabled": rule.is_enabled,
                    "severity": getattr(rule, "severity", "N/A"),
                    "location": rule.location if rule.location else "N/A",
                }
            )

            if len(alerts) >= 25:
                break

        if not alerts:
            return f"No Monitor alert rules found in subscription {SUBSCRIPTION_ID}."

        return json.dumps(alerts, indent=2)
    except Exception as e:
        return f"Error fetching Monitor alerts: {str(e)}"


@tool(approval_mode="never_require")
def get_monitor_metrics(
    resource_id: Annotated[
        str,
        Field(description="The full Azure resource ID to query metrics for."),
    ],
    metric_names: Annotated[
        str,
        Field(
            description="Comma-separated metric names to query (e.g., 'Percentage CPU,Available Memory Bytes'). Leave empty for default metrics."
        ),
    ] = "",
    time_range_hours: Annotated[
        int, Field(description="How many hours back to query metrics. Default is 24.")
    ] = 24,
) -> str:
    """Get Azure Monitor metrics for a specific resource. Returns metric values over the specified time range."""
    try:
        monitor_client = MonitorManagementClient(credential, SUBSCRIPTION_ID)

        # Use ISO 8601 duration format so Azure determines the time window
        # server-side, avoiding issues with incorrect local system clocks.
        timespan = f"PT{time_range_hours}H"

        kwargs = {
            "resource_uri": resource_id,
            "timespan": timespan,
            "interval": timedelta(hours=1),
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
                for data_point in ts.data[-5:]:  # Last 5 data points
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
def get_activity_log(
    time_range_hours: Annotated[
        int, Field(description="How many hours back to look at activity logs. Default is 24.")
    ] = 24,
    resource_group: Annotated[
        str,
        Field(description="Optional resource group name to filter activity logs."),
    ] = "",
) -> str:
    """Get Azure Monitor activity log entries for the subscription. Useful for identifying recent changes, failures, or warnings."""
    try:
        monitor_client = MonitorManagementClient(credential, SUBSCRIPTION_ID)

        # Use only a lower-bound filter to reduce sensitivity to clock drift.
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=time_range_hours)

        filter_str = f"eventTimestamp ge '{start_time.isoformat()}'"
        if resource_group:
            filter_str += f" and resourceGroupName eq '{resource_group}'"

        logs = []
        for event in monitor_client.activity_logs.list(filter=filter_str):
            level = event.level.value if event.level else "Unknown"
            if level in ("Error", "Warning", "Critical"):
                logs.append(
                    {
                        "timestamp": event.event_timestamp.isoformat() if event.event_timestamp else "N/A",
                        "level": level,
                        "operation": event.operation_name.value if event.operation_name else "N/A",
                        "status": event.status.value if event.status else "N/A",
                        "description": event.description if event.description else "N/A",
                        "resource_id": event.resource_id if event.resource_id else "N/A",
                        "caller": event.caller if event.caller else "N/A",
                    }
                )

            if len(logs) >= 25:
                break

        if not logs:
            return f"No warning/error activity log entries found in the last {time_range_hours} hours."

        return json.dumps(logs, indent=2)
    except Exception as e:
        return f"Error fetching activity logs: {str(e)}"


AGENT_INSTRUCTIONS = """You are an Azure Monitor Recommendations Agent. Your purpose is to analyze Azure Advisor recommendations, Monitor metrics, alerts, and activity logs for a subscription, and then provide actionable, prioritized recommendations.

## Your Capabilities:
1. **Advisor Recommendations** - Retrieve and analyze Azure Advisor recommendations across Cost, Performance, Reliability, Security, and Operational Excellence categories.
2. **Monitor Alerts** - Check active alert rules and their status.
3. **Resource Metrics** - Query specific resource metrics to identify performance issues.
4. **Activity Logs** - Review recent errors and warnings in the activity log.

## How You Work:
- When a user asks for recommendations, first gather data from Advisor and relevant Monitor sources.
- Analyze the data holistically to identify patterns and priorities.
- Present findings as structured, actionable recommendations with:
  - **Priority** (Critical, High, Medium, Low)
  - **Category** (Cost, Performance, Reliability, Security, Operations)
  - **Impact** description
  - **Action** - specific steps to remediate
  - **Affected resources**

## Guidelines:
- Always start by checking Advisor recommendations to get the broadest view.
- Cross-reference with activity logs to identify active issues.
- If the user asks about a specific resource, pull metrics for deeper analysis.
- Be concise but thorough. Group related recommendations together.
- Highlight quick wins (low effort, high impact) separately from long-term improvements.
- When you see cost optimization opportunities, include estimated savings if available.
"""


def main():
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    )

    agent = Agent(
        client=client,
        instructions=AGENT_INSTRUCTIONS,
        tools=[get_advisor_recommendations, get_monitor_alerts, get_monitor_metrics, get_activity_log],
        default_options={"store": False},
    )

    server = ResponsesHostServer(agent)
    server.run()


if __name__ == "__main__":
    main()
