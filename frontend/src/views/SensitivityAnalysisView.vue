<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  fetchBaseModels,
  fetchSensitivityDefaults,
  runSensitivityAnalysisV2,
} from '../services/actuaryApi'
import BaseChart from '../components/BaseChart.vue'
import {
  Activity,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  Sliders,
  Layers,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  RefreshCw,
  Info,
  SlidersHorizontal,
  Flame,
  Award,
  ChevronRight,
  Sparkles,
} from 'lucide-vue-next'

const router = useRouter()

// State
const loading = ref(false)
const modelsLoading = ref(false)
const error = ref(null)
const baseModels = ref([])
const selectedModelId = ref('default-endowment')
const targetMetric = ref('bel')
const sensitivityResult = ref(null)
const showConfigModal = ref(false)
const activeTableTab = ref('all')

// Configurable Shocks Input State (comma-separated strings for easy input)
const shockInputs = ref({
  mortality: '-20, -10, 0, 10, 20',
  discount_rate: '-200, -100, 0, 100, 200',
  lapse: '-20, -10, 0, 10, 20',
  expense: '-20, -10, 0, 10, 20',
})

const metricLabels = {
  bel: 'Best Estimate Liability (BEL)',
  csm: 'Contractual Service Margin (CSM)',
  profit_loss: 'PV of Underwriting Profit',
}

function parseNumberList(str) {
  if (!str || typeof str !== 'string') return null
  const items = str
    .split(',')
    .map((s) => parseFloat(s.trim()))
    .filter((n) => !isNaN(n))
  return items.length > 0 ? items : null
}

function formatCurrency(val) {
  if (val === undefined || val === null || isNaN(val)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(val)
}

function formatPercent(val, decimals = 2) {
  if (val === undefined || val === null || isNaN(val)) return '—'
  const sign = val > 0 ? '+' : ''
  return `${sign}${Number(val).toFixed(decimals)}%`
}

// Load available models and execute initial analysis
onMounted(async () => {
  await loadBaseModels()
  await runAnalysis()
})

async function loadBaseModels() {
  modelsLoading.value = true
  try {
    const res = await fetchBaseModels()
    baseModels.value = res.data || []
    if (baseModels.value.length > 0 && !baseModels.value.some((m) => m.id === selectedModelId.value)) {
      selectedModelId.value = baseModels.value[0].id
    }
  } catch (err) {
    console.warn('Failed to load base models:', err)
  } finally {
    modelsLoading.value = false
  }
}

async function runAnalysis() {
  loading.value = true
  error.value = null

  try {
    const shocksPayload = {
      mortality_shocks: parseNumberList(shockInputs.value.mortality),
      interest_shocks_bps: parseNumberList(shockInputs.value.discount_rate),
      lapse_shocks: parseNumberList(shockInputs.value.lapse),
      expense_shocks: parseNumberList(shockInputs.value.expense),
    }

    const payload = {
      base_model_id: selectedModelId.value,
      target_metric: targetMetric.value,
      shocks: shocksPayload,
    }

    const res = await runSensitivityAnalysisV2(payload)
    sensitivityResult.value = res.data
    showConfigModal.value = false
  } catch (err) {
    console.error('Sensitivity analysis error:', err)
    error.value = err.response?.data?.detail || err.message || 'Failed to execute sensitivity analysis.'
  } finally {
    loading.value = false
  }
}

function resetShockInputs() {
  shockInputs.value = {
    mortality: '-20, -10, 0, 10, 20',
    discount_rate: '-200, -100, 0, 100, 200',
    lapse: '-20, -10, 0, 10, 20',
    expense: '-20, -10, 0, 10, 20',
  }
}

function applyPreset(preset) {
  if (preset === 'standard') {
    resetShockInputs()
  } else if (preset === 'mild') {
    shockInputs.value = {
      mortality: '-10, 0, 10',
      discount_rate: '-100, 0, 100',
      lapse: '-10, 0, 10',
      expense: '-10, 0, 10',
    }
  } else if (preset === 'severe') {
    shockInputs.value = {
      mortality: '-30, -15, 0, 15, 30',
      discount_rate: '-300, -150, 0, 150, 300',
      lapse: '-40, -20, 0, 20, 40',
      expense: '-30, -15, 0, 15, 30',
    }
  }
}

// Current active base model details
const currentModel = computed(() => {
  return baseModels.value.find((m) => m.id === selectedModelId.value) || null
})

// Top driver (#1)
const topDriver = computed(() => {
  if (!sensitivityResult.value?.drivers?.length) return null
  return sensitivityResult.value.drivers[0]
})

// Filtered table points
const filteredGridPoints = computed(() => {
  if (!sensitivityResult.value?.grid_points) return []
  if (activeTableTab.value === 'all') return sensitivityResult.value.grid_points
  return sensitivityResult.value.grid_points.filter((pt) => pt.variable === activeTableTab.value)
})

// Clean Horizontal Tornado / Impact Bar Chart
const chartOption = computed(() => {
  if (!sensitivityResult.value?.drivers || sensitivityResult.value.drivers.length === 0) return null

  const drivers = [...sensitivityResult.value.drivers].reverse()
  const baseVal = sensitivityResult.value.base_metric_value || 0
  const yCategories = drivers.map((d) => d.variable_label)

  // Min and Max deltas from base
  const minDeltas = drivers.map((d) => Math.round(d.min_metric - baseVal))
  const maxDeltas = drivers.map((d) => Math.round(d.max_metric - baseVal))

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: '#0f172a',
      borderColor: '#334155',
      textStyle: { color: '#f8fafc', fontSize: 12 },
      formatter: (params) => {
        const idx = params[0].dataIndex
        const d = drivers[idx]
        return `
          <div class="space-y-1 py-0.5">
            <div class="font-bold text-sky-400">${d.variable_label} (Rank #${d.rank})</div>
            <div class="text-slate-300">Baseline ${metricLabels[targetMetric.value]}: <span class="font-semibold text-white">${formatCurrency(baseVal)}</span></div>
            <div class="text-slate-300">Lowest Metric: <span class="font-semibold text-emerald-400">${formatCurrency(d.min_metric)}</span></div>
            <div class="text-slate-300">Highest Metric: <span class="font-semibold text-rose-400">${formatCurrency(d.max_metric)}</span></div>
            <div class="text-slate-300">Absolute Swing: <span class="font-bold text-amber-400">${formatCurrency(d.swing)}</span> (${d.swing_pct > 0 ? '+' : ''}${d.swing_pct}%)</div>
            <div class="text-[11px] text-slate-400">Most Adverse Shock: <span class="text-rose-300">${d.most_adverse_shock}</span></div>
          </div>
        `
      },
    },
    grid: {
      left: '3%',
      right: '6%',
      bottom: '10%',
      top: '12%',
      containLabel: true,
    },
    xAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#334155' } },
      splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } },
      axisLabel: {
        color: '#94a3b8',
        fontSize: 11,
        formatter: (val) => {
          if (Math.abs(val) >= 1000000) return `${(val / 1000000).toFixed(1)}M`
          if (Math.abs(val) >= 1000) return `${(val / 1000).toFixed(0)}k`
          return val
        },
      },
    },
    yAxis: {
      type: 'category',
      data: yCategories,
      axisLine: { lineStyle: { color: '#334155' } },
      axisTick: { show: false },
      axisLabel: { color: '#e2e8f0', fontSize: 12, fontWeight: 500 },
    },
    series: [
      {
        name: 'Downside Deviation',
        type: 'bar',
        stack: 'total',
        barWidth: 18,
        data: minDeltas.map((val) => ({
          value: val,
          itemStyle: {
            color: val < 0 ? '#10b981' : '#f43f5e',
            borderRadius: [4, 0, 0, 4],
          },
        })),
      },
      {
        name: 'Upside Deviation',
        type: 'bar',
        stack: 'total',
        barWidth: 18,
        data: maxDeltas.map((val) => ({
          value: val,
          itemStyle: {
            color: val > 0 ? '#f43f5e' : '#10b981',
            borderRadius: [0, 4, 4, 0],
          },
        })),
      },
    ],
  }
})
</script>

<template>
  <div class="min-h-screen bg-slate-950 text-slate-100 p-4 sm:p-6 lg:p-8 space-y-6">
    <!-- 1. HEADER & CONTROLS -->
    <header class="card p-6 bg-gradient-to-r from-slate-900 via-slate-900/90 to-slate-950 border-slate-800">
      <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div class="flex items-center space-x-3">
          <button
            @click="router.push('/')"
            class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
            title="Return to Dashboard"
          >
            <ArrowLeft class="w-5 h-5" />
          </button>
          <div>
            <div class="flex items-center space-x-2.5">
              <h1 class="text-2xl font-bold text-white tracking-tight">Sensitivity Analysis</h1>
              <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
                First-Class Engine
              </span>
            </div>
            <p class="text-xs text-slate-400 mt-1">
              Identify which actuarial assumptions have the greatest impact on valuation results
            </p>
          </div>
        </div>

        <!-- Action Controls -->
        <div class="flex flex-wrap items-center gap-3">
          <!-- Model Selector -->
          <div class="flex items-center space-x-2 bg-slate-800/80 px-3 py-1.5 rounded-lg border border-slate-700">
            <span class="text-xs text-slate-400">Base Model:</span>
            <select
              v-model="selectedModelId"
              @change="runAnalysis"
              class="bg-transparent text-xs text-white font-medium focus:outline-none cursor-pointer"
            >
              <option v-for="m in baseModels" :key="m.id" :value="m.id" class="bg-slate-900 text-white">
                {{ m.name }}
              </option>
            </select>
          </div>

          <!-- Configure Shocks Button -->
          <button
            @click="showConfigModal = true"
            class="btn-secondary text-xs px-3.5 py-2 rounded-lg flex items-center space-x-1.5 border border-slate-700 hover:border-slate-600"
          >
            <SlidersHorizontal class="w-3.5 h-3.5 text-sky-400" />
            <span>Configure Shocks</span>
          </button>

          <!-- Run Button -->
          <button
            @click="runAnalysis"
            :disabled="loading"
            class="btn-primary text-xs px-4 py-2 rounded-lg flex items-center space-x-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
            <span>{{ loading ? 'Running Shocks...' : 'Recalculate' }}</span>
          </button>
        </div>
      </div>

      <!-- Target Metric Switcher Pills -->
      <div class="mt-5 pt-4 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center space-x-2">
          <span class="text-xs font-medium text-slate-400">Evaluate Metric:</span>
          <div class="inline-flex rounded-lg bg-slate-800/90 p-0.5 border border-slate-700">
            <button
              @click="targetMetric = 'bel'; runAnalysis()"
              :class="targetMetric === 'bel' ? 'bg-sky-600 text-white font-semibold shadow-sm' : 'text-slate-400 hover:text-white'"
              class="px-3 py-1 text-xs rounded-md transition"
            >
              Best Estimate Liability (BEL)
            </button>
            <button
              @click="targetMetric = 'csm'; runAnalysis()"
              :class="targetMetric === 'csm' ? 'bg-sky-600 text-white font-semibold shadow-sm' : 'text-slate-400 hover:text-white'"
              class="px-3 py-1 text-xs rounded-md transition"
            >
              Contractual Service Margin (CSM)
            </button>
            <button
              @click="targetMetric = 'profit_loss'; runAnalysis()"
              :class="targetMetric === 'profit_loss' ? 'bg-sky-600 text-white font-semibold shadow-sm' : 'text-slate-400 hover:text-white'"
              class="px-3 py-1 text-xs rounded-md transition"
            >
              Profit / Loss (NPV)
            </button>
          </div>
        </div>

        <div v-if="sensitivityResult" class="text-xs text-slate-400 flex items-center space-x-2">
          <span class="inline-block w-2 h-2 rounded-full bg-emerald-400"></span>
          <span>Analysis ID: <code class="text-slate-300 font-mono">{{ sensitivityResult.analysis_id }}</code></span>
        </div>
      </div>
    </header>

    <!-- Error Banner -->
    <div
      v-if="error"
      class="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center justify-between"
    >
      <div class="flex items-center space-x-2.5">
        <AlertTriangle class="w-4 h-4 text-rose-400 flex-shrink-0" />
        <span>{{ error }}</span>
      </div>
      <button @click="error = null" class="text-rose-400 hover:text-white text-xs underline ml-4">
        Dismiss
      </button>
    </div>

    <!-- 2. TOP VALUATION SUMMARY METRIC CARDS -->
    <div v-if="sensitivityResult" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Baseline Value -->
      <div class="card p-4 border-slate-800/80 bg-slate-900/60">
        <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
          <span>Unstressed Baseline</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-300">Base</span>
        </div>
        <div class="text-xl font-bold text-white">
          {{ formatCurrency(sensitivityResult.base_metric_value) }}
        </div>
        <p class="text-[11px] text-slate-400 mt-1">
          {{ metricLabels[targetMetric] }}
        </p>
      </div>

      <!-- Key Valuation Driver (#1) -->
      <div class="card p-4 border-amber-500/30 bg-gradient-to-b from-amber-500/10 to-slate-900">
        <div class="flex items-center justify-between text-xs text-amber-300/90 mb-1">
          <div class="flex items-center space-x-1">
            <Flame class="w-3.5 h-3.5 text-amber-400" />
            <span class="font-semibold uppercase tracking-wider text-[10px]">#1 Top Driver</span>
          </div>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
            Max Impact
          </span>
        </div>
        <div class="text-xl font-bold text-white flex items-center justify-between">
          <span>{{ topDriver?.variable_label || '—' }}</span>
          <span class="text-sm font-semibold text-amber-400">{{ formatCurrency(topDriver?.swing) }}</span>
        </div>
        <p class="text-[11px] text-amber-200/70 mt-1">
          Causes up to {{ topDriver?.swing_pct > 0 ? '+' : '' }}{{ topDriver?.swing_pct }}% valuation swing
        </p>
      </div>

      <!-- Most Adverse Condition -->
      <div class="card p-4 border-slate-800/80 bg-slate-900/60">
        <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
          <span>Worst-Case Shock</span>
          <TrendingDown class="w-3.5 h-3.5 text-rose-400" />
        </div>
        <div class="text-xl font-bold text-rose-400">
          {{ topDriver?.most_adverse_shock || '—' }}
        </div>
        <p class="text-[11px] text-slate-400 mt-1">
          Peak liability shift under {{ topDriver?.variable_label }}
        </p>
      </div>

      <!-- Scenarios Evaluated -->
      <div class="card p-4 border-slate-800/80 bg-slate-900/60">
        <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
          <span>Sensitivity Grid</span>
          <Layers class="w-3.5 h-3.5 text-sky-400" />
        </div>
        <div class="text-xl font-bold text-white">
          {{ sensitivityResult.grid_points.length }} Points
        </div>
        <p class="text-[11px] text-slate-400 mt-1">
          Across 4 risk factors (reproducible &amp; persisted)
        </p>
      </div>
    </div>

    <!-- 3. MAIN DASHBOARD CONTENT: TOP DRIVERS + TORNADO CHART -->
    <div v-if="sensitivityResult" class="grid grid-cols-1 lg:grid-cols-12 gap-6">
      <!-- Left Column: Top Valuation Drivers Ranked List (5 cols) -->
      <div class="lg:col-span-5 space-y-4">
        <div class="card p-5 border-slate-800 space-y-4">
          <div class="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <h2 class="text-sm font-semibold text-white flex items-center space-x-2">
                <Award class="w-4 h-4 text-amber-400" />
                <span>Top Valuation Drivers</span>
              </h2>
              <p class="text-xs text-slate-400">Ranked by absolute valuation swing magnitude</p>
            </div>
            <span class="text-[11px] text-slate-400">Rank #1 to #4</span>
          </div>

          <div class="space-y-3">
            <div
              v-for="driver in sensitivityResult.drivers"
              :key="driver.variable"
              class="p-3.5 rounded-xl border transition"
              :class="
                driver.rank === 1
                  ? 'bg-amber-500/[0.07] border-amber-500/30'
                  : 'bg-slate-900/50 border-slate-800 hover:border-slate-700'
              "
            >
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2.5">
                  <span
                    class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                    :class="
                      driver.rank === 1
                        ? 'bg-amber-500 text-slate-950'
                        : 'bg-slate-800 text-slate-300'
                    "
                  >
                    {{ driver.rank }}
                  </span>
                  <div>
                    <h3 class="text-xs font-semibold text-white">{{ driver.variable_label }}</h3>
                    <p class="text-[10px] text-slate-400">Adverse shock: <span class="text-rose-400">{{ driver.most_adverse_shock }}</span></p>
                  </div>
                </div>

                <div class="text-right">
                  <div class="text-xs font-bold text-white">{{ formatCurrency(driver.swing) }}</div>
                  <div class="text-[10px] text-slate-400">{{ driver.swing_pct > 0 ? '+' : '' }}{{ driver.swing_pct }}% spread</div>
                </div>
              </div>

              <!-- Relative Impact Bar -->
              <div class="mt-2.5 w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  :class="driver.rank === 1 ? 'bg-amber-400' : 'bg-sky-400'"
                  :style="{
                    width: `${Math.min(100, Math.max(8, (driver.swing / (topDriver?.swing || 1)) * 100))}%`,
                  }"
                ></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: Sensitivity Chart (7 cols) -->
      <div class="lg:col-span-7">
        <div class="card p-5 border-slate-800 h-full flex flex-col justify-between">
          <div class="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <h2 class="text-sm font-semibold text-white flex items-center space-x-2">
                <BarChart3 class="w-4 h-4 text-sky-400" />
                <span>Sensitivity Impact &amp; Deviations</span>
              </h2>
              <p class="text-xs text-slate-400">
                Absolute shift relative to baseline {{ metricLabels[targetMetric] }}
              </p>
            </div>
            <span class="text-[11px] text-slate-400">Centered at Baseline ($0)</span>
          </div>

          <div class="h-[280px] w-full mt-2">
            <BaseChart :option="chartOption" :loading="loading" />
          </div>

          <div class="pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
            <div class="flex items-center space-x-4">
              <span class="flex items-center space-x-1.5">
                <span class="w-2.5 h-2.5 rounded-sm bg-emerald-500"></span>
                <span>Favorable Deviation</span>
              </span>
              <span class="flex items-center space-x-1.5">
                <span class="w-2.5 h-2.5 rounded-sm bg-rose-500"></span>
                <span>Adverse Shift</span>
              </span>
            </div>
            <span>Base Model: {{ sensitivityResult.base_model_name }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 4. DETAILED SENSITIVITY TABLE -->
    <div v-if="sensitivityResult" class="card p-5 border-slate-800 space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-slate-800">
        <div>
          <h2 class="text-sm font-semibold text-white">Full Sensitivity Shock Results</h2>
          <p class="text-xs text-slate-400">Individual assumption evaluation points and resulting changes</p>
        </div>

        <!-- Filter Tabs -->
        <div class="inline-flex rounded-lg bg-slate-900 p-0.5 border border-slate-800 text-xs">
          <button
            @click="activeTableTab = 'all'"
            :class="activeTableTab === 'all' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            All ({{ sensitivityResult.grid_points.length }})
          </button>
          <button
            @click="activeTableTab = 'mortality'"
            :class="activeTableTab === 'mortality' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            Mortality
          </button>
          <button
            @click="activeTableTab = 'discount_rate'"
            :class="activeTableTab === 'discount_rate' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            Discount Rate
          </button>
          <button
            @click="activeTableTab = 'lapse'"
            :class="activeTableTab === 'lapse' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            Lapse
          </button>
          <button
            @click="activeTableTab = 'expense'"
            :class="activeTableTab === 'expense' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            Expense
          </button>
        </div>
      </div>

      <!-- Table -->
      <div class="overflow-x-auto rounded-lg border border-slate-800/80">
        <table class="w-full text-left border-collapse text-xs">
          <thead class="bg-slate-900/90 text-slate-400 font-medium border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">Assumption</th>
              <th class="py-2.5 px-3">Shock Condition</th>
              <th class="py-2.5 px-3 text-right">Resulting Metric</th>
              <th class="py-2.5 px-3 text-right">Absolute Change (&Delta;)</th>
              <th class="py-2.5 px-3 text-right">Percentage Change (%&Delta;)</th>
              <th class="py-2.5 px-3 text-right text-slate-400">BEL</th>
              <th class="py-2.5 px-3 text-right text-slate-400">CSM</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60">
            <tr
              v-for="(point, idx) in filteredGridPoints"
              :key="idx"
              :class="point.shock_label === 'Base' ? 'bg-slate-900/80 font-semibold' : 'hover:bg-slate-900/40'"
              class="transition"
            >
              <td class="py-2.5 px-3 flex items-center space-x-2">
                <span
                  class="w-2 h-2 rounded-full"
                  :class="{
                    'bg-rose-400': point.variable === 'mortality',
                    'bg-sky-400': point.variable === 'discount_rate',
                    'bg-amber-400': point.variable === 'lapse',
                    'bg-purple-400': point.variable === 'expense',
                  }"
                ></span>
                <span class="text-white">{{ point.variable_label }}</span>
              </td>
              <td class="py-2.5 px-3">
                <span
                  class="px-2 py-0.5 rounded text-[11px] font-mono"
                  :class="
                    point.shock_label === 'Base'
                      ? 'bg-slate-800 text-slate-300'
                      : 'bg-slate-800/60 text-white'
                  "
                >
                  {{ point.shock_label }}
                </span>
              </td>
              <td class="py-2.5 px-3 text-right font-medium text-white">
                {{ formatCurrency(point.resulting_metric) }}
              </td>
              <td class="py-2.5 px-3 text-right font-mono">
                <span
                  :class="{
                    'text-rose-400': point.absolute_change > 0 && targetMetric === 'bel',
                    'text-emerald-400': point.absolute_change < 0 && targetMetric === 'bel',
                    'text-emerald-400': point.absolute_change > 0 && targetMetric !== 'bel',
                    'text-rose-400': point.absolute_change < 0 && targetMetric !== 'bel',
                    'text-slate-400': point.absolute_change === 0,
                  }"
                >
                  {{ point.absolute_change > 0 ? '+' : '' }}{{ formatCurrency(point.absolute_change) }}
                </span>
              </td>
              <td class="py-2.5 px-3 text-right">
                <span
                  class="px-1.5 py-0.5 rounded text-[11px] font-medium"
                  :class="{
                    'bg-rose-500/10 text-rose-300 border border-rose-500/20':
                      (point.percentage_change > 0 && targetMetric === 'bel') ||
                      (point.percentage_change < 0 && targetMetric !== 'bel'),
                    'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20':
                      (point.percentage_change < 0 && targetMetric === 'bel') ||
                      (point.percentage_change > 0 && targetMetric !== 'bel'),
                    'bg-slate-800 text-slate-400': point.percentage_change === 0,
                  }"
                >
                  {{ formatPercent(point.percentage_change) }}
                </span>
              </td>
              <td class="py-2.5 px-3 text-right text-slate-400">
                {{ formatCurrency(point.bel) }}
              </td>
              <td class="py-2.5 px-3 text-right text-slate-400">
                {{ formatCurrency(point.csm) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 5. CONFIGURABLE SHOCKS MODAL -->
    <div
      v-if="showConfigModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4"
    >
      <div class="card p-6 max-w-lg w-full bg-slate-900 border-slate-800 shadow-2xl space-y-5">
        <div class="flex items-center justify-between pb-3 border-b border-slate-800">
          <div class="flex items-center space-x-2">
            <Sliders class="w-5 h-5 text-sky-400" />
            <h3 class="text-base font-bold text-white">Configure Sensitivity Shocks</h3>
          </div>
          <button
            @click="showConfigModal = false"
            class="text-slate-400 hover:text-white text-xs font-semibold p-1"
          >
            ✕
          </button>
        </div>

        <!-- Presets Bar -->
        <div class="space-y-1">
          <span class="text-xs text-slate-400 font-medium">Quick Presets:</span>
          <div class="flex items-center space-x-2">
            <button
              @click="applyPreset('standard')"
              class="px-2.5 py-1 rounded text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            >
              Standard (5-Point)
            </button>
            <button
              @click="applyPreset('mild')"
              class="px-2.5 py-1 rounded text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            >
              Mild (3-Point)
            </button>
            <button
              @click="applyPreset('severe')"
              class="px-2.5 py-1 rounded text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            >
              Severe Stress
            </button>
          </div>
        </div>

        <!-- Inputs Form -->
        <div class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">
              Mortality Shocks (% relative shift, e.g. -20, -10, 0, 10, 20)
            </label>
            <input
              v-model="shockInputs.mortality"
              type="text"
              class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white font-mono focus:border-sky-500 focus:outline-none"
            />
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">
              Discount Rate Shocks (bps shift, e.g. -200, -100, 0, 100, 200)
            </label>
            <input
              v-model="shockInputs.discount_rate"
              type="text"
              class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white font-mono focus:border-sky-500 focus:outline-none"
            />
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">
              Lapse Shocks (% relative shift, e.g. -20, -10, 0, 10, 20)
            </label>
            <input
              v-model="shockInputs.lapse"
              type="text"
              class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white font-mono focus:border-sky-500 focus:outline-none"
            />
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">
              Expense Shocks (% relative shift, e.g. -20, -10, 0, 10, 20)
            </label>
            <input
              v-model="shockInputs.expense"
              type="text"
              class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white font-mono focus:border-sky-500 focus:outline-none"
            />
          </div>
        </div>

        <!-- Footer Actions -->
        <div class="pt-3 border-t border-slate-800 flex items-center justify-between">
          <button
            @click="resetShockInputs"
            class="text-xs text-slate-400 hover:text-white underline"
          >
            Reset Defaults
          </button>
          <div class="flex items-center space-x-2">
            <button
              @click="showConfigModal = false"
              class="btn-secondary text-xs px-3 py-1.5 rounded-lg"
            >
              Cancel
            </button>
            <button
              @click="runAnalysis"
              class="btn-primary text-xs px-4 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold"
            >
              Apply &amp; Recalculate
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
