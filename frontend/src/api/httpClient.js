import axios from 'axios'

/**
 * Custom Actuarial API Error with structured status, clean user message, and payload details.
 */
export class ActuaryApiError extends Error {
  constructor(message, status = 500, details = null) {
    super(message)
    this.name = 'ActuaryApiError'
    this.status = status
    this.details = details
  }
}

/**
 * Global Axios HTTP client configured for the Actuarial Engine FastAPI backend.
 */
const httpClient = axios.create({
  baseURL: '/api/v1',
  timeout: 45000, // 45 seconds for heavy stochastic simulations & batch runs
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
})

// ────────────────────────────────────────────────────────────
// Request Interceptor
// ────────────────────────────────────────────────────────────
httpClient.interceptors.request.use(
  (config) => {
    // If payload is FormData, let the browser set multipart boundary
    if (config.data instanceof FormData) {
      delete config.headers['Content-Type']
    }
    
    // Inject JWT Authorization Token
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    
    return config
  },
  (error) => {
    return Promise.reject(new ActuaryApiError('Failed to dispatch request: ' + error.message, 0))
  }
)

// ────────────────────────────────────────────────────────────
// Response Interceptor (Global 422, 500 & Network Error Handling)
// ────────────────────────────────────────────────────────────
httpClient.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    // 0. Request Cancellation / Aborted by User
    if (axios.isCancel(error) || error.name === 'CanceledError' || error.code === 'ERR_CANCELED') {
      return Promise.reject(error)
    }

    // 1. Timeout / Network Abort
    if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
      const timeoutErr = new ActuaryApiError(
        'Request timed out. The actuarial computation took longer than 45 seconds.',
        408
      )
      return Promise.reject(timeoutErr)
    }

    // 2. Server responded with an HTTP error code
    if (error.response) {
      const status = error.response.status
      const data = error.response.data

      let formattedMessage = 'An unexpected server error occurred.'

      // FastAPI 401 Unauthorized (Auth Failed)
      if (status === 401) {
        localStorage.removeItem('token')
        localStorage.removeItem('user')
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
        return Promise.reject(new ActuaryApiError('Authentication required. Please log in.', 401))
      }

      // FastAPI 422 Unprocessable Entity (Schema Validation Error)
      if (status === 422 && data && Array.isArray(data.detail)) {
        const errorDetails = data.detail
          .map((item) => {
            const loc = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : 'field'
            return `${loc}: ${item.msg}`
          })
          .join('; ')
        formattedMessage = `Validation Error (422): ${errorDetails}`
        return Promise.reject(new ActuaryApiError(formattedMessage, status, data.detail))
      }

      // FastAPI 500 Internal Server Error
      if (status === 500) {
        const detailMsg = typeof data?.detail === 'string' ? data.detail : 'Internal calculation engine error.'
        formattedMessage = `Backend Engine Error (500): ${detailMsg}`
        return Promise.reject(new ActuaryApiError(formattedMessage, status, data))
      }

      // FastAPI 400 Bad Request / 404 Not Found
      if (typeof data?.detail === 'string') {
        formattedMessage = data.detail
      } else if (typeof data?.message === 'string') {
        formattedMessage = data.message
      } else {
        formattedMessage = `HTTP ${status}: ${error.response.statusText || 'Error processing request'}`
      }

      return Promise.reject(new ActuaryApiError(formattedMessage, status, data))
    }

    // 3. No response received (Connection Refused / Server Offline)
    if (error.request) {
      const offlineErr = new ActuaryApiError(
        'Unable to connect to the Actuary API backend (http://127.0.0.1:8000). Please ensure the FastAPI server is running.',
        0
      )
      return Promise.reject(offlineErr)
    }

    return Promise.reject(new ActuaryApiError(error.message || 'Unknown request error', 500))
  }
)

export default httpClient
