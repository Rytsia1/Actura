import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useProjectStore = defineStore('project', () => {
  const currentProject = ref(null)
  const currentContract = ref(null) // Represents the saved state of the blueprint in DB
  const valuationHistory = ref([])

  const setCurrentProject = (project) => {
    currentProject.value = project
  }

  const setCurrentContract = (contract) => {
    currentContract.value = contract
  }

  const setValuationHistory = (history) => {
    valuationHistory.value = history
  }

  const addValuationResult = (result) => {
    valuationHistory.value = [result, ...valuationHistory.value]
  }

  const clearStore = () => {
    currentProject.value = null
    currentContract.value = null
    valuationHistory.value = []
  }

  return {
    currentProject,
    currentContract,
    valuationHistory,
    setCurrentProject,
    setCurrentContract,
    setValuationHistory,
    addValuationResult,
    clearStore
  }
})
