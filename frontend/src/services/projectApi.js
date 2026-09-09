import httpClient from '../api/httpClient'

export const projectApi = {
  create: (name, description = '') =>
    httpClient.post('/projects/', { name, description }),

  list: () =>
    httpClient.get('/projects/'),

  get: (id) =>
    httpClient.get(`/projects/${id}`),

  update: (id, data) =>
    httpClient.put(`/projects/${id}`, data),

  delete: (id) =>
    httpClient.delete(`/projects/${id}`),
    
  // Blueprints (Contracts)
  saveBlueprint: (projectId, name, blueprintJson, productType = 'Unknown') =>
    httpClient.post(`/projects/${projectId}/blueprints/`, { name, blueprint_json: blueprintJson, product_type: productType }),
    
  listBlueprints: (projectId) =>
    httpClient.get(`/projects/${projectId}/blueprints/`),
    
  loadBlueprint: (projectId, contractId) =>
    httpClient.get(`/projects/${projectId}/blueprints/${contractId}`),
    
  updateBlueprint: (projectId, contractId, name, blueprintJson) =>
    httpClient.put(`/projects/${projectId}/blueprints/${contractId}`, { name, blueprint_json: blueprintJson }),
    
  // Valuations
  runValuation: (projectId, contractId, assumptionSetId = null) =>
    httpClient.post(`/projects/${projectId}/valuations/`, { contract_id: contractId, assumption_set_id: assumptionSetId }),
    
  listValuationHistory: (projectId) =>
    httpClient.get(`/projects/${projectId}/valuations/`),
    
  getValuationResult: (projectId, runId) =>
    httpClient.get(`/projects/${projectId}/valuations/${runId}`)
}
