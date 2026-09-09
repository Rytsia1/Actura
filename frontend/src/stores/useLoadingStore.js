import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useLoadingStore = defineStore('loading', () => {
  const steps = ref([])
  const isRunning = ref(false)

  const startLoading = (initialSteps = []) => {
    isRunning.value = true
    steps.value = initialSteps.length ? initialSteps : [
      { id: 'prepare', label: 'Preparing valuation...', status: 'pending' },
      { id: 'projection', label: 'Running projection...', status: 'pending' },
      { id: 'stochastic', label: 'Running stochastic simulation...', status: 'pending' },
      { id: 'risk', label: 'Calculating risk metrics...', status: 'pending' },
      { id: 'finalize', label: 'Finalizing result...', status: 'pending' }
    ]
  }

  const updateStep = (id, status) => {
    const step = steps.value.find(s => s.id === id)
    if (step) {
      step.status = status
    }
  }

  const stopLoading = () => {
    isRunning.value = false
  }

  return { steps, isRunning, startLoading, updateStep, stopLoading }
})
