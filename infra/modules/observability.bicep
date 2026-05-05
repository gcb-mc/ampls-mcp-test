@description('Azure region for all resources.')
param location string

@description('Log Analytics workspace name.')
param workspaceName string

@description('Application Insights component name (workspace-based).')
param appInsightsName string

@description('Data Collection Endpoint name.')
param dceName string

@description('Tags applied to all resources.')
param tags object

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' = {
  name: dceName
  location: location
  tags: tags
  properties: {
    networkAcls: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

output workspaceId string = workspace.id
output appInsightsId string = appInsights.id
output dceId string = dce.id
output workspaceName string = workspace.name
output appInsightsName string = appInsights.name
output dceName string = dce.name
