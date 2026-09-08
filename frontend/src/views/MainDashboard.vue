<script setup>
import { ref, shallowRef, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import {
  checkHealth,
  fetchTables,
  uploadMortalityTable,
  runDeterministicValuation,
  runIFRS17Valuation,
  runSensitivityAnalysis,
  startAsyncStochasticValuation,
  getStochasticJobStatus,
  runStochasticValuation,
  uploadPortfolioCSV,
  getSamplePortfolioCSVUrl,
  ActuaryApiError,
} from '../services/actuaryApi'
import { connectSimulationSocket } from '../services/simulationSocket'

// Decomposed Modular Dashboard Components
import ValuationForm from '../components/ValuationForm.vue'
import OverviewDashboard from '../components/OverviewDashboard.vue'
import ReserveDashboard from '../components/ReserveDashboard.vue'
import StochasticDashboard from '../components/StochasticDashboard.vue'
import IFRS17Dashboard from '../components/IFRS17Dashboard.vue'
import SensitivityDashboard from '../components/SensitivityDashboard.vue'
import PortfolioDashboard from '../components/PortfolioDashboard.vue'
import CashFlowTable from '../components/CashFlowTable.vue'
import ContractBuilderView from './ContractBuilderView.vue'
import AssumptionLibraryView from './AssumptionLibraryView.vue'
import CommandPalette from '../components/CommandPalette.vue'
import { useRouter } from 'vue-router'
import { createRequestState } from '../utils/useAsyncState'
import { exportValuationCSV } from '../utils/export.js'

// ────────────────────────────────────────────────────────────
// Reactive Dashboard State & Request State Machines
// ────────────────────────────────────────────────────────────

const activeTab = ref('overview')
const backendStatus = ref('checking')
const backendDetails = ref(null)
const sidebarOpen = ref(false)
const lastRunTime = ref(null)

const showCommandPalette = ref(false)
const router = useRouter()

// Individual Request States (loading, error, data lifecycle)
const detState = createRequestState()
const stochState = createRequestState()
const ifrs17State = createRequestState()
const sensState = createRequestState()
const portfolioState = createRequestState()

// Global aggregated loading and error states for header indicators
const loading = computed(() => detState.loading.value || stochState.loading.value || ifrs17State.loading.value || sensState.loading.value)
const errorMessage = computed(() => detState.error.value || stochState.error.value || ifrs17State.error.value || sensState.error.value || null)

// Mortality Table Registry State
const availableTables = ref([])
const showTableModal = ref(false)
const uploadTableLoading = ref(false)
const uploadTableError = ref(null)
const uploadTableName = ref('')
const uploadTableDesc = ref('')
const uploadTableFile = ref(null)
const isTableDragging = ref(false)
const tableFileInput = ref(null)

// Simulation Progress Tracking
const isSimulating = ref(false)
const simProgress = ref(0)
const completedPaths = ref(0)
const totalPaths = ref(0)
const partialMetrics = ref(null)
let activeSocketConnection = null

// Portfolio Batch State
const portfolioInterestRate = ref(0.05)

// Sensitivity & Stress Ref
const sensitivityDashboardRef = ref(null)

// Form Parameters with standard actuarial defaults
const form = reactive({
  product_type: 'endowment',
  issue_age: 30,
  term: 20,
  sum_assured: 1000000,
  premium_paying_term: null,
  interest_rate: 0.05,
  gross_premium: null,
  table_id: 'soa_ilt',
  ra_ratio: 0.06,
  expense: {
    percent_of_premium_first: 0.35,
    percent_of_premium_renewal: 0.05,
    per_policy_first: 200.0,
    per_policy_renewal: 20.0,
  },
  lapse: {
    duration_rates: [0.08, 0.05, 0.04, 0.03],
    flat_annual_rate: 0.02,
  },
  vasicek: {
    r0: 0.05,
    kappa: 0.20,
    theta: 0.05,
    sigma: 0.015,
  },
  enable_dynamic_lapse: true,
  dynamic_lapse: {
    base_lapse_rate: 0.04,
    credited_rate: 0.04,
    min_lapse_rate: 0.01,
    max_lapse_rate: 0.35,
    sensitivity: 25.0,
    spread_threshold: 0.0,
  },
  n_scenarios: 5000,
  seed: 42,
})

// Navigation definition
const navItems = [
  { id: 'overview', label: 'Overview', icon: 'chart' },
  { id: 'builder', label: 'Logic Builder', icon: 'blueprint' },
  { id: 'stochastic', label: 'ESG & Risk', icon: 'risk' },
  { id: 'sensitivity', label: 'Stress Testing', icon: 'tornado' },
  { id: 'ifrs17', label: 'IFRS 17', icon: 'balance' },
  { id: 'reserves', label: 'Reserves', icon: 'reserve' },
  { id: 'cashflows', label: 'Cash Flows', icon: 'cashflow' },
  { id: 'table', label: 'Cohort Data', icon: 'table' },
  { id: 'portfolio', label: 'Portfolio Batch', icon: 'portfolio' },
  { id: 'assumptions', label: 'Assumptions', icon: 'database' },
  { id: 'history', label: 'Run History', icon: 'history' },
]

function formatCurrency(val) {
  if (val === undefined || val === null || isNaN(val)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(val)
}

function switchTab(tabId) {
  if (tabId === 'history') {
    router.push('/history')
    sidebarOpen.value = false
    return
  }
  activeTab.value = tabId
  sidebarOpen.value = false
  checkAndLazyLoadTab(tabId)
  if (tabId === 'sensitivity') {
    nextTick(() => {
      sensitivityDashboardRef.value?.resizeCharts?.()
    })
  }
}

// ────────────────────────────────────────────────────────────
// Preset Contract Loaders
// ────────────────────────────────────────────────────────────

function applyPreset(type) {
  if (type === 'endowment_20') {
    form.product_type = 'endowment'
    form.issue_age = 30
    form.term = 20
    form.sum_assured = 1000000
    form.interest_rate = 0.05
    form.vasicek.sigma = 0.015
    form.enable_dynamic_lapse = true
  } else if (type === 'term_30') {
    form.product_type = 'term'
    form.issue_age = 35
    form.term = 30
    form.sum_assured = 750000
    form.interest_rate = 0.045
    form.vasicek.sigma = 0.02
    form.enable_dynamic_lapse = true
  } else if (type === 'whole_life') {
    form.product_type = 'whole_life'
    form.issue_age = 40
    form.term = null
    form.sum_assured = 500000
    form.interest_rate = 0.05
    form.vasicek.sigma = 0.012
    form.enable_dynamic_lapse = false
  } else if (type === 'large_scale_10k') {
    form.product_type = 'endowment'
    form.issue_age = 30
    form.term = 20
    form.sum_assured = 1000000
    form.n_scenarios = 10000
    form.vasicek.sigma = 0.02
    form.enable_dynamic_lapse = true
  }
  executeValuation()
}

// ────────────────────────────────────────────────────────────
// API Communication & Valuation Orchestrator
// ────────────────────────────────────────────────────────────

// ────────────────────────────────────────────────────────────
// API Communication & Progressive Valuation Orchestrator
// ────────────────────────────────────────────────────────────

function buildDeterministicPayload() {
  return {
    product_type: form.product_type,
    issue_age: form.issue_age,
    term: form.product_type === 'whole_life' ? null : form.term,
    sum_assured: form.sum_assured,
    premium_paying_term: form.premium_paying_term,
    interest_rate: form.interest_rate,
    gross_premium: form.gross_premium,
    table_id: form.table_id,
    expense: form.expense,
    lapse: form.lapse,
  }
}

function buildStochasticPayload() {
  return {
    product_type: form.product_type,
    issue_age: form.issue_age,
    term: form.product_type === 'whole_life' ? null : form.term,
    sum_assured: form.sum_assured,
    premium_paying_term: form.premium_paying_term,
    gross_premium: form.gross_premium,
    table_id: form.table_id,
    vasicek: form.vasicek,
    dynamic_lapse: form.enable_dynamic_lapse ? form.dynamic_lapse : null,
    expense: form.expense,
    n_scenarios: form.n_scenarios,
    seed: form.seed,
  }
}

async function runStochasticAsyncWithSocket(requestId, signal) {
  if (activeSocketConnection) {
    try { activeSocketConnection.close() } catch (_) {}
    activeSocketConnection = null
  }

  isSimulating.value = true
  simProgress.value = 0
  completedPaths.value = 0
  totalPaths.value = form.n_scenarios
  partialMetrics.value = null

  const stochPayload = buildStochasticPayload()

  return new Promise(async (resolve, reject) => {
    // If signal already aborted before dispatch
    if (signal?.aborted) {
      isSimulating.value = false
      return reject(new Error('Simulation aborted'))
    }

    try {
      const jobRes = await startAsyncStochasticValuation(stochPayload, { signal })
      if (!stochState.isLatest(requestId)) {
        isSimulating.value = false
        return
      }

      const jobId = jobRes.job_id

      activeSocketConnection = connectSimulationSocket(jobId, {
        onProgress: (prog) => {
          if (!stochState.isLatest(requestId)) return
          simProgress.value = prog.percent
          completedPaths.value = prog.completed_paths
          totalPaths.value = prog.total_paths
          if (prog.partial_metrics) {
            partialMetrics.value = prog.partial_metrics
          }
        },
        onComplete: (data) => {
          if (!stochState.isLatest(requestId)) return
          simProgress.value = 100
          completedPaths.value = totalPaths.value
          isSimulating.value = false
          resolve(data)
        },
        onError: async (err) => {
          if (!stochState.isLatest(requestId)) return
          console.warn('WebSocket error, falling back to HTTP polling:', err)
          try {
            let attempts = 0
            while (attempts < 60) {
              if (!stochState.isLatest(requestId) || signal?.aborted) return
              await new Promise(r => setTimeout(r, 250))
              const statusRes = await getStochasticJobStatus(jobId, { signal })
              if (!stochState.isLatest(requestId)) return
              simProgress.value = statusRes.progress
              completedPaths.value = statusRes.completed_paths
              if (statusRes.status === 'COMPLETED' && statusRes.result) {
                isSimulating.value = false
                resolve(statusRes.result)
                return
              } else if (statusRes.status === 'FAILED') {
                throw new Error(statusRes.error || 'Async simulation failed')
              }
              attempts++
            }
            throw new Error('Simulation polling timed out')
          } catch (pollErr) {
            reject(pollErr)
          }
        },
      })
    } catch (err) {
      if (!stochState.isLatest(requestId) || signal?.aborted) {
        isSimulating.value = false
        return
      }
      try {
        const syncRes = await runStochasticValuation(stochPayload, { signal })
        if (!stochState.isLatest(requestId)) return
        simProgress.value = 100
        completedPaths.value = form.n_scenarios
        isSimulating.value = false
        resolve(syncRes)
      } catch (syncErr) {
        reject(syncErr)
      }
    }
  })
}

// 1. Fast, instant baseline valuation (<10ms)
async function executeBaselineValuation() {
  const { requestId, signal } = detState.start()

  try {
    const detPayload = buildDeterministicPayload()
    const detRes = await runDeterministicValuation(detPayload, { signal })
    detState.success(detRes, requestId)
    backendStatus.value = 'healthy'
  } catch (err) {
    console.error('Baseline valuation error:', err)
    detState.failure(err, requestId)
    backendStatus.value = 'error'
  }
}

// 2. Full progressive valuation execution with race-condition guard
async function executeValuation() {
  const detReq = detState.start()
  const ifrs17Req = ifrs17State.start()
  const sensReq = sensState.start()
  const stochReq = stochState.start()

  // 1. Immediate deterministic calculation
  try {
    const detPayload = buildDeterministicPayload()
    const detRes = await runDeterministicValuation(detPayload, { signal: detReq.signal })
    detState.success(detRes, detReq.requestId)
    backendStatus.value = 'healthy'
  } catch (err) {
    console.error('Deterministic valuation error:', err)
    detState.failure(err, detReq.requestId)
    ifrs17State.failure(err, ifrs17Req.requestId)
    sensState.failure(err, sensReq.requestId)
    stochState.failure(err, stochReq.requestId)
    backendStatus.value = 'error'
    return
  }

  // 2. Secondary valuations asynchronously in background
  const detPayload = buildDeterministicPayload()
  const ifrs17Payload = { ...detPayload, ra_ratio: form.ra_ratio }
  const sensPayload = { ...detPayload }

  const ifrs17Task = runIFRS17Valuation(ifrs17Payload, { signal: ifrs17Req.signal })
    .then(res => ifrs17State.success(res, ifrs17Req.requestId))
    .catch(err => {
      console.warn('IFRS17 valuation error:', err)
      ifrs17State.failure(err, ifrs17Req.requestId)
    })

  const sensTask = runSensitivityAnalysis(sensPayload, { signal: sensReq.signal })
    .then(res => sensState.success(res, sensReq.requestId))
    .catch(err => {
      console.warn('Sensitivity analysis error:', err)
      sensState.failure(err, sensReq.requestId)
    })

  const stochTask = runStochasticAsyncWithSocket(stochReq.requestId, stochReq.signal)
    .then(res => stochState.success(res, stochReq.requestId))
    .catch(err => {
      console.warn('Stochastic valuation error:', err)
      stochState.failure(err, stochReq.requestId)
    })

  await Promise.allSettled([ifrs17Task, sensTask, stochTask])
  const ts = new Date().toLocaleTimeString('en-US', { hour12: false })
  lastRunTime.value = ts
}

// On-demand lazy loader for tabs
async function checkAndLazyLoadTab(tabId) {
  if (tabId === 'ifrs17' && !ifrs17State.data.value && !ifrs17State.loading.value) {
    const { requestId, signal } = ifrs17State.start()
    try {
      const ifrs17Payload = { ...buildDeterministicPayload(), ra_ratio: form.ra_ratio }
      const res = await runIFRS17Valuation(ifrs17Payload, { signal })
      ifrs17State.success(res, requestId)
    } catch (err) {
      console.warn('Lazy IFRS 17 loading failed:', err)
      ifrs17State.failure(err, requestId)
    }
  }
  if (tabId === 'stochastic' && !stochState.data.value && !stochState.loading.value && !isSimulating.value) {
    const { requestId, signal } = stochState.start()
    try {
      const res = await runStochasticAsyncWithSocket(requestId, signal)
      stochState.success(res, requestId)
    } catch (err) {
      console.warn('Lazy Stochastic loading failed:', err)
      stochState.failure(err, requestId)
    }
  }
}

async function loadTableCatalogue() {
  try {
    const tables = await fetchTables()
    availableTables.value = tables
    if (tables.length > 0 && !availableTables.value.some(t => t.table_id === form.table_id)) {
      form.table_id = tables[0].table_id
    }
  } catch (err) {
    console.warn('Failed to load table catalogue:', err)
  }
}

async function checkBackendConnection() {
  try {
    const health = await checkHealth()
    backendStatus.value = health.status === 'healthy' ? 'healthy' : 'error'
    backendDetails.value = health
    await loadTableCatalogue()
    return true
  } catch (err) {
    console.warn('Backend health check error:', err)
    backendStatus.value = 'error'
    return false
  }
}

// ────────────────────────────────────────────────────────────
// Custom Mortality Table Upload
// ────────────────────────────────────────────────────────────

function handleTableFileSelect(event) {
  uploadTableFile.value = event.target.files?.[0] || null
}

function handleTableFileDrop(event) {
  isTableDragging.value = false
  uploadTableFile.value = event.dataTransfer?.files?.[0] || null
}

async function submitCustomTable() {
  if (!uploadTableFile.value) {
    uploadTableError.value = 'Please select a mortality table file (.csv, .xml, .xtbml).'
    return
  }

  uploadTableLoading.value = true
  uploadTableError.value = null

  try {
    const formData = new FormData()
    formData.append('file', uploadTableFile.value)
    if (uploadTableName.value) formData.append('table_name', uploadTableName.value)
    if (uploadTableDesc.value) formData.append('table_description', uploadTableDesc.value)

    const res = await uploadMortalityTable(formData)
    await loadTableCatalogue()
    form.table_id = res.table_id

    showTableModal.value = false
    uploadTableFile.value = null
    uploadTableName.value = ''
    uploadTableDesc.value = ''

    await executeValuation()
  } catch (err) {
    console.error('Table upload error:', err)
    uploadTableError.value = err.message || 'Failed to upload mortality table.'
  } finally {
    uploadTableLoading.value = false
  }
}

// ────────────────────────────────────────────────────────────
// Portfolio Batch Upload & Processing
// ────────────────────────────────────────────────────────────

async function handlePortfolioFileUpload(file) {
  if (!file) return
  await processPortfolioFile(file)
}

async function processPortfolioFile(file) {
  portfolioState.start()

  try {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('interest_rate', portfolioInterestRate.value)
    formData.append('table_id', form.table_id)

    const res = await uploadPortfolioCSV(formData)
    portfolioState.success(res)
    activeTab.value = 'portfolio'
  } catch (err) {
    console.error('Portfolio valuation error:', err)
    portfolioState.failure(err)
  }
}

async function runSamplePortfolioDemo(nPolicies = 1000) {
  portfolioState.start()

  try {
    const url = getSamplePortfolioCSVUrl(nPolicies)
    const fetchRes = await fetch(url)
    const blob = await fetchRes.blob()
    const file = new File([blob], `sample_portfolio_${nPolicies}.csv`, { type: 'text/csv' })
    await processPortfolioFile(file)
  } catch (err) {
    console.error('Demo portfolio error:', err)
    portfolioState.failure(err)
  }
}

// ────────────────────────────────────────────────────────────
// Lifecycle Hooks
// ────────────────────────────────────────────────────────────

function handleCommandPaletteAction(actionId) {
  switch (actionId) {
    case 'run_valuation':
      executeValuation()
      break
    case 'export_csv':
      exportValuationCSV(detState.data.value, form)
      break
    case 'upload_table':
      showTableModal.value = true
      break
    case 'view_history':
      router.push('/history')
      break
    case 'tab_overview':
      switchTab('overview')
      break
    case 'tab_sensitivity':
      switchTab('sensitivity')
      break
  }
}

onMounted(async () => {
  const isConnected = await checkBackendConnection()
  if (isConnected) {
    // Only execute the ultra-fast deterministic baseline on initial app launch (<10ms)
    // Stochastic (5,000+ paths) & full suite will run smoothly when the user clicks 'Run Valuation' or switches to that tab
    await executeBaselineValuation()
  }
})

onUnmounted(() => {
  if (activeSocketConnection) {
    activeSocketConnection.close()
    activeSocketConnection = null
  }
})
</script>

<template>
  <div class="min-h-screen bg-[#0B0F19] text-slate-100 font-sans selection:bg-sky-500/20">

    <!-- ═══════════════════════════════════════════════════════ -->
    <!-- SIDEBAR NAVIGATION                                     -->
    <!-- ═══════════════════════════════════════════════════════ -->
    <aside :class="['sidebar', sidebarOpen ? 'open' : '']">
      <!-- Brand -->
      <div class="px-5 py-5 flex items-center space-x-3 border-b border-white/[0.06]">
        <div class="h-12 w-12 rounded-xl flex-shrink-0 shadow-md border border-white/[0.05] relative overflow-hidden bg-[#070b14]">
          <img src="/logo.jpg" alt="Actura Mascot" class="absolute w-[220%] h-[220%] max-w-none -bottom-[15%] -right-[20%]" />
        </div>
        <div>
          <div class="text-sm font-semibold text-white tracking-tight">Actura</div>
          <div class="text-[10px] text-slate-500 font-medium">Actuarial Valuation & Risk Platform</div>
        </div>
      </div>

      <!-- Nav Items -->
      <nav class="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        <button
          v-for="item in navItems"
          :key="item.id"
          @click="switchTab(item.id)"
          :class="['sidebar-nav-item w-full text-left', activeTab === item.id ? 'active' : '']"
        >
          <!-- Icons -->
          <svg v-if="item.icon === 'blueprint'" class="h-4 w-4 flex-shrink-0 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
          </svg>
          <svg v-else-if="item.icon === 'chart'" class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
          </svg>
          <svg v-else-if="item.icon === 'risk'" class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5" />
          </svg>
          <svg v-else-if="item.icon === 'tornado'" class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <svg v-else-if="item.icon === 'balance'" class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v17.25m0 0c-1.472 0-2.882.265-4.185.75M12 20.25c1.472 0 2.882.265 4.185.75M18.75 4.97A48.416 48.416 0 0012 4.5c-2.291 0-4.545.16-6.75.47m13.5 0c1.01.143 2.01.317 3 .52m-3-.52l2.62 10.726c.122.499-.106 1.028-.589 1.202a5.988 5.988 0 01-2.031.352 5.988 5.988 0 01-2.031-.352c-.483-.174-.711-.703-.59-1.202L18.75 4.971zm-16.5.52c.99-.203 1.99-.377 3-.52m0 0l2.62 10.726c.122.499-.106 1.028-.589 1.202a5.989 5.989 0 01-2.031.352 5.989 5.989 0 01-2.031-.352c-.483-.174-.711-.703-.59-1.202L5.25 4.971z" />
          </svg>
          <svg v-else-if="item.icon === 'portfolio'" class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
          </svg>
          <svg v-else-if="item.icon === 'reserve'" class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
          </svg>
          <svg v-else-if="item.icon === 'cashflow'" class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
          </svg>
          <svg v-else-if="item.icon === 'history'" class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6l4 2m6-2a10 10 0 11-20 0 10 10 0 0120 0z" />
          </svg>
          <svg v-else class="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125M12 10.875v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125M10.875 12c-.621 0-1.125.504-1.125 1.125M12 12c.621 0 1.125.504 1.125 1.125m0 0v1.5c0 .621-.504 1.125-1.125 1.125m0-3.75c-.621 0-1.125.504-1.125 1.125" />
          </svg>
          <span>{{ item.label }}</span>
        </button>
      </nav>


    </aside>

    <!-- ═══════════════════════════════════════════════════════ -->
    <!-- MAIN CONTENT AREA (offset by sidebar)                  -->
    <!-- ═══════════════════════════════════════════════════════ -->
    <div class="lg:ml-[240px]">

      <!-- ─── Top Header Bar ─── -->
      <header class="header-bar sticky top-0 z-30 px-6 h-14 flex items-center justify-between">
        <!-- Mobile hamburger -->
        <button @click="sidebarOpen = !sidebarOpen" class="lg:hidden mr-3 text-slate-400 hover:text-white">
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
          </svg>
        </button>

        <!-- Search Bar -->
        <div class="hidden sm:flex items-center flex-1 max-w-md">
          <CommandPalette @action="handleCommandPaletteAction" />
        </div>

        <!-- Right Actions -->
        <div class="flex items-center space-x-2.5">
          <button @click="executeValuation" :disabled="loading" class="btn-primary flex items-center space-x-1.5 text-[13px]">
            <svg :class="['h-3.5 w-3.5', loading ? 'animate-spin' : '']" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5.636 5.636a9 9 0 1012.728 0M12 3v9" />
            </svg>
            <span>{{ loading ? 'Running...' : 'Run Valuation' }}</span>
          </button>
          <button @click="showTableModal = true" class="btn-secondary flex items-center space-x-1.5 text-[13px]">
            <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
            <span>Upload</span>
          </button>

          <!-- Status -->
          <div class="hidden md:flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-[11px]">
            <span :class="['h-1.5 w-1.5 rounded-full', backendStatus === 'healthy' ? 'bg-emerald-400' : 'bg-rose-400']"></span>
            <span class="text-slate-400 font-medium">{{ backendStatus === 'healthy' ? 'Online' : 'Offline' }}</span>
          </div>
        </div>
      </header>

      <!-- ─── Mobile Sidebar Overlay ─── -->
      <div v-if="sidebarOpen" @click="sidebarOpen = false" class="fixed inset-0 bg-black/50 z-30 lg:hidden"></div>

      <!-- ─── Error Banner ─── -->
      <div v-if="errorMessage || backendStatus === 'error'" class="mx-6 mt-4">
        <div class="card p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-rose-500/20">
          <div class="flex items-center space-x-2.5 text-sm">
            <span class="h-2 w-2 rounded-full bg-rose-500 animate-pulse"></span>
            <div>
              <span class="font-medium text-rose-400">Connection Error: </span>
              <span class="text-slate-400 text-xs">{{ errorMessage || 'FastAPI server unreachable at http://127.0.0.1:8000' }}</span>
            </div>
          </div>
          <div class="flex items-center space-x-2">
            <code class="text-[10px] text-slate-500 bg-black/30 px-2 py-1 rounded font-mono">uvicorn actuary_engine.api.main:app --port 8000</code>
            <button @click="executeValuation" class="btn-primary text-[11px] px-3 py-1">Retry</button>
          </div>
        </div>
      </div>

      <!-- ─── Simulation Progress Bar ─── -->
      <div v-if="isSimulating" class="mx-6 mt-4">
        <div class="card p-4 space-y-2">
          <div class="flex items-center justify-between text-xs">
            <div class="flex items-center space-x-2">
              <span class="h-2 w-2 rounded-full bg-sky-400 animate-pulse"></span>
              <span class="font-medium text-slate-200">Monte Carlo Simulation</span>
              <span class="text-slate-500 font-mono text-[11px]">({{ completedPaths.toLocaleString() }} / {{ totalPaths.toLocaleString() }} paths)</span>
            </div>
            <div class="flex items-center space-x-3">
              <span v-if="partialMetrics" class="text-slate-400 text-[11px]">
                Mean BEL: <strong class="text-emerald-400 font-mono">{{ formatCurrency(partialMetrics.mean_bel) }}</strong>
              </span>
              <span class="font-semibold text-sky-400 font-mono">{{ simProgress.toFixed(0) }}%</span>
            </div>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: `${simProgress}%` }"></div>
          </div>
        </div>
      </div>

      <!-- ═══════════════════════════════════════════════════════ -->
      <!-- WELCOME HEADER + QUICK ACTIONS                         -->
      <!-- ═══════════════════════════════════════════════════════ -->
      <div class="px-6 pt-6 pb-2">
        <h1 class="text-2xl font-semibold text-white tracking-tight">Dashboard</h1>
        <p class="text-sm text-slate-500 mt-1">Actuarial valuation, risk analytics, and regulatory reporting</p>

        <div class="mt-4 flex flex-wrap gap-2">
          <button @click="$router.push('/guided')" class="btn-primary text-[12px] px-3 py-1.5 rounded-md bg-gradient-to-r from-sky-500 to-indigo-500 hover:from-sky-400 hover:to-indigo-400 border-none">✨ Guided Workflow</button>
          <button @click="applyPreset('endowment_20')" class="btn-secondary text-[12px] px-3 py-1.5 rounded-md">20-Yr Endowment</button>
          <button @click="applyPreset('term_30')" class="btn-secondary text-[12px] px-3 py-1.5 rounded-md">30-Yr Term</button>
          <button @click="applyPreset('large_scale_10k')" class="btn-secondary text-[12px] px-3 py-1.5 rounded-md">10K Monte Carlo</button>
          <button @click="switchTab('sensitivity')" class="btn-secondary text-[12px] px-3 py-1.5 rounded-md">Sensitivity Shock</button>
          <button @click="switchTab('portfolio'); runSamplePortfolioDemo(1000)" class="btn-secondary text-[12px] px-3 py-1.5 rounded-md">Batch Portfolio</button>
        </div>
      </div>

      <!-- ═══════════════════════════════════════════════════════ -->
      <!-- PRIMARY CORE DASHBOARD TABS (with Form Layout)          -->
      <!-- ═══════════════════════════════════════════════════════ -->
      <section v-show="['overview', 'reserves', 'stochastic', 'cashflows', 'table'].includes(activeTab)" class="px-6 py-4">
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <!-- Left 1/3: Modular Valuation Input Form -->
          <div class="space-y-4">
            <ValuationForm
              :form="form"
              :available-tables="availableTables"
              :loading="loading"
              :sim-progress="simProgress"
              :det-loading="detState.loading.value"
              :ifrs17-loading="ifrs17State.loading.value"
              :sens-loading="sensState.loading.value"
              :stoch-loading="stochState.loading.value"
              :last-run-time="lastRunTime"
              @submit="executeValuation"
              @open-table-modal="showTableModal = true"
            />
          </div>

          <!-- Right 2/3: Active Dashboard View -->
          <div class="lg:col-span-2 space-y-5">
            <!-- 1. Overview Dashboard -->
            <div v-show="activeTab === 'overview'">
              <OverviewDashboard
                :deterministic-data="detState.data.value"
                :stochastic-data="stochState.data.value"
                :form="form"
                :loading="detState.loading.value || stochState.loading.value"
                :error="detState.error.value || stochState.error.value"
                :is-active="activeTab === 'overview'"
                @run-valuation="executeValuation"
              />
            </div>

            <!-- 2. Reserve Dashboard -->
            <div v-show="activeTab === 'reserves'">
              <ReserveDashboard
                :deterministic-data="detState.data.value"
                :loading="detState.loading.value"
                :error="detState.error.value"
                :is-active="activeTab === 'reserves'"
                @run-valuation="executeValuation"
              />
            </div>

            <!-- 3. Stochastic & ESG Dashboard -->
            <div v-show="activeTab === 'stochastic'">
              <StochasticDashboard
                :stochastic-data="stochState.data.value"
                :form="form"
                :loading="stochState.loading.value"
                :error="stochState.error.value"
                :is-active="activeTab === 'stochastic'"
                @run-valuation="executeValuation"
              />
            </div>

            <!-- 4. Cash Flows Tab -->
            <div v-show="activeTab === 'cashflows'">
              <CashFlowTable :cash-flows="detState.data.value?.cash_flows || []" />
            </div>

            <!-- 5. Cohort Data Tab -->
            <div v-show="activeTab === 'table'" class="card p-5">
              <div class="flex items-center justify-between mb-4">
                <div>
                  <h3 class="text-sm font-semibold text-white">Multi-Decrement Cohort Table</h3>
                  <p class="text-[11px] text-slate-500">{{ detState.data.value?.cash_flows?.length || 0 }} projection periods</p>
                </div>
              </div>
              <div class="overflow-x-auto card-inset rounded-lg max-h-[500px]">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th>Age</th>
                      <th>Inforce</th>
                      <th>Premium</th>
                      <th>Claims</th>
                      <th>Expenses</th>
                      <th>Net CF</th>
                      <th>PV Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in detState.data.value?.cash_flows || []" :key="row.year">
                      <td class="text-sky-400 font-semibold font-mono">t={{ row.year }}</td>
                      <td class="font-mono">{{ row.age }}</td>
                      <td class="text-slate-500 font-mono">{{ (row.inforce_boy * 100).toFixed(2) }}%</td>
                      <td class="text-emerald-400 font-mono">{{ formatCurrency(row.premium_income) }}</td>
                      <td class="text-rose-400 font-mono">{{ formatCurrency(row.death_claims + row.maturity_benefit) }}</td>
                      <td class="text-amber-400 font-mono">{{ formatCurrency(row.total_expense) }}</td>
                      <td :class="['font-mono font-semibold', row.net_liability_cf > 0 ? 'text-rose-400' : 'text-emerald-400']">
                        {{ formatCurrency(row.net_liability_cf) }}
                      </td>
                      <td :class="['font-mono font-semibold', row.pv_net_liability > 0 ? 'text-rose-400' : 'text-emerald-400']">
                        {{ formatCurrency(row.pv_net_liability) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ═══════════════════════════════════════════════════════ -->
      <!-- SENSITIVITY & STRESS TESTING TAB                       -->
      <!-- ═══════════════════════════════════════════════════════ -->
      <section v-show="activeTab === 'sensitivity'" class="px-6 py-4">
        <SensitivityDashboard
          :form="form"
          :sensitivity-data="sensState.data.value"
          :loading="sensState.loading.value"
          :error="sensState.error.value"
          :is-active="activeTab === 'sensitivity'"
          ref="sensitivityDashboardRef"
          @run-valuation="executeValuation"
        />
      </section>

      <!-- ═══════════════════════════════════════════════════════ -->
      <!-- IFRS 17 TAB                                            -->
      <!-- ═══════════════════════════════════════════════════════ -->
      <section v-show="activeTab === 'ifrs17'" class="px-6 py-4">
        <IFRS17Dashboard
          :ifrs17-data="ifrs17State.data.value"
          :loading="ifrs17State.loading.value"
          :error="ifrs17State.error.value"
          :is-active="activeTab === 'ifrs17'"
          @run-valuation="executeValuation"
        />
      </section>

      <!-- ═══════════════════════════════════════════════════════ -->
      <!-- PORTFOLIO BATCH TAB                                     -->
      <!-- ═══════════════════════════════════════════════════════ -->
      <section v-show="activeTab === 'portfolio'" class="px-6 py-4">
        <PortfolioDashboard
          :portfolio-data="portfolioState.data.value"
          :portfolio-loading="portfolioState.loading.value"
          :portfolio-error="portfolioState.error.value"
          :portfolio-interest-rate="portfolioInterestRate"
          :form="form"
          :is-active="activeTab === 'portfolio'"
          @upload-file="handlePortfolioFileUpload"
          @run-demo="runSamplePortfolioDemo"
          @update:portfolio-interest-rate="portfolioInterestRate = $event"
        />
      </section>

      <!-- ═══════════════════════════════════════════════════════ -->
      <!-- CONTRACT LOGIC BUILDER TAB                              -->
      <!-- ═══════════════════════════════════════════════════════ -->
      <section v-show="activeTab === 'builder'" class="p-0">
        <ContractBuilderView />
      </section>

      <!-- ═══════════════════════════════════════════════════════ -->
      <!-- ASSUMPTION LIBRARY TAB                                  -->
      <!-- ═══════════════════════════════════════════════════════ -->
      <section v-show="activeTab === 'assumptions'" class="px-6 py-4 h-full">
        <AssumptionLibraryView />
      </section>

      <!-- ═══════════════════════════════════════════════════════ -->
      <!-- UPLOAD TABLE MODAL                                      -->
      <!-- ═══════════════════════════════════════════════════════ -->
      <div v-if="showTableModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
        <div class="card max-w-lg w-full p-6 space-y-4">
          <div class="flex items-center justify-between pb-3 border-b border-white/[0.06]">
            <h3 class="text-sm font-semibold text-white">Upload Mortality Table</h3>
            <button @click="showTableModal = false" class="text-slate-400 hover:text-white text-lg">✕</button>
          </div>

          <div v-if="uploadTableError" class="p-3 card-inset border-rose-500/20 text-rose-400 text-xs">{{ uploadTableError }}</div>

          <div class="space-y-3">
            <div>
              <label class="text-[11px] text-slate-400 font-medium mb-1 block">Table Name (Optional)</label>
              <input type="text" v-model="uploadTableName" placeholder="e.g. 2024 Experience Table" class="input-field" />
            </div>
            <div>
              <label class="text-[11px] text-slate-400 font-medium mb-1 block">Description</label>
              <input type="text" v-model="uploadTableDesc" placeholder="e.g. Corporate insured lives" class="input-field" />
            </div>

            <div
              @dragover.prevent="isTableDragging = true"
              @dragleave.prevent="isTableDragging = false"
              @drop.prevent="handleTableFileDrop"
              :class="['border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition', isTableDragging ? 'border-sky-400 bg-sky-500/5' : 'border-white/[0.1] bg-[#0F172A] hover:border-sky-400/40']"
              @click="tableFileInput?.click()"
              role="button"
              tabindex="0"
            >
              <input type="file" ref="tableFileInput" accept=".csv,.tsv,.txt,.xml,.xtbml" class="hidden" @change="handleTableFileSelect" />
              <div class="flex flex-col items-center space-y-1">
                <svg class="h-6 w-6 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <p class="text-xs text-slate-300">{{ uploadTableFile ? uploadTableFile.name : 'Drop file here or browse' }}</p>
                <p class="text-[10px] text-slate-500 font-mono">CSV (age,qx) or SOA XTbML (XML)</p>
              </div>
            </div>
          </div>

          <div class="flex items-center justify-end space-x-2.5 pt-2">
            <button @click="showTableModal = false" class="btn-secondary">Cancel</button>
            <button @click="submitCustomTable" :disabled="uploadTableLoading" class="btn-primary">
              {{ uploadTableLoading ? 'Uploading...' : 'Upload & Use' }}
            </button>
          </div>
        </div>
      </div>

      <!-- ─── Footer ─── -->
      <footer class="border-t border-white/[0.06] py-5 mt-8">
        <div class="px-6 flex flex-col sm:flex-row items-center justify-between text-[11px] text-slate-600 gap-2">
          <div class="flex items-center space-x-1.5">
            <span class="text-slate-400 font-medium">Actura</span>
            <span>·</span><span>IFRS 17</span><span>·</span><span>Monte Carlo ESG</span><span>·</span><span>Batch Portfolio</span>
          </div>
          <div class="flex items-center space-x-3">
            <router-link to="/terms" class="hover:text-slate-400 transition-colors">Terms of Service</router-link>
            <span>·</span>
            <router-link to="/privacy" class="hover:text-slate-400 transition-colors">Privacy Policy</router-link>
            <span class="ml-2">FastAPI · Vue 3 · ECharts · TailwindCSS</span>
          </div>
        </div>
      </footer>
    </div>
  </div>
</template>
