<template>
  <div v-if="isRunning" class="loading-overlay">
    <div class="loading-card">
      <div class="loading-spinner"></div>
      <h3 class="loading-title">Calculating Valuation...</h3>
      <div class="loading-steps">
        <div 
          v-for="step in steps" 
          :key="step.id" 
          :class="['step', step.status]"
        >
          <span class="step-icon">
            <!-- Complete -->
            <svg v-if="step.status === 'complete'" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-check-circle-2 text-green-500"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
            <!-- Active -->
            <svg v-else-if="step.status === 'active'" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-2 text-blue-500 animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
            <!-- Error -->
            <svg v-else-if="step.status === 'error'" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-x-circle text-red-500"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg>
            <!-- Pending -->
            <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-circle text-gray-300"><circle cx="12" cy="12" r="10"/></svg>
          </span>
          <span class="step-label">{{ step.label }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { storeToRefs } from 'pinia'
import { useLoadingStore } from '../stores/useLoadingStore'

const loadingStore = useLoadingStore()
const { steps, isRunning } = storeToRefs(loadingStore)
</script>

<style scoped>
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.loading-card {
  background-color: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  width: 100%;
  max-width: 400px;
  text-align: center;
  border: 1px solid #e5e7eb;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #e5e7eb;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1rem auto;
}

.loading-title {
  margin: 0 0 1.5rem 0;
  color: #1f2937;
  font-size: 1.25rem;
  font-weight: 600;
}

.loading-steps {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  text-align: left;
}

.step {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.875rem;
  color: #6b7280;
  transition: all 0.3s ease;
}

.step.active {
  color: #1f2937;
  font-weight: 500;
}

.step.complete {
  color: #10b981;
}

.step.error {
  color: #ef4444;
}

.step-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.text-blue-500 { color: #3b82f6; }
.text-green-500 { color: #10b981; }
.text-red-500 { color: #ef4444; }
.text-gray-300 { color: #d1d5db; }

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.animate-spin {
  animation: spin 1.5s linear infinite;
}
</style>
