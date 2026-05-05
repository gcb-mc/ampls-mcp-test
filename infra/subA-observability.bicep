targetScope = 'subscription'

@description('Azure region for all resources.')
param location string = 'eastus2'

@description('Resource group for observability resources.')
param rgName string = 'rg-observability-eastus2'

@description('Log Analytics workspace name.')
param workspaceName string = 'log-foundry-mcp-eastus2'

@description('Application Insights component name (workspace-based).')
param appInsightsName string = 'appi-foundry-mcp-eastus2'

@description('Data Collection Endpoint name.')
param dceName string = 'dce-foundry-mcp-eastus2'

@description('Tags applied to all resources.')
param tags object = {
  workload: 'foundry-mcp'
  managedBy: 'bicep'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
  tags: tags
}

module obs 'modules/observability.bicep' = {
  scope: rg
  name: 'observability-deploy'
  params: {
    location: location
    workspaceName: workspaceName
    appInsightsName: appInsightsName
    dceName: dceName
    tags: tags
  }
}

output workspaceId string = obs.outputs.workspaceId
output appInsightsId string = obs.outputs.appInsightsId
output dceId string = obs.outputs.dceId
output workspaceName string = obs.outputs.workspaceName
output appInsightsName string = obs.outputs.appInsightsName
output dceName string = obs.outputs.dceName
output rgName string = rg.name
