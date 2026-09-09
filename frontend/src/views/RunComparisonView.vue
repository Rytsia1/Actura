<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { fetchComparableRuns, compareRuns, downloadValuationExport } from '../services/actuaryApi'
import BaseChart from '../components/BaseChart.vue'
import {
  ArrowLeft,
  ArrowRightLeft,
  Sparkles,
  AlertCircle,
  CheckCircle2,
  Sliders,
  Layers,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Info,
  Calendar,
  Clock,
  ShieldCheck,
  Tag,
  Scale,
} from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()

// State
const loading = ref(false)
const runsLoading = ref(false)
const error = ref(null)
const comparableRuns = ref([])
const runAId = ref('')
const runBId = ref('')
const comparisonData = ref(null)
const activeMetricCategory = ref('all')

function formatCurrency(val, unit = '$') {
  if (val === undefined || val === null || isNaN(val)) return '—'
  if (unit === '') return Number(val).toFixed(4)
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

function formatDate(timestamp) {
  if (!timestamp) return '—'
  return new Date(timestamp * 1000).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shortenId(id) {
  if (!id) return '—'
  return id.length > 12 ? `${id.substring(0, 8)}...` : id
}

onMounted(async () => {
  await loadRuns()
  // Check URL query parameters for initial run IDs
  if (route.query.runA) runAId.value = route.query.runA
  if (route.query.runB) runBId.value = route.query.runB

  // If IDs not in query, auto-pick first two comparable runs
  if (!runAId.value && comparableRuns.value.length > 0) {
    runAId.value = comparableRuns.value[0].job_id
  }
  if (!runBId.value && comparableRuns.value.length > 1) {
    runBId.value = comparableRuns.value[1].job_id
  } else if (!runBId.value && comparableRuns.value.length > 0) {
    runBId.value = comparableRuns.value[0].job_id
  }

  if (runAId.value && runBId.value) {
    await executeComparison()
  }
})

async function loadRuns() {
  runsLoading.value = true
  try {
    const res = await fetchComparableRuns({ limit: 100 })
    comparableRuns.value = Array.isArray(res) ? res : (res?.data || [])
  } catch (err) {
    console.warn('Failed to load comparable runs:', err)
  } finally {
    runsLoading.value = false
  }
}

async function executeComparison() {
  if (!runAId.value || !runBId.value) return
  loading.value = true
  error.value = null

  try {
    const res = await compareRuns({
      run_a_id: runAId.value,
      run_b_id: runBId.value,
    })
    comparisonData.value = res?.data || res
  } catch (err) {
    console.error('Run comparison failed:', err)
    error.value = err.response?.data?.detail || err.message || 'Failed to compare runs.'
  } finally {
    loading.value = false
  }
}

function swapRuns() {
  const temp = runAId.value
  runAId.value = runBId.value
  runBId.value = temp
  executeComparison()
}

// Filtered metrics list
const filteredMetrics = computed(() => {
  if (!comparisonData.value?.metrics) return []
  if (activeMetricCategory.value === 'all') return comparisonData.value.metrics
  return comparisonData.value.metrics.filter(
    (m) => m.category === activeMetricCategory.value
  )
})

// Visual comparison bar chart (Key Metrics: BEL, Premiums, Benefits, Expenses)
const chartOption = computed(() => {
  if (!comparisonData.value?.metrics) return null

  // Pick up to 5 prominent financial metrics that exist in both runs
  const targetKeys = ['bel', 'annual_gross_premium', 'pv_premiums', 'pv_benefits', 'pv_expenses', 'profit_loss']
  const candidateMetrics = comparisonData.value.metrics.filter(
    (m) => targetKeys.includes(m.metric_key) && (m.value_a !== null || m.value_b !== null)
  )

  if (candidateMetrics.length === 0) return null

  const categories = candidateMetrics.map((m) => m.metric_label)
  const dataA = candidateMetrics.map((m) => m.value_a || 0)
  const dataB = candidateMetrics.map((m) => m.value_b || 0)

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
        const m = candidateMetrics[idx]
        return `
          <div class="space-y-1 py-0.5">
            <div class="font-bold text-white">${m.metric_label}</div>
            <div class="text-sky-400">Run A: <span class="font-semibold text-white">${formatCurrency(m.value_a)}</span></div>
            <div class="text-indigo-400">Run B: <span class="font-semibold text-white">${formatCurrency(m.value_b)}</span></div>
            <div class="text-slate-300">Delta: <span class="font-bold ${m.absolute_delta > 0 ? 'text-rose-400' : 'text-emerald-400'}">${m.absolute_delta > 0 ? '+' : ''}${formatCurrency(m.absolute_delta)} (${formatPercent(m.percentage_delta)})</span></div>
          </div>
        `
      },
    },
    legend: {
      data: ['Run A (Baseline)', 'Run B (Comparison)'],
      textStyle: { color: '#94a3b8', fontSize: 12 },
      top: '0%',
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '10%',
      top: '14%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8', fontSize: 11, interval: 0, rotate: categories.length > 3 ? 15 : 0 },
    },
    yAxis: {
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
    series: [
      {
        name: 'Run A (Baseline)',
        type: 'bar',
        barWidth: 20,
        itemStyle: { color: '#0284c7', borderRadius: [4, 4, 0, 0] },
        data: dataA,
      },
      {
        name: 'Run B (Comparison)',
        type: 'bar',
        barWidth: 20,
        itemStyle: { color: '#6366f1', borderRadius: [4, 4, 0, 0] },
        data: dataB,
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
            @click="router.push('/history')"
            class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
            title="Back to Run History"
          >
            <ArrowLeft class="w-5 h-5" />
          </button>
          <div>
            <div class="flex items-center space-x-2.5">
              <Scale class="w-6 h-6 text-sky-400" />
              <h1 class="text-2xl font-bold text-white tracking-tight">Run Comparison</h1>
              <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Diff &amp; Explanation
              </span>
            </div>
            <p class="text-xs text-slate-400 mt-1">
              Select any two valuation runs to compare metrics and explain configuration differences
            </p>
          </div>
        </div>

        <div class="flex items-center space-x-3">
          <button
            @click="swapRuns"
            :disabled="loading"
            class="btn-secondary text-xs px-3.5 py-2 rounded-lg flex items-center space-x-1.5 border border-slate-700 hover:border-slate-600"
            title="Swap Run A and Run B"
          >
            <ArrowRightLeft class="w-3.5 h-3.5 text-sky-400" />
            <span>Swap Runs</span>
          </button>
          <button
            @click="executeComparison"
            :disabled="loading"
            class="btn-primary text-xs px-4 py-2 rounded-lg flex items-center space-x-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
            <span>{{ loading ? 'Comparing...' : 'Recalculate Diff' }}</span>
          </button>
        </div>
      </div>

      <!-- RUN SELECTORS DUAL CARDS -->
      <div class="grid grid-cols-1 md:grid-cols-12 gap-4 mt-6 pt-5 border-t border-slate-800/80 items-center">
        <!-- Run A Selector (5 cols) -->
        <div class="md:col-span-5 p-4 rounded-xl border border-sky-500/30 bg-sky-950/20 space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="font-bold text-sky-400 flex items-center space-x-1.5">
              <span class="w-2 h-2 rounded-full bg-sky-400"></span>
              <span>RUN A (Baseline)</span>
            </span>
            <div v-if="comparisonData?.run_a" class="flex items-center space-x-2">
              <span class="text-slate-400 text-[11px]">{{ formatDate(comparisonData.run_a.created_at) }}</span>
              <button
                @click="downloadValuationExport(runAId, 'xlsx')"
                class="px-2 py-0.5 text-[10px] rounded bg-sky-500/20 text-sky-300 hover:bg-sky-500/30 transition flex items-center gap-1 font-medium"
                title="Export Run A (Excel)"
              >
                📊 Export
              </button>
            </div>
          </div>
          <select
            v-model="runAId"
            @change="executeComparison"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-medium focus:outline-none focus:border-sky-500"
          >
            <option v-for="r in comparableRuns" :key="r.job_id" :value="r.job_id">
              {{ r.name }} — {{ r.valuation_type }} ({{ shortenId(r.job_id) }}) {{ r.bel ? `[BEL: ${formatCurrency(r.bel)}]` : '' }}
            </option>
          </select>
          <div v-if="comparisonData?.run_a" class="flex items-center space-x-2 text-[11px] text-slate-400">
            <span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono text-[10px]">{{ comparisonData.run_a.valuation_type }}</span>
            <span>Scenario: <strong class="text-white">{{ comparisonData.run_a.scenario_name }}</strong></span>
          </div>
        </div>

        <!-- VS Divider (2 cols) -->
        <div class="md:col-span-2 flex flex-col items-center justify-center py-2">
          <div class="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center font-bold text-xs text-slate-300">
            VS
          </div>
          <span class="text-[10px] text-slate-500 mt-1">Delta = B - A</span>
        </div>

        <!-- Run B Selector (5 cols) -->
        <div class="md:col-span-5 p-4 rounded-xl border border-indigo-500/30 bg-indigo-950/20 space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="font-bold text-indigo-400 flex items-center space-x-1.5">
              <span class="w-2 h-2 rounded-full bg-indigo-400"></span>
              <span>RUN B (Comparison)</span>
            </span>
            <div v-if="comparisonData?.run_b" class="flex items-center space-x-2">
              <span class="text-slate-400 text-[11px]">{{ formatDate(comparisonData.run_b.created_at) }}</span>
              <button
                @click="downloadValuationExport(runBId, 'xlsx')"
                class="px-2 py-0.5 text-[10px] rounded bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30 transition flex items-center gap-1 font-medium"
                title="Export Run B (Excel)"
              >
                📊 Export
              </button>
            </div>
          </div>
          <select
            v-model="runBId"
            @change="executeComparison"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-medium focus:outline-none focus:border-indigo-500"
          >
            <option v-for="r in comparableRuns" :key="r.job_id" :value="r.job_id">
              {{ r.name }} — {{ r.valuation_type }} ({{ shortenId(r.job_id) }}) {{ r.bel ? `[BEL: ${formatCurrency(r.bel)}]` : '' }}
            </option>
          </select>
          <div v-if="comparisonData?.run_b" class="flex items-center space-x-2 text-[11px] text-slate-400">
            <span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono text-[10px]">{{ comparisonData.run_b.valuation_type }}</span>
            <span>Scenario: <strong class="text-white">{{ comparisonData.run_b.scenario_name }}</strong></span>
          </div>
        </div>
      </div>
    </header>

    <!-- Error Banner -->
    <div
      v-if="error"
      class="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center justify-between"
    >
      <div class="flex items-center space-x-2.5">
        <AlertCircle class="w-4 h-4 text-rose-400 flex-shrink-0" />
        <span>{{ error }}</span>
      </div>
      <button @click="error = null" class="text-rose-400 hover:text-white text-xs underline ml-4">
        Dismiss
      </button>
    </div>

    <!-- 2. AUTOMATED EXPLANATION SUMMARY BANNER -->
    <div
      v-if="comparisonData"
      class="p-5 rounded-xl border border-sky-500/30 bg-gradient-to-r from-sky-950/40 via-slate-900 to-indigo-950/40 shadow-lg"
    >
      <div class="flex items-start space-x-3.5">
        <div class="p-2 rounded-lg bg-sky-500/10 border border-sky-500/20 text-sky-400 mt-0.5">
          <Sparkles class="w-5 h-5" />
        </div>
        <div class="space-y-1">
          <div class="flex items-center space-x-2">
            <h2 class="text-sm font-bold text-white uppercase tracking-wider text-[11px]">
              Valuation Difference Insight
            </h2>
            <span
              v-if="comparisonData.changed_elements.length > 0"
              class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30"
            >
              {{ comparisonData.changed_elements.length }} Configuration Changes Detected
            </span>
            <span
              v-else
              class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
            >
              Identical Configurations
            </span>
          </div>
          <p class="text-base font-semibold text-sky-100">
            {{ comparisonData.summary_explanation }}
          </p>
          <div v-if="comparisonData.changed_elements.length > 0" class="flex flex-wrap items-center gap-1.5 pt-1">
            <span class="text-xs text-slate-400">Modified inputs:</span>
            <span
              v-for="elem in comparisonData.changed_elements"
              :key="elem"
              class="px-2 py-0.5 rounded bg-slate-800 text-white font-medium text-xs border border-slate-700"
            >
              {{ elem }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. CONFIGURATION-LEVEL COMPARISON TABLE -->
    <div v-if="comparisonData" class="card p-5 border-slate-800 space-y-4">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <div>
          <h2 class="text-sm font-semibold text-white flex items-center space-x-2">
            <Sliders class="w-4 h-4 text-sky-400" />
            <span>Configuration &amp; Assumption Differences</span>
          </h2>
          <p class="text-xs text-slate-400">
            Compare model versions, actuarial assumptions, and simulation parameters
          </p>
        </div>
        <span class="text-xs text-slate-400">
          {{ comparisonData.changed_elements.length }} differences
        </span>
      </div>

      <div class="overflow-x-auto rounded-lg border border-slate-800/80">
        <table class="w-full text-left border-collapse text-xs">
          <thead class="bg-slate-900/90 text-slate-400 font-medium border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">Configuration Element</th>
              <th class="py-2.5 px-3">Run A (Baseline)</th>
              <th class="py-2.5 px-3">Run B (Comparison)</th>
              <th class="py-2.5 px-3 text-right">Change Status</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60">
            <tr
              v-for="item in comparisonData.configurations"
              :key="item.element_key"
              :class="item.has_changed ? 'bg-amber-500/[0.04]' : 'hover:bg-slate-900/40'"
              class="transition"
            >
              <td class="py-2.5 px-3 font-medium text-white flex items-center space-x-2">
                <span
                  class="w-2 h-2 rounded-full"
                  :class="item.has_changed ? 'bg-amber-400' : 'bg-slate-600'"
                ></span>
                <span>{{ item.label }}</span>
              </td>
              <td class="py-2.5 px-3 text-slate-300 font-mono">
                {{ item.value_a }}
              </td>
              <td class="py-2.5 px-3 text-slate-300 font-mono">
                {{ item.value_b }}
              </td>
              <td class="py-2.5 px-3 text-right">
                <span
                  v-if="item.has_changed"
                  class="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30"
                >
                  {{ item.change_summary }}
                </span>
                <span
                  v-else
                  class="px-2 py-0.5 rounded text-[11px] text-slate-500 font-medium bg-slate-800/60"
                >
                  Identical
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 4. VISUAL METRIC COMPARISON CHART -->
    <div v-if="comparisonData && chartOption" class="card p-5 border-slate-800 space-y-3">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <div>
          <h2 class="text-sm font-semibold text-white">Financial Impact Visualization</h2>
          <p class="text-xs text-slate-400">Direct side-by-side comparison of key valuation metrics</p>
        </div>
      </div>
      <div class="h-[280px] w-full">
        <BaseChart :option="chartOption" :loading="loading" />
      </div>
    </div>

    <!-- 5. VALUATION METRICS COMPARISON TABLE -->
    <div v-if="comparisonData" class="card p-5 border-slate-800 space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-slate-800">
        <div>
          <h2 class="text-sm font-semibold text-white">Full Valuation Metrics Comparison</h2>
          <p class="text-xs text-slate-400">Detailed line-by-line delta analysis across all valuation metrics</p>
        </div>

        <!-- Category Filters -->
        <div class="inline-flex rounded-lg bg-slate-900 p-0.5 border border-slate-800 text-xs">
          <button
            @click="activeMetricCategory = 'all'"
            :class="activeMetricCategory === 'all' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            All Metrics
          </button>
          <button
            @click="activeMetricCategory = 'liability'"
            :class="activeMetricCategory === 'liability' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            Liabilities
          </button>
          <button
            @click="activeMetricCategory = 'cash_flow'"
            :class="activeMetricCategory === 'cash_flow' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            Cash Flows
          </button>
          <button
            @click="activeMetricCategory = 'risk'"
            :class="activeMetricCategory === 'risk' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            Risk
          </button>
          <button
            @click="activeMetricCategory = 'profitability'"
            :class="activeMetricCategory === 'profitability' ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'"
            class="px-2.5 py-1 rounded-md transition"
          >
            Profitability
          </button>
        </div>
      </div>

      <div class="overflow-x-auto rounded-lg border border-slate-800/80">
        <table class="w-full text-left border-collapse text-xs">
          <thead class="bg-slate-900/90 text-slate-400 font-medium border-b border-slate-800">
            <tr>
              <th class="py-2.5 px-3">Metric</th>
              <th class="py-2.5 px-3 text-right text-sky-400">Run A (Baseline)</th>
              <th class="py-2.5 px-3 text-right text-indigo-400">Run B (Comparison)</th>
              <th class="py-2.5 px-3 text-right">Absolute Delta (&Delta;)</th>
              <th class="py-2.5 px-3 text-right">Percentage Delta (%&Delta;)</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60">
            <tr
              v-for="m in filteredMetrics"
              :key="m.metric_key"
              class="hover:bg-slate-900/40 transition"
            >
              <td class="py-2.5 px-3 font-medium text-white">
                <span>{{ m.metric_label }}</span>
                <span class="ml-2 text-[10px] text-slate-500 font-normal uppercase">{{ m.category }}</span>
              </td>
              <td class="py-2.5 px-3 text-right font-mono text-slate-300">
                {{ formatCurrency(m.value_a, m.unit) }}
              </td>
              <td class="py-2.5 px-3 text-right font-mono text-slate-300">
                {{ formatCurrency(m.value_b, m.unit) }}
              </td>
              <td class="py-2.5 px-3 text-right font-mono">
                <span
                  v-if="m.absolute_delta !== null"
                  :class="{
                    'text-rose-400': m.absolute_delta > 0 && m.category === 'liability',
                    'text-emerald-400': m.absolute_delta < 0 && m.category === 'liability',
                    'text-emerald-400': m.absolute_delta > 0 && m.category !== 'liability',
                    'text-rose-400': m.absolute_delta < 0 && m.category !== 'liability',
                    'text-slate-500': m.absolute_delta === 0,
                  }"
                >
                  {{ m.absolute_delta > 0 ? '+' : '' }}{{ formatCurrency(m.absolute_delta, m.unit) }}
                </span>
                <span v-else class="text-slate-600">—</span>
              </td>
              <td class="py-2.5 px-3 text-right">
                <span
                  v-if="m.percentage_delta !== null"
                  class="px-1.5 py-0.5 rounded text-[11px] font-medium"
                  :class="{
                    'bg-rose-500/10 text-rose-300 border border-rose-500/20':
                      (m.percentage_delta > 0 && m.category === 'liability') ||
                      (m.percentage_delta < 0 && m.category !== 'liability'),
                    'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20':
                      (m.percentage_delta < 0 && m.category === 'liability') ||
                      (m.percentage_delta > 0 && m.category !== 'liability'),
                    'bg-slate-800 text-slate-400': m.percentage_delta === 0,
                  }"
                >
                  {{ formatPercent(m.percentage_delta) }}
                </span>
                <span v-else class="text-slate-600">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
