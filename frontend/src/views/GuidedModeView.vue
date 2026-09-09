<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useValuationStore } from '../stores/useValuationStore'
import { generateGuidedTermLife } from '../services/actuaryApi'
import {
  ChevronRight,
  Shield,
  Briefcase,
  Activity,
  Calculator,
  ArrowRight,
  Loader2,
  CheckCircle2,
  AlertCircle
} from 'lucide-vue-next'

const router = useRouter()
const valuationStore = useValuationStore()

const currentStep = ref(1)
const isGenerating = ref(false)
const errorMessage = ref(null)

const form = ref({
  product_type: 'term_life',
  issue_age: 35,
  term: 20,
  sum_assured: 1000000,
  premium_freq: 'annual',
  table_id: 'soa_ilt',
  interest_rate: 0.05,
  lapse_rate: 0.03,
  expense_first_year_pct: 0.35,
  expense_renewal_pct: 0.05,
})

const steps = [
  { id: 1, title: 'Choose Product', icon: Briefcase },
  { id: 2, title: 'Policy Details', icon: Shield },
  { id: 3, title: 'Assumptions', icon: Activity },
  { id: 4, title: 'Review & Generate', icon: Calculator },
]

function nextStep() {
  if (currentStep.value < 4) currentStep.value++
}

function prevStep() {
  if (currentStep.value > 1) currentStep.value--
}

async function handleGenerate() {
  isGenerating.value = true
  errorMessage.value = null
  
  try {
    const payload = { ...form.value }
    const blueprint = await generateGuidedTermLife(payload)
    
    // Store in pinia
    const payloadData = blueprint?.data || blueprint
    valuationStore.setCustomBlueprintPayload(payloadData)
    
    // Navigate to builder
    router.push('/builder')
  } catch (error) {
    console.error('Failed to generate blueprint:', error)
    errorMessage.value = error.response?.data?.detail || error.message || 'Generation failed'
  } finally {
    isGenerating.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-900 text-slate-200 py-12 px-4 sm:px-6 lg:px-8 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-800 via-slate-900 to-black">
    <div class="max-w-4xl mx-auto">
      
      <!-- Header -->
      <div class="text-center mb-12">
        <h1 class="text-4xl md:text-5xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-sky-400 to-indigo-400 mb-4 tracking-tight">
          Guided Modeling
        </h1>
        <p class="text-lg text-slate-400 max-w-2xl mx-auto">
          Create complex actuarial blueprints without writing nodes. Just tell us about the product, and we'll generate the architecture.
        </p>
      </div>

      <!-- Stepper -->
      <nav aria-label="Progress" class="mb-12 hidden md:block">
        <ol role="list" class="flex items-center justify-between w-full">
          <li v-for="(step, idx) in steps" :key="step.id" class="relative flex-1">
            <div class="flex items-center w-full">
              <div 
                class="flex items-center justify-center w-10 h-10 rounded-full transition-all duration-300 shadow-lg shrink-0"
                :class="currentStep >= step.id ? 'bg-sky-500 text-white shadow-sky-500/30' : 'bg-slate-800 text-slate-500 border border-slate-700'"
              >
                <component :is="step.icon" class="w-5 h-5" />
              </div>
              <div v-if="idx !== steps.length - 1" class="flex-1 h-0.5 mx-4 transition-colors duration-300" :class="currentStep > step.id ? 'bg-sky-500/50' : 'bg-slate-800'"></div>
            </div>
            <div class="absolute mt-3 w-32 -ml-11 text-center">
              <span class="text-sm font-medium transition-colors duration-300" :class="currentStep >= step.id ? 'text-sky-300' : 'text-slate-500'">
                {{ step.title }}
              </span>
            </div>
          </li>
        </ol>
      </nav>

      <!-- Main Form Card -->
      <div class="bg-slate-800/40 backdrop-blur-xl border border-slate-700/50 rounded-3xl p-8 shadow-2xl relative overflow-hidden">
        
        <!-- Step 1: Product -->
        <div v-if="currentStep === 1" class="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
          <h2 class="text-2xl font-bold text-white mb-6">Select a Product</h2>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div class="relative rounded-2xl border-2 border-sky-500 bg-sky-500/10 p-6 cursor-pointer hover:bg-sky-500/20 transition-all">
              <div class="absolute top-4 right-4 text-sky-400"><CheckCircle2 class="w-6 h-6" /></div>
              <Shield class="w-10 h-10 text-sky-400 mb-4" />
              <h3 class="text-lg font-bold text-white mb-2">Term Life Insurance</h3>
              <p class="text-sm text-sky-200/70">Pure death benefit protection for a fixed period. (Currently the only guided product available).</p>
            </div>
            <div class="rounded-2xl border-2 border-slate-700/50 bg-slate-800/50 p-6 opacity-50 cursor-not-allowed">
              <Briefcase class="w-10 h-10 text-slate-500 mb-4" />
              <h3 class="text-lg font-bold text-slate-300 mb-2">Endowment</h3>
              <p class="text-sm text-slate-500">Coming soon.</p>
            </div>
          </div>
        </div>

        <!-- Step 2: Policy Details -->
        <div v-if="currentStep === 2" class="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
          <h2 class="text-2xl font-bold text-white mb-6">Policy Configuration</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="space-y-2">
              <label class="text-sm font-medium text-slate-400">Entry Age</label>
              <input v-model.number="form.issue_age" type="number" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none transition-all" />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium text-slate-400">Policy Term (Years)</label>
              <input v-model.number="form.term" type="number" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none transition-all" />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium text-slate-400">Sum Assured ($)</label>
              <input v-model.number="form.sum_assured" type="number" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none transition-all" />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium text-slate-400">Premium Frequency</label>
              <select v-model="form.premium_freq" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none transition-all">
                <option value="annual">Annual</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
          </div>
        </div>

        <!-- Step 3: Assumptions -->
        <div v-if="currentStep === 3" class="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
          <h2 class="text-2xl font-bold text-white mb-6">Actuarial Assumptions</h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="space-y-2">
              <label class="text-sm font-medium text-slate-400">Discount Rate (%)</label>
              <input v-model.number="form.interest_rate" type="number" step="0.01" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none transition-all" />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium text-slate-400">Annual Lapse Rate (%)</label>
              <input v-model.number="form.lapse_rate" type="number" step="0.01" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none transition-all" />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium text-slate-400">First Year Expense (% of Prem)</label>
              <input v-model.number="form.expense_first_year_pct" type="number" step="0.01" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none transition-all" />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium text-slate-400">Renewal Expense (% of Prem)</label>
              <input v-model.number="form.expense_renewal_pct" type="number" step="0.01" class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-white focus:ring-2 focus:ring-sky-500 focus:border-transparent outline-none transition-all" />
            </div>
          </div>
        </div>

        <!-- Step 4: Review -->
        <div v-if="currentStep === 4" class="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
          <h2 class="text-2xl font-bold text-white mb-6">Review Configuration</h2>
          <div class="bg-slate-900/50 border border-slate-700 rounded-xl p-6 mb-6">
            <dl class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-6 text-sm">
              <div><dt class="text-slate-400">Product</dt><dd class="text-white font-medium">Term Life Insurance</dd></div>
              <div><dt class="text-slate-400">Age / Term</dt><dd class="text-white font-medium">{{ form.issue_age }} / {{ form.term }} Years</dd></div>
              <div><dt class="text-slate-400">Sum Assured</dt><dd class="text-white font-medium">${{ form.sum_assured.toLocaleString() }}</dd></div>
              <div><dt class="text-slate-400">Discount Rate</dt><dd class="text-white font-medium">{{ (form.interest_rate * 100).toFixed(1) }}%</dd></div>
            </dl>
          </div>

          <div v-if="errorMessage" class="bg-rose-500/10 border border-rose-500/50 text-rose-400 px-4 py-3 rounded-lg flex items-start space-x-3 mb-6">
            <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
            <p class="text-sm">{{ errorMessage }}</p>
          </div>
        </div>

        <!-- Navigation Buttons -->
        <div class="mt-10 flex items-center justify-between border-t border-slate-700/50 pt-6">
          <button 
            @click="prevStep" 
            :disabled="currentStep === 1 || isGenerating"
            class="px-6 py-2.5 rounded-xl font-medium transition-colors"
            :class="currentStep === 1 ? 'text-slate-600 cursor-not-allowed' : 'text-slate-300 hover:bg-slate-800'"
          >
            Back
          </button>
          
          <button 
            v-if="currentStep < 4" 
            @click="nextStep"
            class="flex items-center space-x-2 bg-sky-500 hover:bg-sky-400 text-white px-6 py-2.5 rounded-xl font-medium transition-colors shadow-lg shadow-sky-500/25"
          >
            <span>Continue</span>
            <ChevronRight class="w-4 h-4" />
          </button>
          
          <button 
            v-else
            @click="handleGenerate"
            :disabled="isGenerating"
            class="flex items-center space-x-2 bg-gradient-to-r from-sky-500 to-indigo-500 hover:from-sky-400 hover:to-indigo-400 text-white px-8 py-3 rounded-xl font-bold transition-all shadow-lg shadow-indigo-500/30 disabled:opacity-70 disabled:cursor-not-allowed transform hover:scale-105 active:scale-95"
          >
            <Loader2 v-if="isGenerating" class="w-5 h-5 animate-spin" />
            <Sparkles v-else class="w-5 h-5" />
            <span>Generate Blueprint</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
