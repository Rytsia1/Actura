/**
 * Actuarial Engine API Service
 * Centralized API interface using Axios with global interceptors, automatic error handling, timeout safety, and AbortController signal support.
 */

import httpClient, { ActuaryApiError } from '../api/httpClient'

export { ActuaryApiError }

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
const API_BASE = BASE_URL ? `${BASE_URL}/api/v1` : '/api/v1'

/**
 * Health check endpoint
 * GET /api/v1/health
 */
export async function checkHealth(config = {}) {
  return await httpClient.get('/health', config)
}

/**
 * List all available mortality tables (built-in and custom uploaded)
 * GET /api/v1/tables
 */
export async function fetchTables(config = {}) {
  return await httpClient.get('/tables', config)
}

/**
 * Upload custom mortality table file (CSV or XTbML)
 * POST /api/v1/tables/upload
 * 
 * @param {FormData} formData - Contains 'file', 'table_name', 'table_description'
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} TableUploadResponse
 */
export async function uploadMortalityTable(formData, config = {}) {
  return await httpClient.post('/tables/upload', formData, config)
}

/**
 * Delete a custom mortality table
 * DELETE /api/v1/tables/{table_id}
 * 
 * @param {string} tableId - ID of table to delete
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} Status response
 */
export async function deleteMortalityTable(tableId, config = {}) {
  return await httpClient.delete(`/tables/${encodeURIComponent(tableId)}`, config)
}

/**
 * Run deterministic baseline valuation
 * POST /api/v1/valuation/deterministic
 * 
 * @param {Object} payload - DeterministicValuationRequest
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} DeterministicValuationResponse
 */
export async function runDeterministicValuation(payload, config = {}) {
  return await httpClient.post('/valuation/deterministic', payload, config)
}

/**
 * Run IFRS 17 standard valuation
 * POST /api/v1/valuation/ifrs17
 * 
 * @param {Object} payload - IFRS17ValuationRequest
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} IFRS17ValuationResponse
 */
export async function runIFRS17Valuation(payload, config = {}) {
  return await httpClient.post('/valuation/ifrs17', payload, config)
}

/**
 * Start asynchronous Monte Carlo stochastic simulation job
 * POST /api/v1/valuation/stochastic/async
 * 
 * @param {Object} payload - StochasticValuationRequest
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} AsyncJobCreateResponse { job_id, status }
 */
export async function startAsyncStochasticValuation(payload, config = {}) {
  return await httpClient.post('/valuation/stochastic/async', payload, config)
}

/**
 * Check status of background stochastic valuation job
 * GET /api/v1/valuation/stochastic/status/{job_id}
 * 
 * @param {string} jobId - UUID of the async job
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} AsyncJobStatusResponse
 */
export async function getStochasticJobStatus(jobId, config = {}) {
  return await httpClient.get(`/valuation/stochastic/status/${encodeURIComponent(jobId)}`, config)
}

/**
 * Start asynchronous Monte Carlo stochastic ESG simulation job
 * POST /api/v1/esg/simulate/async
 * 
 * @param {Object} payload - ESGSimulationRequest
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} AsyncJobCreateResponse { job_id, status }
 */
export async function startAsyncESGSimulation(payload, config = {}) {
  return await httpClient.post('/esg/simulate/async', payload, config)
}

/**
 * Fetch persistent run history jobs
 * GET /api/v1/jobs
 * 
 * @param {number} limit - Number of jobs to fetch
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Array>} Array of jobs
 */
export async function fetchJobs(limit = 100, config = {}) {
  return await httpClient.get(`/jobs?limit=${limit}`, config)
}

/**
 * Fetch a persistent job by ID
 * GET /api/v1/jobs/{job_id}
 * 
 * @param {string} jobId - The job ID
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} Job data
 */
export async function fetchJobById(jobId, config = {}) {
  return await httpClient.get(`/jobs/${encodeURIComponent(jobId)}`, config)
}

/**
 * Run synchronous stochastic valuation (legacy / fast simulation)
 * POST /api/v1/valuation/stochastic
 * 
 * @param {Object} payload - StochasticValuationRequest
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} StochasticValuationResponse
 */
export async function runStochasticValuation(payload, config = {}) {
  return await httpClient.post('/valuation/stochastic', payload, config)
}

/**
 * Upload seriatim portfolio CSV for parallel batch valuation
 * POST /api/v1/valuation/portfolio/csv
 * 
 * @param {FormData} formData - Multipart with 'file' and valuation parameters
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} PortfolioValuationResponse
 */
export async function uploadPortfolioCSV(formData, config = {}) {
  return await httpClient.post('/valuation/portfolio/csv', formData, config)
}

/**
 * Get direct download URL for synthetic portfolio CSV
 * 
 * @param {number} count - Number of policies to generate
 * @returns {string} URL string
 */
export function getSamplePortfolioCSVUrl(count = 1000) {
  return `${API_BASE}/valuation/portfolio/sample-csv?count=${count}`
}

/**
 * Run multi-factor sensitivity analysis & Tornado chart evaluation
 * POST /api/v1/valuation/sensitivity/tornado
 * 
 * @param {Object} payload - SensitivityRequest
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} SensitivityResponse
 */
export async function runSensitivityAnalysis(payload, config = {}) {
  return await httpClient.post('/valuation/sensitivity/tornado', payload, config)
}

/**
 * Run real-time stress testing with interactive slider shocks
 * POST /api/v1/valuation/stress-test
 * 
 * @param {Object} payload - StressTestRequest
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} StressTestResponse
 */
export async function runStressTest(payload, config = {}) {
  return await httpClient.post('/valuation/stress-test', payload, config)
}

/**
 * Simulate visual node-based contract graph DAG
 * POST /api/v1/contracts/simulate-graph
 * 
 * @param {Object} payload - ContractGraphPayload
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} SimulateGraphResponse
 */
export async function simulateContractGraph(payload, config = {}) {
  return await httpClient.post('/contracts/simulate-graph', payload, config)
}

/**
 * Generate a Term Life blueprint from simple guided parameters
 * POST /api/v1/contracts/guided/term-life
 * 
 * @param {Object} payload - GuidedTermLifeRequest
 * @param {Object} config - Optional Axios request config
 * @returns {Promise<Object>} ContractGraphPayload
 */
export async function generateGuidedTermLife(payload, config = {}) {
  return await httpClient.post('/contracts/guided/term-life', payload, config)
}

// ────────────────────────────────────────────────────────────
// Assumption Management
// ────────────────────────────────────────────────────────────

export async function fetchAssumptions(type = null) {
  const params = type ? { type } : {}
  return await httpClient.get('/assumptions', { params })
}

export async function fetchAssumptionHistory(id) {
  return await httpClient.get(`/assumptions/${id}/history`)
}

export async function createAssumption(payload) {
  return await httpClient.post('/assumptions', payload)
}

export async function createAssumptionVersion(id, payload) {
  return await httpClient.post(`/assumptions/${id}/version`, payload)
}

export async function updateAssumptionStatus(id, status) {
  return await httpClient.put(`/assumptions/${id}/status`, { status })
}

// ────────────────────────────────────────────────────────────
// Base Model & Scenario Management
// ────────────────────────────────────────────────────────────

export async function fetchBaseModels() {
  return await httpClient.get('/models')
}

export async function fetchBaseModel(id) {
  return await httpClient.get(`/models/${id}`)
}

export async function createBaseModel(payload) {
  return await httpClient.post('/models', payload)
}

export async function fetchScenarios(baseModelId = null, status = null) {
  const params = {}
  if (baseModelId) params.base_model_id = baseModelId
  if (status) params.status = status
  return await httpClient.get('/scenarios', { params })
}

export async function fetchScenario(id) {
  return await httpClient.get(`/scenarios/${id}`)
}

export async function createScenario(payload) {
  return await httpClient.post('/scenarios', payload)
}

export async function updateScenario(id, payload) {
  return await httpClient.put(`/scenarios/${id}`, payload)
}

export async function duplicateScenario(id, newName = null) {
  const params = newName ? { name: newName } : {}
  return await httpClient.post(`/scenarios/${id}/duplicate`, null, { params })
}

export async function validateScenario(id) {
  return await httpClient.post(`/scenarios/${id}/validate`)
}

export async function runScenario(id) {
  return await httpClient.post(`/scenarios/${id}/run`)
}

export async function deleteScenario(id) {
  return await httpClient.delete(`/scenarios/${id}`)
}

export async function fetchSensitivityDefaults() {
  return await httpClient.get('/sensitivity/defaults')
}

export async function runSensitivityAnalysisV2(payload, config = {}) {
  return await httpClient.post('/sensitivity/analyze', payload, config)
}

export async function fetchSensitivityResult(id) {
  return await httpClient.get(`/sensitivity/${id}`)
}

