<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { workflowApi, WorkflowStep } from '../services/workflowApi'
import { useErrorStore } from '../stores/useErrorStore'
import { useLoadingStore } from '../stores/useLoadingStore'
import StepIndicator from '../components/StepIndicator.vue'
import ProductCard from '../components/ProductCard.vue'
import LoadingOverlay from '../components/LoadingOverlay.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import { PRESET_TEMPLATES } from '../utils/presets'
import { ChevronLeft } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const errorStore = useErrorStore()
const loadingStore = useLoadingStore()

const projectId = route.params.projectId
const state = ref(null)

const projectName = ref('')
const selectedProductType = ref(null)
const selectedPresetId = ref('term_life_20y')

const loadState = async () => {
  if (!projectId) {
    state.value = { step: WorkflowStep.PROJECT }
    return
  }
  try {
    const response = await workflowApi.getState(projectId)
    state.value = response.data || response
    
    // If state is beyond Blueprint (because of old backend data), reset to Blueprint
    if ([WorkflowStep.ASSUMPTIONS, WorkflowStep.VALIDATION, WorkflowStep.RUNNING, WorkflowStep.RESULTS].includes(state.value.step)) {
       state.value.step = WorkflowStep.BLUEPRINT
    }
  } catch (err) {
    errorStore.setError({ code: 'LOAD_ERROR', message: 'Failed to load workflow state' })
  }
}

onMounted(() => {
  loadState()
})

const goBack = () => {
  if (state.value.step === WorkflowStep.CONTRACT) {
    state.value.step = WorkflowStep.PROJECT
  } else if (state.value.step === WorkflowStep.BLUEPRINT) {
    state.value.step = WorkflowStep.CONTRACT
  }
}

const selectPreset = (key) => {
  selectedPresetId.value = key
}

const handleAction = async (action, data = null) => {
  errorStore.clearError()
  try {
    if (action === 'create_project') {
      loadingStore.startLoading()
      const response = await workflowApi.start(projectName.value, "Valuation Project")
      const newState = response.data || response
      router.replace(`/wizard/${newState.project_id}`)
      state.value = newState
    } 
    else if (action === 'select_product') {
      selectedProductType.value = data
      // Pre-select preset based on product type
      if (data === 'Term') selectedPresetId.value = 'term_life_20y'
      else if (data === 'WholeLife') selectedPresetId.value = 'endowment_15y'
      else if (data === 'Annuity') selectedPresetId.value = 'unit_linked_10y'
      
      state.value.step = WorkflowStep.BLUEPRINT
    } 
    else if (action === 'launch_builder') {
      loadingStore.startLoading()
      const preset = PRESET_TEMPLATES[selectedPresetId.value]
      
      // Save contract with preset nodes and edges
      await workflowApi.addContract(projectId, `${preset.name} Contract`, selectedProductType.value || 'Term', {
         nodes: preset.nodes,
         edges: preset.edges
      })
      
      // Navigate to Visual Blueprint Builder
      router.push(`/projects/${projectId}`)
    }
  } catch (err) {
    console.error(err)
  } finally {
    loadingStore.stopLoading()
  }
}
</script>

<template>
  <div class="h-screen w-full bg-[#0B0F19] text-slate-200 flex flex-col font-sans">
    <ErrorBanner />
    
    <header class="h-16 shrink-0 border-b border-white/[0.08] bg-[#0F172A] flex items-center px-6 justify-between">
      <div class="flex items-center gap-3 cursor-pointer" @click="router.push('/')">
        <div class="h-10 w-10 rounded-xl flex-shrink-0 shadow-md border border-white/[0.05] relative overflow-hidden bg-[#070b14]">
          <img src="/logo.jpg" alt="Actura Mascot" class="absolute w-[220%] h-[220%] max-w-none -bottom-[15%] -right-[20%]" />
        </div>
        <div class="min-w-0 flex-1">
          <h1 class="text-sm font-semibold text-white tracking-tight">Actura</h1>
          <p class="text-xs text-slate-500 font-medium truncate">Actuarial Valuation & Risk Platform</p>
        </div>
      </div>
      <div>
        <button @click="router.push('/')" class="btn-secondary text-sm px-4 py-2 flex items-center gap-2 border-slate-600 hover:border-slate-400">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-log-out"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/></svg>
          Exit to Dashboard
        </button>
      </div>
    </header>

    <div class="flex-1 flex overflow-hidden">
      <!-- Sidebar -->
      <aside class="w-64 border-r border-white/[0.06] bg-[#0F172A] p-6 hidden md:block">
        <h3 class="text-sm font-semibold text-white mb-6 uppercase tracking-wider">Workflow Step</h3>
        <StepIndicator :current="state?.step" />
      </aside>

      <!-- Main Content -->
      <main class="flex-1 p-8 overflow-y-auto relative flex justify-center">
        <LoadingOverlay v-if="loadingStore.isLoading" />
        
        <div v-if="!state" class="flex items-center justify-center h-full">
          <div class="animate-pulse flex flex-col items-center">
            <div class="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin mb-4"></div>
            <p class="text-slate-400">Loading workflow state...</p>
          </div>
        </div>

        <div v-else class="w-full max-w-3xl pt-8 relative">
          
          <!-- Shared Back Button -->
          <button 
             v-if="state.step === WorkflowStep.CONTRACT || state.step === WorkflowStep.BLUEPRINT"
             @click="goBack"
             class="absolute top-0 left-0 -mt-2 flex items-center text-sm font-medium text-slate-400 hover:text-white transition-colors"
          >
            <ChevronLeft class="w-4 h-4 mr-1" />
            Back to previous step
          </button>

          <!-- Step 1: Project -->
          <div v-if="state.step === WorkflowStep.PROJECT" class="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500 mt-8">
            <div>
              <h2 class="text-3xl font-bold text-white mb-2">Create Project</h2>
              <p class="text-slate-400 text-lg">Name your actuarial project to get started.</p>
            </div>
            <div class="card p-6 space-y-4">
              <div>
                <label class="block text-sm font-medium text-slate-300 mb-1.5">Project Name</label>
                <input v-model="projectName" type="text" class="input-field w-full" placeholder="e.g. Q3 Term Life Valuation" />
              </div>
              <button @click="handleAction('create_project')" :disabled="!projectName" class="btn-primary w-full py-2.5">
                Start Project
              </button>
            </div>
          </div>

          <!-- Step 2: Contract (Product Selection) -->
          <div v-else-if="state.step === WorkflowStep.CONTRACT" class="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500 mt-8">
            <div>
              <h2 class="text-3xl font-bold text-white mb-2">Select Product Category</h2>
              <p class="text-slate-400 text-lg">Choose the base product family for this valuation.</p>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <ProductCard type="WholeLife" title="Whole Life" description="Permanent life insurance with fixed premiums and guaranteed death benefit." @select="(type) => handleAction('select_product', type)" />
              <ProductCard type="Term" title="Term Life" description="Temporary coverage for a specified term (e.g. 10, 20, 30 years)." @select="(type) => handleAction('select_product', type)" />
              <ProductCard type="Annuity" title="Annuity" description="A stream of income payments for life or a specified period." @select="(type) => handleAction('select_product', type)" />
            </div>
          </div>

          <!-- Step 3: Blueprint (Preset Selection) -->
          <div v-else-if="state.step === WorkflowStep.BLUEPRINT" class="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500 mt-8">
            <div>
              <h2 class="text-3xl font-bold text-white mb-2">Select Template</h2>
              <p class="text-slate-400 text-lg">Pick a starter cash flow topology to launch into the Visual Builder.</p>
            </div>
            
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div 
                 v-for="(preset, key) in PRESET_TEMPLATES" 
                 :key="key"
                 @click="selectPreset(key)"
                 :class="[
                   'rounded-xl p-5 cursor-pointer border-2 transition-all duration-200',
                   selectedPresetId === key ? 'border-indigo-500 bg-indigo-500/10' : 'bg-slate-800 border-white/[0.06] hover:border-slate-500'
                 ]"
              >
                <div class="flex justify-between items-start mb-2">
                  <h3 class="text-lg font-bold text-white">{{ preset.name }}</h3>
                  <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-white/5 text-slate-400">{{ preset.badge }}</span>
                </div>
                <p class="text-sm text-slate-400 leading-relaxed line-clamp-2">
                  {{ preset.description }}
                </p>
                <div class="mt-4 flex -space-x-2">
                   <!-- Visual cue of nodes in preset -->
                   <div v-for="i in Math.min(preset.nodes.length, 5)" :key="i" class="w-6 h-6 rounded bg-slate-800 border border-slate-700 flex items-center justify-center text-[8px] text-slate-500 shadow-sm z-[calc(5-i)]"></div>
                   <div v-if="preset.nodes.length > 5" class="w-6 h-6 rounded bg-slate-800/50 border border-slate-700 flex items-center justify-center text-[10px] text-slate-500 z-0">+</div>
                </div>
              </div>
            </div>
            
            <div class="pt-6 border-t border-slate-700/50 flex justify-end">
              <button @click="handleAction('launch_builder')" class="btn-primary px-8 py-2.5 text-base flex items-center shadow-lg shadow-indigo-500/25">
                Launch Visual Builder
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="ml-2 lucide lucide-arrow-right"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
              </button>
            </div>
          </div>

        </div>
      </main>
    </div>
  </div>
</template>
