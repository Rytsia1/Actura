import httpClient from '../api/httpClient'

export const WorkflowStep = {
  PROJECT: 'project',
  CONTRACT: 'contract',
  BLUEPRINT: 'blueprint'
}

export const workflowApi = {
  start: (name, description = '') =>
    httpClient.post('/workflow/start', { name, description }),

  getState: (projectId) =>
    httpClient.get(`/workflow/${projectId}/state`),

  addContract: (projectId, name, productType, blueprintJson = null) =>
    httpClient.post(`/workflow/${projectId}/contract`, { name, product_type: productType, blueprint_json: blueprintJson }),

  setAssumptions: (projectId, name, assumptions) =>
    httpClient.post(`/workflow/${projectId}/assumptions`, { name, assumptions }),

  runValuation: (projectId) =>
    httpClient.post(`/workflow/${projectId}/run`),

  getJobStatus: (jobId) =>
    httpClient.get(`/workflow/status/${jobId}`),

  pollValuation: async (jobId, onProgress) => {
    while (true) {
      const response = await workflowApi.getJobStatus(jobId)
      const data = response.data
      
      if (data.progress !== undefined) {
        onProgress(data.progress)
      }
      
      if (data.step === 'results' || data.status === 'failed') {
        return data
      }
      
      // Wait 1 second before polling again
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  }
}
