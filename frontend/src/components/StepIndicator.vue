<script setup>
import { computed } from 'vue'
import { WorkflowStep } from '../services/workflowApi'

const props = defineProps({
  current: {
    type: String,
    default: WorkflowStep.PROJECT
  }
})

const steps = [
  { id: WorkflowStep.PROJECT, label: 'Project Setup' },
  { id: WorkflowStep.CONTRACT, label: 'Product Selection' },
  { id: WorkflowStep.BLUEPRINT, label: 'Preset Template' }
]

const currentIndex = computed(() => {
  const index = steps.findIndex(s => s.id === props.current)
  return index === -1 ? 0 : index
})
</script>

<template>
  <div class="space-y-4">
    <div v-for="(step, index) in steps" :key="step.id" class="flex items-center gap-3">
      <div 
        class="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold transition-colors border"
        :class="[
          index < currentIndex ? 'bg-indigo-500 border-indigo-500 text-white' : 
          index === currentIndex ? 'bg-indigo-500/20 border-indigo-500 text-indigo-400 ring-2 ring-indigo-500/30' : 
          'bg-[#0F172A] border-slate-700 text-slate-500'
        ]"
      >
        <span v-if="index < currentIndex">✓</span>
        <span v-else>{{ index + 1 }}</span>
      </div>
      <span 
        class="text-sm font-medium transition-colors"
        :class="index <= currentIndex ? 'text-slate-200' : 'text-slate-500'"
      >
        {{ step.label }}
      </span>
    </div>
  </div>
</template>
