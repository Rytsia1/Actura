import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useErrorStore = defineStore('error', () => {
  const error = ref(null)

  const setError = (err) => {
    error.value = {
      code: err.code || 'UNKNOWN_ERROR',
      message: err.message || 'An unexpected error occurred.',
      details: err.details || null,
      timestamp: err.timestamp || new Date().toISOString()
    }
  }

  const clearError = () => {
    error.value = null
  }

  return { error, setError, clearError }
})
