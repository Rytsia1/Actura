<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  fetchBaseModels,
  fetchScenarios,
  createScenario,
  updateScenario,
  duplicateScenario,
  validateScenario,
  runScenario,
  deleteScenario,
} from '../services/actuaryApi'
import {
  Layers,
  Plus,
  Play,
  Copy,
  Edit2,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  TrendingUp,
  TrendingDown,
  ShieldCheck,
  RefreshCw,
  Search,
  Filter,
  ArrowLeft,
  DollarSign,
  Activity,
  Sliders,
  FileText,
  ChevronDown,
  ChevronUp,
} from 'lucide-vue-next'

const router = useRouter()

// Data State
const baseModels = ref([])
const scenarios = ref([])
const selectedModelId = ref('default-endowment')
const loading = ref(false)
const error = ref(null)
const successMessage = ref(null)

// Filter & Search State
const searchQuery = ref('')
const statusFilter = ref('ALL')

// Execution Results State
const runningScenarioId = ref(null)
const executionResults = ref({}) // map scenario_id -> result
const activeResultTab = ref('summary') // 'summary' | 'cashflows' | 'reserves'
const selectedResultScenario = ref(null)

// Validation Feedback State
const validationResults = ref({}) // map scenario_id -> { is_valid, errors, warnings, effective_assumptions }
const showValidationModal = ref(false)
const activeValidation = ref(null)

// Modal State (Create / Edit Scenario)
const showModal = ref(false)
const modalMode = ref('create') // 'create' | 'edit'
const editingScenarioId = ref(null)
const scenarioForm = ref({
  name: '',
  description: '',
  base_model_id: 'default-endowment',
  status: 'ACTIVE',
  interest_rate_bps: null,
  interest_rate_delta: null,
  interest_rate_override: null,
  mortality_multiplier: 1.0,
  mortality_table_id: '',
  lapse_multiplier: 1.0,
  lapse_rate_delta: null,
  lapse_override: null,
  expense_multiplier: 1.0,
  expense_inflation_pct: null,
})

// Active Base Model Computed
const currentBaseModel = computed(() => {
  return baseModels.value.find((m) => m.id === selectedModelId.value) || baseModels.value[0] || null
})

// Filtered Scenarios Computed
const filteredScenarios = computed(() => {
  return scenarios.value.filter((sc) => {
    const matchesModel = !selectedModelId.value || sc.base_model_id === selectedModelId.value
    const matchesStatus = statusFilter.value === 'ALL' || sc.status === statusFilter.value
    const matchesSearch =
      !searchQuery.value ||
      sc.name.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
      (sc.description && sc.description.toLowerCase().includes(searchQuery.value.toLowerCase()))
    return matchesModel && matchesStatus && matchesSearch
  })
})

// Live Preview of Effective Assumptions in Modal
const modalEffectivePreview = computed(() => {
  if (!currentBaseModel.value) return null
  const base = currentBaseModel.value

  // Interest
  let effInterest = base.interest_rate
  if (scenarioForm.value.interest_rate_override !== null && scenarioForm.value.interest_rate_override !== '') {
    effInterest = parseFloat(scenarioForm.value.interest_rate_override)
  } else if (scenarioForm.value.interest_rate_bps !== null && scenarioForm.value.interest_rate_bps !== '') {
    effInterest = base.interest_rate + parseFloat(scenarioForm.value.interest_rate_bps) / 10000.0
  } else if (scenarioForm.value.interest_rate_delta !== null && scenarioForm.value.interest_rate_delta !== '') {
    effInterest = base.interest_rate + parseFloat(scenarioForm.value.interest_rate_delta)
  }

  // Mortality
  const effMort = scenarioForm.value.mortality_multiplier ? parseFloat(scenarioForm.value.mortality_multiplier) : 1.0
  const effTable = scenarioForm.value.mortality_table_id || base.table_id

  // Lapse
  const baseLapseRate = base.lapse?.flat_annual_rate || 0.03
  let effLapse = baseLapseRate
  if (scenarioForm.value.lapse_override !== null && scenarioForm.value.lapse_override !== '') {
    effLapse = parseFloat(scenarioForm.value.lapse_override)
  } else {
    const lDelta = scenarioForm.value.lapse_rate_delta ? parseFloat(scenarioForm.value.lapse_rate_delta) : 0.0
    const lMult = scenarioForm.value.lapse_multiplier ? parseFloat(scenarioForm.value.lapse_multiplier) : 1.0
    effLapse = (baseLapseRate + lDelta) * lMult
  }

  // Expense
  let effExp = scenarioForm.value.expense_multiplier ? parseFloat(scenarioForm.value.expense_multiplier) : 1.0
  if (scenarioForm.value.expense_inflation_pct) {
    effExp *= 1.0 + parseFloat(scenarioForm.value.expense_inflation_pct) / 100.0
  }

  return {
    interest_rate: effInterest,
    mortality_multiplier: effMort,
    table_id: effTable,
    lapse_rate: effLapse,
    expense_multiplier: effExp,
  }
})

// Data Loading
async function loadData() {
  loading.value = true
  error.value = null
  try {
    const [modelsRes, scenRes] = await Promise.all([fetchBaseModels(), fetchScenarios()])
    baseModels.value = modelsRes.data || []
    scenarios.value = scenRes.data || []

    if (baseModels.value.length > 0 && !baseModels.value.some((m) => m.id === selectedModelId.value)) {
      selectedModelId.value = baseModels.value[0].id
    }
  } catch (err) {
    console.error('Failed to load scenarios or models:', err)
    error.value = 'Failed to load scenario data from engine.'
  } finally {
    loading.value = false
  }
}

// Modal Handlers
function openCreateModal() {
  modalMode.value = 'create'
  editingScenarioId.value = null
  scenarioForm.value = {
    name: '',
    description: '',
    base_model_id: selectedModelId.value || 'default-endowment',
    status: 'ACTIVE',
    interest_rate_bps: null,
    interest_rate_delta: null,
    interest_rate_override: null,
    mortality_multiplier: 1.0,
    mortality_table_id: '',
    lapse_multiplier: 1.0,
    lapse_rate_delta: null,
    lapse_override: null,
    expense_multiplier: 1.0,
    expense_inflation_pct: null,
  }
  showModal.value = true
}

function openEditModal(scenario) {
  modalMode.value = 'edit'
  editingScenarioId.value = scenario.id
  const ov = scenario.overrides || {}
  scenarioForm.value = {
    name: scenario.name,
    description: scenario.description || '',
    base_model_id: scenario.base_model_id,
    status: scenario.status || 'ACTIVE',
    interest_rate_bps: ov.interest_rate_bps ?? null,
    interest_rate_delta: ov.interest_rate_delta ?? null,
    interest_rate_override: ov.interest_rate_override ?? null,
    mortality_multiplier: ov.mortality_multiplier ?? 1.0,
    mortality_table_id: ov.mortality_table_id ?? '',
    lapse_multiplier: ov.lapse_multiplier ?? 1.0,
    lapse_rate_delta: ov.lapse_rate_delta ?? null,
    lapse_override: ov.lapse_override ?? null,
    expense_multiplier: ov.expense_multiplier ?? 1.0,
    expense_inflation_pct: ov.expense_inflation_pct ?? null,
  }
  showModal.value = true
}

async function saveScenario() {
  if (!scenarioForm.value.name.trim()) {
    alert('Please provide a scenario name.')
    return
  }

  // Construct overrides payload
  const overrides = {}
  const f = scenarioForm.value

  if (f.interest_rate_override !== null && f.interest_rate_override !== '') {
    overrides.interest_rate_override = parseFloat(f.interest_rate_override)
  } else if (f.interest_rate_bps !== null && f.interest_rate_bps !== '') {
    overrides.interest_rate_bps = parseFloat(f.interest_rate_bps)
  } else if (f.interest_rate_delta !== null && f.interest_rate_delta !== '') {
    overrides.interest_rate_delta = parseFloat(f.interest_rate_delta)
  }

  if (f.mortality_multiplier !== null && f.mortality_multiplier !== '' && parseFloat(f.mortality_multiplier) !== 1.0) {
    overrides.mortality_multiplier = parseFloat(f.mortality_multiplier)
  }
  if (f.mortality_table_id && f.mortality_table_id.trim()) {
    overrides.mortality_table_id = f.mortality_table_id.trim()
  }

  if (f.lapse_override !== null && f.lapse_override !== '') {
    overrides.lapse_override = parseFloat(f.lapse_override)
  } else {
    if (f.lapse_multiplier !== null && f.lapse_multiplier !== '' && parseFloat(f.lapse_multiplier) !== 1.0) {
      overrides.lapse_multiplier = parseFloat(f.lapse_multiplier)
    }
    if (f.lapse_rate_delta !== null && f.lapse_rate_delta !== '') {
      overrides.lapse_rate_delta = parseFloat(f.lapse_rate_delta)
    }
  }

  if (f.expense_multiplier !== null && f.expense_multiplier !== '' && parseFloat(f.expense_multiplier) !== 1.0) {
    overrides.expense_multiplier = parseFloat(f.expense_multiplier)
  }
  if (f.expense_inflation_pct !== null && f.expense_inflation_pct !== '') {
    overrides.expense_inflation_pct = parseFloat(f.expense_inflation_pct)
  }

  const payload = {
    name: f.name.trim(),
    description: f.description.trim(),
    base_model_id: f.base_model_id,
    overrides,
    status: f.status,
  }

  loading.value = true
  try {
    if (modalMode.value === 'create') {
      await createScenario(payload)
      showNotification('Scenario created successfully')
    } else {
      await updateScenario(editingScenarioId.value, payload)
      showNotification('Scenario updated successfully')
    }
    showModal.value = false
    await loadData()
  } catch (err) {
    console.error('Save scenario error:', err)
    alert('Failed to save scenario: ' + (err.response?.data?.detail || err.message))
  } finally {
    loading.value = false
  }
}

// Scenario Actions
async function handleDuplicate(scen) {
  loading.value = true
  try {
    const res = await duplicateScenario(scen.id)
    showNotification(`Duplicated scenario as "${res.data.name}"`)
    await loadData()
  } catch (err) {
    console.error('Duplicate scenario error:', err)
    alert('Failed to duplicate scenario: ' + (err.response?.data?.detail || err.message))
  } finally {
    loading.value = false
  }
}

async function handleDelete(scen) {
  if (!confirm(`Are you sure you want to delete scenario "${scen.name}"?`)) return
  loading.value = true
  try {
    await deleteScenario(scen.id)
    showNotification(`Deleted scenario "${scen.name}"`)
    delete executionResults.value[scen.id]
    if (selectedResultScenario.value?.id === scen.id) {
      selectedResultScenario.value = null
    }
    await loadData()
  } catch (err) {
    console.error('Delete scenario error:', err)
    alert('Failed to delete scenario: ' + (err.response?.data?.detail || err.message))
  } finally {
    loading.value = false
  }
}

async function handleValidate(scen) {
  try {
    const res = await validateScenario(scen.id)
    validationResults.value[scen.id] = res.data
    activeValidation.value = {
      scenario: scen,
      result: res.data,
    }
    showValidationModal.value = true
  } catch (err) {
    console.error('Validation error:', err)
    alert('Validation error: ' + (err.response?.data?.detail || err.message))
  }
}

async function handleRun(scen) {
  runningScenarioId.value = scen.id
  error.value = null
  try {
    const res = await runScenario(scen.id)
    executionResults.value[scen.id] = res.data
    selectedResultScenario.value = scen
    showNotification(`Executed valuation for "${scen.name}"! BEL: ${formatCurrency(res.data.bel)}`)
  } catch (err) {
    console.error('Scenario run error:', err)
    alert('Scenario valuation failed: ' + (err.response?.data?.detail || err.message))
  } finally {
    runningScenarioId.value = null
  }
}

async function handleRunAll() {
  const currentScens = filteredScenarios.value
  if (currentScens.length === 0) return
  for (const sc of currentScens) {
    await handleRun(sc)
  }
}

function showNotification(msg) {
  successMessage.value = msg
  setTimeout(() => {
    successMessage.value = null
  }, 4000)
}

function formatCurrency(val) {
  if (val === undefined || val === null || isNaN(val)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(val)
}

function formatPercent(val) {
  if (val === undefined || val === null || isNaN(val)) return '—'
  return `${(val * 100).toFixed(2)}%`
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="min-h-screen bg-[#0B0F19] text-slate-100 font-sans p-6 lg:p-8">
    <!-- Header Navigation & Title -->
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/[0.08] pb-6 mb-6">
      <div class="flex items-center space-x-4">
        <button
          @click="router.push('/')"
          class="p-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 hover:text-white transition-colors border border-white/[0.06]"
          title="Back to Dashboard"
        >
          <ArrowLeft class="w-5 h-5" />
        </button>
        <div>
          <div class="flex items-center space-x-2">
            <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <Layers class="w-7 h-7 text-sky-400" />
              Scenario Workbench
            </h1>
            <span class="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
              Task 09
            </span>
          </div>
          <p class="text-xs text-slate-400 mt-1">
            Define, validate, and execute assumption overrides against reusable base models with strict immutability.
          </p>
        </div>
      </div>

      <div class="flex items-center space-x-3">
        <button
          @click="loadData"
          :disabled="loading"
          class="px-3.5 py-2 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 border border-white/[0.08] text-slate-200 flex items-center space-x-1.5 transition-colors"
        >
          <RefreshCw :class="['w-3.5 h-3.5', loading ? 'animate-spin' : '']" />
          <span>Refresh</span>
        </button>

        <button
          @click="handleRunAll"
          :disabled="loading || filteredScenarios.length === 0"
          class="px-3.5 py-2 text-xs font-medium rounded-lg bg-emerald-600/90 hover:bg-emerald-500 text-white flex items-center space-x-1.5 transition-colors shadow-sm"
        >
          <Play class="w-3.5 h-3.5 fill-current" />
          <span>Run All ({{ filteredScenarios.length }})</span>
        </button>

        <button
          @click="openCreateModal"
          class="px-4 py-2 text-xs font-semibold rounded-lg bg-sky-500 hover:bg-sky-400 text-white flex items-center space-x-1.5 transition-colors shadow-lg shadow-sky-500/20"
        >
          <Plus class="w-4 h-4" />
          <span>New Scenario</span>
        </button>
      </div>
    </div>

    <!-- Alert / Toast Banner -->
    <div v-if="successMessage" class="mb-6 p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs flex items-center space-x-2">
      <CheckCircle2 class="w-4 h-4 flex-shrink-0" />
      <span>{{ successMessage }}</span>
    </div>
    <div v-if="error" class="mb-6 p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center space-x-2">
      <XCircle class="w-4 h-4 flex-shrink-0" />
      <span>{{ error }}</span>
    </div>

    <!-- Top Grid: Base Model Card + Filter Bar -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
      <!-- Base Model Selector & Specs Card -->
      <div class="lg:col-span-1 bg-slate-900/60 backdrop-blur border border-white/[0.08] rounded-2xl p-5 shadow-xl">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
            <FileText class="w-3.5 h-3.5 text-sky-400" />
            Base Model Reference
          </span>
          <span class="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono">
            IMMUTABLE
          </span>
        </div>

        <!-- Model Selection Dropdown -->
        <select
          v-model="selectedModelId"
          class="w-full mb-4 px-3 py-2 bg-slate-800/90 border border-white/[0.1] rounded-lg text-xs text-white focus:outline-none focus:border-sky-500"
        >
          <option v-for="m in baseModels" :key="m.id" :value="m.id">
            {{ m.name }} ({{ m.product_type }})
          </option>
        </select>

        <!-- Model Parameters Summary -->
        <div v-if="currentBaseModel" class="space-y-2 text-xs">
          <div class="flex justify-between py-1 border-b border-white/[0.04]">
            <span class="text-slate-400">Product Type</span>
            <span class="font-medium text-white capitalize">{{ currentBaseModel.product_type }}</span>
          </div>
          <div class="flex justify-between py-1 border-b border-white/[0.04]">
            <span class="text-slate-400">Issue Age / Term</span>
            <span class="font-medium text-white">{{ currentBaseModel.issue_age }} yrs / {{ currentBaseModel.term || '—' }} yrs</span>
          </div>
          <div class="flex justify-between py-1 border-b border-white/[0.04]">
            <span class="text-slate-400">Sum Assured</span>
            <span class="font-medium text-white">{{ formatCurrency(currentBaseModel.sum_assured) }}</span>
          </div>
          <div class="flex justify-between py-1 border-b border-white/[0.04]">
            <span class="text-slate-400">Base Discount Rate</span>
            <span class="font-medium text-emerald-400">{{ formatPercent(currentBaseModel.interest_rate) }}</span>
          </div>
          <div class="flex justify-between py-1 border-b border-white/[0.04]">
            <span class="text-slate-400">Mortality Table</span>
            <span class="font-mono text-sky-300">{{ currentBaseModel.table_id }}</span>
          </div>
          <div class="flex justify-between py-1">
            <span class="text-slate-400">Base Lapse Rate</span>
            <span class="font-medium text-white">{{ formatPercent(currentBaseModel.lapse?.flat_annual_rate || 0.03) }}</span>
          </div>
        </div>
      </div>

      <!-- Controls & Overview KPI -->
      <div class="lg:col-span-2 flex flex-col justify-between bg-slate-900/40 border border-white/[0.06] rounded-2xl p-5">
        <div>
          <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
            <div class="flex items-center space-x-2 w-full sm:w-auto flex-1 max-w-sm">
              <div class="relative w-full">
                <Search class="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                <input
                  v-model="searchQuery"
                  type="text"
                  placeholder="Filter scenarios by name..."
                  class="w-full pl-8 pr-3 py-1.5 bg-slate-800/80 border border-white/[0.08] rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                />
              </div>
            </div>

            <!-- Status Tabs -->
            <div class="flex items-center space-x-1 bg-slate-800/70 p-1 rounded-lg border border-white/[0.06] text-xs">
              <button
                v-for="st in ['ALL', 'ACTIVE', 'DRAFT']"
                :key="st"
                @click="statusFilter = st"
                :class="[
                  'px-3 py-1 rounded-md transition-colors text-[11px] font-medium',
                  statusFilter === st ? 'bg-sky-500 text-white shadow-sm' : 'text-slate-400 hover:text-white',
                ]"
              >
                {{ st }}
              </button>
            </div>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
            <div class="bg-slate-800/40 rounded-xl p-3 border border-white/[0.04]">
              <div class="text-[10px] uppercase text-slate-400 font-semibold tracking-wider">Total Scenarios</div>
              <div class="text-xl font-bold text-white mt-1">{{ scenarios.length }}</div>
            </div>
            <div class="bg-slate-800/40 rounded-xl p-3 border border-white/[0.04]">
              <div class="text-[10px] uppercase text-slate-400 font-semibold tracking-wider">Active Base Model</div>
              <div class="text-xl font-bold text-sky-400 mt-1">{{ filteredScenarios.length }}</div>
            </div>
            <div class="bg-slate-800/40 rounded-xl p-3 border border-white/[0.04]">
              <div class="text-[10px] uppercase text-slate-400 font-semibold tracking-wider">Executed Runs</div>
              <div class="text-xl font-bold text-emerald-400 mt-1">{{ Object.keys(executionResults).length }}</div>
            </div>
            <div class="bg-slate-800/40 rounded-xl p-3 border border-white/[0.04]">
              <div class="text-[10px] uppercase text-slate-400 font-semibold tracking-wider">Validation Status</div>
              <div class="text-xl font-bold text-indigo-400 mt-1">Domain Ready</div>
            </div>
          </div>
        </div>

        <div class="mt-4 pt-3 border-t border-white/[0.04] text-[11px] text-slate-400 flex items-center justify-between">
          <span>Actuarial principle: Scenarios reference immutable base models via delta & multiplier shocks.</span>
          <span class="font-mono text-sky-400">Engine v1.0.0</span>
        </div>
      </div>
    </div>

    <!-- Scenarios Grid -->
    <div class="mb-8">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-300 flex items-center gap-2">
          <Sliders class="w-4 h-4 text-sky-400" />
          Configured Scenarios ({{ filteredScenarios.length }})
        </h2>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <div
          v-for="sc in filteredScenarios"
          :key="sc.id"
          :class="[
            'bg-slate-900/70 border rounded-2xl p-5 flex flex-col justify-between transition-all duration-200 hover:border-white/[0.15] hover:shadow-lg',
            selectedResultScenario?.id === sc.id ? 'border-sky-500/50 bg-slate-900/90 shadow-sky-500/10' : 'border-white/[0.06]',
          ]"
        >
          <!-- Card Header -->
          <div>
            <div class="flex items-start justify-between gap-2 mb-2">
              <div>
                <h3 class="text-sm font-bold text-white hover:text-sky-300 transition-colors">
                  {{ sc.name }}
                </h3>
                <span class="text-[10px] font-mono text-slate-500">{{ sc.id }}</span>
              </div>
              <span
                :class="[
                  'text-[10px] px-2 py-0.5 rounded-full font-semibold border',
                  sc.status === 'ACTIVE'
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-300 border-amber-500/20',
                ]"
              >
                {{ sc.status }}
              </span>
            </div>

            <p class="text-xs text-slate-400 mb-4 line-clamp-2">
              {{ sc.description || 'No description provided.' }}
            </p>

            <!-- Overrides Pills -->
            <div class="flex flex-wrap gap-1.5 mb-4">
              <!-- Interest -->
              <span
                v-if="sc.overrides?.interest_rate_bps"
                class="text-[11px] px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-300 border border-blue-500/20 font-mono"
              >
                Rate: {{ sc.overrides.interest_rate_bps > 0 ? '+' : '' }}{{ sc.overrides.interest_rate_bps }} bps
              </span>
              <span
                v-else-if="sc.overrides?.interest_rate_delta"
                class="text-[11px] px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-300 border border-blue-500/20 font-mono"
              >
                Rate: {{ sc.overrides.interest_rate_delta > 0 ? '+' : '' }}{{ sc.overrides.interest_rate_delta * 100 }}%
              </span>
              <span
                v-else-if="sc.overrides?.interest_rate_override"
                class="text-[11px] px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-300 border border-blue-500/20 font-mono"
              >
                Rate: {{ sc.overrides.interest_rate_override * 100 }}% fixed
              </span>

              <!-- Mortality -->
              <span
                v-if="sc.overrides?.mortality_multiplier && sc.overrides.mortality_multiplier !== 1"
                class="text-[11px] px-2 py-0.5 rounded-md bg-rose-500/10 text-rose-300 border border-rose-500/20 font-mono"
              >
                Mort: {{ sc.overrides.mortality_multiplier }}x
              </span>

              <!-- Lapse -->
              <span
                v-if="sc.overrides?.lapse_rate_delta"
                class="text-[11px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono"
              >
                Lapse: +{{ sc.overrides.lapse_rate_delta * 100 }}%
              </span>
              <span
                v-else-if="sc.overrides?.lapse_multiplier && sc.overrides.lapse_multiplier !== 1"
                class="text-[11px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono"
              >
                Lapse: {{ sc.overrides.lapse_multiplier }}x
              </span>
              <span
                v-else-if="sc.overrides?.lapse_override"
                class="text-[11px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono"
              >
                Lapse: {{ sc.overrides.lapse_override * 100 }}% fixed
              </span>

              <!-- Expense -->
              <span
                v-if="sc.overrides?.expense_multiplier && sc.overrides.expense_multiplier !== 1"
                class="text-[11px] px-2 py-0.5 rounded-md bg-purple-500/10 text-purple-300 border border-purple-500/20 font-mono"
              >
                Expense: {{ sc.overrides.expense_multiplier }}x
              </span>

              <!-- Baseline / No shocks -->
              <span
                v-if="!Object.keys(sc.overrides || {}).length"
                class="text-[11px] px-2 py-0.5 rounded-md bg-slate-800 text-slate-400 border border-white/[0.06]"
              >
                Baseline (Zero Shocks)
              </span>
            </div>

            <!-- Run Result Preview (if already executed) -->
            <div
              v-if="executionResults[sc.id]"
              class="mt-3 p-2.5 rounded-xl bg-slate-800/60 border border-white/[0.06] text-xs space-y-1"
            >
              <div class="flex justify-between items-center">
                <span class="text-slate-400">Best Estimate Liability:</span>
                <span class="font-bold text-white">{{ formatCurrency(executionResults[sc.id].bel) }}</span>
              </div>
              <div class="flex justify-between items-center text-[11px]">
                <span class="text-slate-400">Liability Delta:</span>
                <span
                  :class="[
                    'font-medium flex items-center gap-0.5',
                    executionResults[sc.id].delta_bel > 0
                      ? 'text-rose-400'
                      : executionResults[sc.id].delta_bel < 0
                      ? 'text-emerald-400'
                      : 'text-slate-300',
                  ]"
                >
                  <TrendingUp v-if="executionResults[sc.id].delta_bel > 0" class="w-3 h-3" />
                  <TrendingDown v-else-if="executionResults[sc.id].delta_bel < 0" class="w-3 h-3" />
                  {{ formatCurrency(executionResults[sc.id].delta_bel) }}
                  ({{ executionResults[sc.id].pct_change_bel > 0 ? '+' : '' }}{{ executionResults[sc.id].pct_change_bel.toFixed(1) }}%)
                </span>
              </div>
            </div>
          </div>

          <!-- Card Actions Toolbar -->
          <div class="mt-5 pt-3 border-t border-white/[0.06] flex items-center justify-between">
            <div class="flex items-center space-x-1.5">
              <button
                @click="handleRun(sc)"
                :disabled="runningScenarioId === sc.id"
                class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-sky-500/90 hover:bg-sky-400 text-white flex items-center space-x-1 transition-colors shadow-sm"
              >
                <RefreshCw v-if="runningScenarioId === sc.id" class="w-3.5 h-3.5 animate-spin" />
                <Play v-else class="w-3.5 h-3.5 fill-current" />
                <span>{{ runningScenarioId === sc.id ? 'Valuating...' : 'Run' }}</span>
              </button>

              <button
                @click="handleValidate(sc)"
                class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-emerald-400 border border-white/[0.06] transition-colors"
                title="Validate Actuarial Domain Rules"
              >
                <ShieldCheck class="w-4 h-4" />
              </button>
            </div>

            <div class="flex items-center space-x-1">
              <button
                @click="handleDuplicate(sc)"
                class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-sky-300 border border-white/[0.06] transition-colors"
                title="Duplicate Scenario"
              >
                <Copy class="w-3.5 h-3.5" />
              </button>
              <button
                @click="openEditModal(sc)"
                class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-amber-300 border border-white/[0.06] transition-colors"
                title="Edit Overrides"
              >
                <Edit2 class="w-3.5 h-3.5" />
              </button>
              <button
                @click="handleDelete(sc)"
                class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-rose-400 border border-white/[0.06] transition-colors"
                title="Delete Scenario"
              >
                <Trash2 class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Comparative Valuation Results Panel (If any scenario has executed) -->
    <div v-if="Object.keys(executionResults).length > 0" class="bg-slate-900/80 border border-white/[0.08] rounded-2xl p-6 shadow-2xl mb-8">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/[0.08] pb-4 mb-6">
        <div>
          <h3 class="text-base font-bold text-white flex items-center gap-2">
            <Activity class="w-5 h-5 text-emerald-400" />
            Scenario Valuation & Sensitivity Comparison
          </h3>
          <p class="text-xs text-slate-400 mt-0.5">
            Cross-scenario impact on Best Estimate Liabilities (BEL), net single premium, and cash flow projections.
          </p>
        </div>

        <!-- Result View Tabs -->
        <div class="flex items-center space-x-1 bg-slate-800/80 p-1 rounded-lg border border-white/[0.06] text-xs">
          <button
            @click="activeResultTab = 'summary'"
            :class="[
              'px-3 py-1 rounded-md transition-colors text-xs font-medium',
              activeResultTab === 'summary' ? 'bg-sky-500 text-white shadow' : 'text-slate-400 hover:text-white',
            ]"
          >
            Comparative Summary
          </button>
          <button
            @click="activeResultTab = 'cashflows'"
            :class="[
              'px-3 py-1 rounded-md transition-colors text-xs font-medium',
              activeResultTab === 'cashflows' ? 'bg-sky-500 text-white shadow' : 'text-slate-400 hover:text-white',
            ]"
          >
            Projected Cash Flows
          </button>
          <button
            @click="activeResultTab = 'reserves'"
            :class="[
              'px-3 py-1 rounded-md transition-colors text-xs font-medium',
              activeResultTab === 'reserves' ? 'bg-sky-500 text-white shadow' : 'text-slate-400 hover:text-white',
            ]"
          >
            Gross Reserve Profile
          </button>
        </div>
      </div>

      <!-- Tab 1: Comparative Summary Table -->
      <div v-if="activeResultTab === 'summary'" class="overflow-x-auto">
        <table class="w-full text-xs text-left">
          <thead class="bg-slate-800/60 text-slate-400 uppercase tracking-wider font-semibold border-b border-white/[0.06]">
            <tr>
              <th class="py-3 px-4">Scenario Name</th>
              <th class="py-3 px-4">Effective Interest</th>
              <th class="py-3 px-4">Mortality Factor</th>
              <th class="py-3 px-4">Lapse Rate</th>
              <th class="py-3 px-4">BEL ($)</th>
              <th class="py-3 px-4">Liability Delta</th>
              <th class="py-3 px-4">% Change</th>
              <th class="py-3 px-4">Net Premium</th>
              <th class="py-3 px-4">Reproducibility Job</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-white/[0.04]">
            <tr
              v-for="(res, id) in executionResults"
              :key="id"
              class="hover:bg-slate-800/40 transition-colors"
            >
              <td class="py-3 px-4 font-bold text-white flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-sky-400"></span>
                {{ res.scenario_name }}
              </td>
              <td class="py-3 px-4 font-mono text-emerald-300">
                {{ formatPercent(res.effective_interest_rate) }}
              </td>
              <td class="py-3 px-4 font-mono text-rose-300">
                {{ res.effective_mortality_multiplier }}x
              </td>
              <td class="py-3 px-4 font-mono text-amber-300">
                {{ formatPercent(res.effective_lapse_rate) }}
              </td>
              <td class="py-3 px-4 font-bold text-white">
                {{ formatCurrency(res.bel) }}
              </td>
              <td
                :class="[
                  'py-3 px-4 font-medium font-mono',
                  res.delta_bel > 0 ? 'text-rose-400' : res.delta_bel < 0 ? 'text-emerald-400' : 'text-slate-300',
                ]"
              >
                {{ res.delta_bel > 0 ? '+' : '' }}{{ formatCurrency(res.delta_bel) }}
              </td>
              <td
                :class="[
                  'py-3 px-4 font-bold font-mono',
                  res.pct_change_bel > 0 ? 'text-rose-400' : res.pct_change_bel < 0 ? 'text-emerald-400' : 'text-slate-300',
                ]"
              >
                {{ res.pct_change_bel > 0 ? '+' : '' }}{{ res.pct_change_bel?.toFixed(2) }}%
              </td>
              <td class="py-3 px-4 text-slate-200">
                {{ formatCurrency(res.annual_net_premium) }}
              </td>
              <td class="py-3 px-4">
                <span class="font-mono text-[10px] text-sky-400 bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/20">
                  {{ res.job_id.substring(0, 12) }}...
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Tab 2: Cash Flows Table -->
      <div v-else-if="activeResultTab === 'cashflows'">
        <!-- Scenario Selector for Cash Flows -->
        <div class="mb-4 flex items-center space-x-3">
          <label class="text-xs text-slate-400">View Cash Flows for:</label>
          <select
            v-model="selectedResultScenario"
            class="px-3 py-1.5 bg-slate-800 border border-white/[0.1] rounded-lg text-xs text-white"
          >
            <option
              v-for="sc in scenarios.filter(s => executionResults[s.id])"
              :key="sc.id"
              :value="sc"
            >
              {{ sc.name }} (BEL: {{ formatCurrency(executionResults[sc.id].bel) }})
            </option>
          </select>
        </div>

        <div v-if="selectedResultScenario && executionResults[selectedResultScenario.id]" class="overflow-x-auto">
          <table class="w-full text-xs text-left">
            <thead class="bg-slate-800/60 text-slate-400 uppercase tracking-wider font-semibold border-b border-white/[0.06]">
              <tr>
                <th class="py-2.5 px-3">Year $t$</th>
                <th class="py-2.5 px-3">Age</th>
                <th class="py-2.5 px-3">Inforce BOY</th>
                <th class="py-2.5 px-3">Premium Income</th>
                <th class="py-2.5 px-3">Death Claims</th>
                <th class="py-2.5 px-3">Maturity Benefit</th>
                <th class="py-2.5 px-3">Expenses</th>
                <th class="py-2.5 px-3">Net Liability CF</th>
                <th class="py-2.5 px-3">PV Net Liability</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/[0.04] font-mono text-[11px]">
              <tr
                v-for="cf in executionResults[selectedResultScenario.id].cash_flows"
                :key="cf.year"
                class="hover:bg-slate-800/40"
              >
                <td class="py-2 px-3 text-slate-300 font-sans font-bold">{{ cf.year }}</td>
                <td class="py-2 px-3 text-slate-400">{{ cf.age }}</td>
                <td class="py-2 px-3 text-slate-300">{{ cf.inforce_boy }}</td>
                <td class="py-2 px-3 text-emerald-400">{{ formatCurrency(cf.premium_income) }}</td>
                <td class="py-2 px-3 text-rose-400">{{ formatCurrency(cf.death_claims) }}</td>
                <td class="py-2 px-3 text-amber-400">{{ formatCurrency(cf.maturity_benefit) }}</td>
                <td class="py-2 px-3 text-slate-400">{{ formatCurrency(cf.total_expense) }}</td>
                <td class="py-2 px-3 font-semibold text-white">{{ formatCurrency(cf.net_liability_cf) }}</td>
                <td class="py-2 px-3 font-bold text-sky-400">{{ formatCurrency(cf.pv_net_liability) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Tab 3: Gross Reserve Profile Table -->
      <div v-else-if="activeResultTab === 'reserves'">
        <div class="mb-4 flex items-center space-x-3">
          <label class="text-xs text-slate-400">View Reserves for:</label>
          <select
            v-model="selectedResultScenario"
            class="px-3 py-1.5 bg-slate-800 border border-white/[0.1] rounded-lg text-xs text-white"
          >
            <option
              v-for="sc in scenarios.filter(s => executionResults[s.id])"
              :key="sc.id"
              :value="sc"
            >
              {{ sc.name }}
            </option>
          </select>
        </div>

        <div v-if="selectedResultScenario && executionResults[selectedResultScenario.id]" class="overflow-x-auto">
          <table class="w-full text-xs text-left">
            <thead class="bg-slate-800/60 text-slate-400 uppercase tracking-wider font-semibold border-b border-white/[0.06]">
              <tr>
                <th class="py-2.5 px-4">Duration $t$</th>
                <th class="py-2.5 px-4">Attained Age</th>
                <th class="py-2.5 px-4">Gross Premium Reserve $_t V$</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/[0.04] font-mono text-[11px]">
              <tr
                v-for="r in executionResults[selectedResultScenario.id].reserve_profile"
                :key="r.duration"
                class="hover:bg-slate-800/40"
              >
                <td class="py-2 px-4 text-slate-300 font-sans font-bold">{{ r.duration }}</td>
                <td class="py-2 px-4 text-slate-400">{{ r.age }}</td>
                <td class="py-2 px-4 font-bold text-sky-400">{{ formatCurrency(r.gross_reserve) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Modal: Create / Edit Scenario -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      @click.self="showModal = false"
    >
      <div class="bg-slate-900 border border-white/[0.1] rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl p-6">
        <div class="flex items-center justify-between border-b border-white/[0.08] pb-4 mb-5">
          <div>
            <h3 class="text-base font-bold text-white">
              {{ modalMode === 'create' ? 'Create Actuarial Scenario' : 'Edit Scenario Overrides' }}
            </h3>
            <p class="text-xs text-slate-400 mt-0.5">
              Specify assumption shocks relative to base model without modifying base configuration.
            </p>
          </div>
          <button @click="showModal = false" class="text-slate-400 hover:text-white text-lg font-bold">
            &times;
          </button>
        </div>

        <form @submit.prevent="saveScenario" class="space-y-4 text-xs">
          <!-- Name & Description -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label class="block text-slate-300 font-medium mb-1">Scenario Name *</label>
              <input
                v-model="scenarioForm.name"
                type="text"
                required
                placeholder="e.g. Severe Stress 2026"
                class="w-full px-3 py-2 bg-slate-800 border border-white/[0.1] rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label class="block text-slate-300 font-medium mb-1">Base Model</label>
              <select
                v-model="scenarioForm.base_model_id"
                class="w-full px-3 py-2 bg-slate-800 border border-white/[0.1] rounded-lg text-white focus:outline-none focus:border-sky-500"
              >
                <option v-for="m in baseModels" :key="m.id" :value="m.id">
                  {{ m.name }}
                </option>
              </select>
            </div>
          </div>

          <div>
            <label class="block text-slate-300 font-medium mb-1">Description</label>
            <textarea
              v-model="scenarioForm.description"
              rows="2"
              placeholder="Narrative explanation of the economic shock or stress conditions..."
              class="w-full px-3 py-2 bg-slate-800 border border-white/[0.1] rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
            ></textarea>
          </div>

          <!-- Section: Interest Rate Overrides -->
          <div class="p-3.5 bg-slate-800/40 rounded-xl border border-white/[0.06] space-y-3">
            <span class="text-xs font-semibold text-sky-400 flex items-center gap-1.5">
              <TrendingDown class="w-3.5 h-3.5" />
              Interest Rate / Discount Curve Shock
            </span>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Basis Points (bps)</label>
                <input
                  v-model.number="scenarioForm.interest_rate_bps"
                  type="number"
                  step="1"
                  placeholder="e.g. -100"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Rate Delta (Additive)</label>
                <input
                  v-model.number="scenarioForm.interest_rate_delta"
                  type="number"
                  step="0.001"
                  placeholder="e.g. -0.01"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Absolute Override</label>
                <input
                  v-model.number="scenarioForm.interest_rate_override"
                  type="number"
                  step="0.001"
                  placeholder="e.g. 0.04"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
            </div>
          </div>

          <!-- Section: Mortality & Lapse Shocks -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <!-- Mortality -->
            <div class="p-3.5 bg-slate-800/40 rounded-xl border border-white/[0.06] space-y-3">
              <span class="text-xs font-semibold text-rose-400 flex items-center gap-1.5">
                <Activity class="w-3.5 h-3.5" />
                Mortality Shock
              </span>
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Mortality Multiplier (e.g. 1.10 = +10%)</label>
                <input
                  v-model.number="scenarioForm.mortality_multiplier"
                  type="number"
                  step="0.01"
                  placeholder="1.0"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Alternative Table ID (Optional)</label>
                <input
                  v-model="scenarioForm.mortality_table_id"
                  type="text"
                  placeholder="soa_ilt"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
            </div>

            <!-- Lapse -->
            <div class="p-3.5 bg-slate-800/40 rounded-xl border border-white/[0.06] space-y-3">
              <span class="text-xs font-semibold text-amber-400 flex items-center gap-1.5">
                <Sliders class="w-3.5 h-3.5" />
                Lapse Shock
              </span>
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Lapse Delta (e.g. 0.05 = +5%)</label>
                <input
                  v-model.number="scenarioForm.lapse_rate_delta"
                  type="number"
                  step="0.005"
                  placeholder="0.0"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Lapse Multiplier</label>
                <input
                  v-model.number="scenarioForm.lapse_multiplier"
                  type="number"
                  step="0.05"
                  placeholder="1.0"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
            </div>
          </div>

          <!-- Section: Expenses -->
          <div class="p-3.5 bg-slate-800/40 rounded-xl border border-white/[0.06] space-y-3">
            <span class="text-xs font-semibold text-purple-400 flex items-center gap-1.5">
              <DollarSign class="w-3.5 h-3.5" />
              Expense & Inflation Overrides
            </span>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Expense Multiplier (e.g. 1.10 = +10%)</label>
                <input
                  v-model.number="scenarioForm.expense_multiplier"
                  type="number"
                  step="0.01"
                  placeholder="1.0"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
              <div>
                <label class="block text-slate-400 text-[11px] mb-1">Inflation Percentage (%)</label>
                <input
                  v-model.number="scenarioForm.expense_inflation_pct"
                  type="number"
                  step="0.1"
                  placeholder="e.g. 3.5"
                  class="w-full px-2.5 py-1.5 bg-slate-800 border border-white/[0.08] rounded-md text-white font-mono"
                />
              </div>
            </div>
          </div>

          <!-- Live Preview Box -->
          <div v-if="modalEffectivePreview" class="p-3 bg-slate-800/80 rounded-xl border border-sky-500/20 text-[11px]">
            <span class="font-semibold text-sky-300 block mb-1">Live Effective Assumption Preview:</span>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-slate-300 font-mono">
              <div>Rate: <span class="text-emerald-300">{{ formatPercent(modalEffectivePreview.interest_rate) }}</span></div>
              <div>Mort: <span class="text-rose-300">{{ modalEffectivePreview.mortality_multiplier }}x</span></div>
              <div>Lapse: <span class="text-amber-300">{{ formatPercent(modalEffectivePreview.lapse_rate) }}</span></div>
              <div>Exp: <span class="text-purple-300">{{ modalEffectivePreview.expense_multiplier.toFixed(2) }}x</span></div>
            </div>
          </div>

          <div class="flex items-center justify-end space-x-3 pt-4 border-t border-white/[0.08]">
            <button
              type="button"
              @click="showModal = false"
              class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              :disabled="loading"
              class="px-5 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-white font-semibold transition-colors shadow-lg shadow-sky-500/20"
            >
              {{ modalMode === 'create' ? 'Create Scenario' : 'Save Changes' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal: Validation Details -->
    <div
      v-if="showValidationModal && activeValidation"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      @click.self="showValidationModal = false"
    >
      <div class="bg-slate-900 border border-white/[0.1] rounded-2xl w-full max-w-lg shadow-2xl p-6">
        <div class="flex items-center justify-between border-b border-white/[0.08] pb-3 mb-4">
          <h3 class="text-sm font-bold text-white flex items-center gap-2">
            <ShieldCheck class="w-4 h-4 text-sky-400" />
            Actuarial Domain Validation: {{ activeValidation.scenario.name }}
          </h3>
          <button @click="showValidationModal = false" class="text-slate-400 hover:text-white">&times;</button>
        </div>

        <div class="space-y-4 text-xs">
          <!-- Status Badge -->
          <div
            :class="[
              'p-3 rounded-xl flex items-center space-x-2 border',
              activeValidation.result.is_valid
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                : 'bg-rose-500/10 border-rose-500/30 text-rose-400',
            ]"
          >
            <CheckCircle2 v-if="activeValidation.result.is_valid" class="w-5 h-5 flex-shrink-0" />
            <XCircle v-else class="w-5 h-5 flex-shrink-0" />
            <div>
              <div class="font-bold">
                {{ activeValidation.result.is_valid ? 'Validation Passed' : 'Actuarial Domain Violations Detected' }}
              </div>
              <div class="text-[11px] opacity-90">
                {{ activeValidation.result.is_valid ? 'All scenario overrides comply with mathematical and product rules.' : 'Fix the following domain errors before executing.' }}
              </div>
            </div>
          </div>

          <!-- Errors -->
          <div v-if="activeValidation.result.errors?.length > 0">
            <span class="text-rose-400 font-semibold uppercase text-[10px] tracking-wider block mb-1">Errors:</span>
            <ul class="space-y-1">
              <li
                v-for="(err, i) in activeValidation.result.errors"
                :key="i"
                class="p-2 rounded bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-1.5"
              >
                <XCircle class="w-3.5 h-3.5 flex-shrink-0" />
                {{ err }}
              </li>
            </ul>
          </div>

          <!-- Warnings -->
          <div v-if="activeValidation.result.warnings?.length > 0">
            <span class="text-amber-400 font-semibold uppercase text-[10px] tracking-wider block mb-1">Warnings:</span>
            <ul class="space-y-1">
              <li
                v-for="(warn, i) in activeValidation.result.warnings"
                :key="i"
                class="p-2 rounded bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs flex items-center gap-1.5"
              >
                <AlertTriangle class="w-3.5 h-3.5 flex-shrink-0" />
                {{ warn }}
              </li>
            </ul>
          </div>

          <!-- Effective Values -->
          <div class="p-3 bg-slate-800/60 rounded-xl border border-white/[0.06]">
            <span class="font-semibold text-slate-300 block mb-1">Resolved Effective Assumptions:</span>
            <div class="grid grid-cols-2 gap-2 text-[11px] font-mono text-slate-300">
              <div>Interest: <span class="text-emerald-300">{{ formatPercent(activeValidation.result.effective_assumptions.interest_rate) }}</span></div>
              <div>Mort Multiplier: <span class="text-rose-300">{{ activeValidation.result.effective_assumptions.mortality_multiplier }}x</span></div>
              <div>Lapse Rate: <span class="text-amber-300">{{ formatPercent(activeValidation.result.effective_assumptions.lapse_flat_rate) }}</span></div>
              <div>Expense Multiplier: <span class="text-purple-300">{{ activeValidation.result.effective_assumptions.expense_multiplier.toFixed(2) }}x</span></div>
            </div>
          </div>
        </div>

        <div class="mt-5 text-right">
          <button
            @click="showValidationModal = false"
            class="px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Custom scrollbar */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: #0b0f19;
}
::-webkit-scrollbar-thumb {
  background: #1e293b;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #334155;
}
</style>
