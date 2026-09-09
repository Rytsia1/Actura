<template>
  <div v-if="error" class="error-banner" role="alert">
    <div class="error-header">
      <span class="error-icon">
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-triangle-alert"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
      </span>
      <strong>Valuation Failed</strong>
      <button @click="clearError" class="error-close" aria-label="Close error">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-x"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
      </button>
    </div>
    <div class="error-body">
      <p class="error-reason"><strong>Reason:</strong> {{ error.message }}</p>
      <pre v-if="error.details" class="error-details">{{ formattedDetails }}</pre>
    </div>
    <div class="error-actions">
      <button @click="handleAction" class="error-action-btn primary">
        {{ actionLabel }}
      </button>
      <button @click="clearError" class="error-action-btn secondary">
        Dismiss
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useErrorStore } from '../stores/useErrorStore'

const errorStore = useErrorStore()
const { error } = storeToRefs(errorStore)
const { clearError } = errorStore

const formattedDetails = computed(() => {
  if (!error.value?.details) return ''
  return JSON.stringify(error.value.details, null, 2)
})

const actionLabel = computed(() => {
  const code = error.value?.code
  switch (code) {
    case 'INVALID_BLUEPRINT': return 'Fix Blueprint'
    case 'MORTALITY_TABLE_MISSING': return 'Upload Table'
    case 'CYCLE_DETECTED': return 'Remove Cycle'
    case 'DISCONNECTED_NODE': return 'Connect Nodes'
    default: return 'Try Again'
  }
})

const handleAction = () => {
  // Clear the error and allow the user to continue working
  clearError()
}
</script>

<style scoped>
.error-banner {
  background-color: #fef2f2;
  border-left: 4px solid #ef4444;
  border-radius: 6px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
  margin-bottom: 1rem;
  overflow: hidden;
  position: relative;
  z-index: 50;
  max-width: 600px;
  margin: 1rem auto;
}

.error-header {
  display: flex;
  align-items: center;
  padding: 0.75rem 1rem;
  background-color: #fee2e2;
  color: #991b1b;
  font-weight: 600;
}

.error-icon {
  margin-right: 0.5rem;
  display: flex;
}

.error-close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: #991b1b;
  cursor: pointer;
  padding: 0.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.error-close:hover {
  background-color: #fca5a5;
}

.error-body {
  padding: 1rem;
  color: #7f1d1d;
  font-size: 0.875rem;
}

.error-reason {
  margin: 0 0 0.5rem 0;
}

.error-details {
  background-color: #f871711a;
  padding: 0.5rem;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 0.75rem;
  color: #991b1b;
  margin: 0;
  border: 1px solid #fca5a5;
}

.error-actions {
  display: flex;
  gap: 0.5rem;
  padding: 0 1rem 1rem 1rem;
}

.error-action-btn {
  padding: 0.375rem 0.75rem;
  border-radius: 4px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}

.error-action-btn.primary {
  background-color: #ef4444;
  color: white;
}

.error-action-btn.primary:hover {
  background-color: #dc2626;
}

.error-action-btn.secondary {
  background-color: transparent;
  color: #991b1b;
  border: 1px solid #fca5a5;
}

.error-action-btn.secondary:hover {
  background-color: #fee2e2;
}
</style>
