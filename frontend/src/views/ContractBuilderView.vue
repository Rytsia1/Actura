<script setup>
import { ref, shallowRef, markRaw, onMounted, onUnmounted, nextTick } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import * as echarts from 'echarts'
import {
  FileText,
  DollarSign,
  GitFork,
  ArrowUpRight,
  TrendingUp,
  Target,
  Play,
  RotateCcw,
  Sparkles,
  Layout,
  Trash2,
  X,
  Layers,
  Search,
  ShieldCheck,
  AlertTriangle,
  AlertOctagon,
} from 'lucide-vue-next'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

import PolicyInputNode from '../components/nodes/PolicyInputNode.vue'
import InflowNode from '../components/nodes/InflowNode.vue'
import ContingencyNode from '../components/nodes/ContingencyNode.vue'
import OutflowNode from '../components/nodes/OutflowNode.vue'
import ValuationSinkNode from '../components/nodes/ValuationSinkNode.vue'
import AccumulatorNode from '../components/nodes/AccumulatorNode.vue'
import ModelHealthDrawer from '../components/ModelHealthDrawer.vue'

import { PRESET_TEMPLATES, layoutGraph } from '../utils/presets'
import { simulateContractGraph, evaluateContractHealth, ActuaryApiError } from '../services/actuaryApi'
import { useLoadingStore } from '../stores/useLoadingStore'
import { useErrorStore } from '../stores/useErrorStore'
import ErrorBanner from '../components/ErrorBanner.vue'
import LoadingOverlay from '../components/LoadingOverlay.vue'
import EmptyState from '../components/EmptyState.vue'
import { useRoute } from 'vue-router'
import { projectApi } from '../services/projectApi'

// ────────────────────────────────────────────────────────────
// Custom Node Registrations (markRaw for Vue reactivity performance)
// ────────────────────────────────────────────────────────────
const nodeTypes = {
  policyInput: markRaw(PolicyInputNode),
  inflow: markRaw(InflowNode),
  contingency: markRaw(ContingencyNode),
  outflow: markRaw(OutflowNode),
  valuationSink: markRaw(ValuationSinkNode),
  accumulator: markRaw(AccumulatorNode),
}

// ────────────────────────────────────────────────────────────
// Reactive State
// ────────────────────────────────────────────────────────────
const selectedPresetId = ref('term_life_20y')
const nodes = ref([])
const edges = ref([])
const isSimulating = ref(false)
const simulationResult = shallowRef(null)
const showResultsDrawer = ref(false)
const selectedTrace = ref(null)
const isTraceDrawerOpen = ref(false)

const modelHealthReport = ref(null)
const isHealthDrawerOpen = ref(false)
const isEvaluatingHealth = ref(false)

const loadingStore = useLoadingStore()
const errorStore = useErrorStore()
const route = useRoute()

const { project, fitView, addNodes, onConnect, addEdges } = useVueFlow()

const cashFlowChartRef = ref(null)
const reserveChartRef = ref(null)
let cashFlowChart = null
let reserveChart = null
let resizeObserver = null

import { useValuationStore } from '../stores/useValuationStore'

const valuationStore = useValuationStore()

// ────────────────────────────────────────────────────────────
// Preset Template Loader
// ────────────────────────────────────────────────────────────
function loadPreset(presetKey) {
  const template = PRESET_TEMPLATES[presetKey]
  if (!template) return

  selectedPresetId.value = presetKey
  errorStore.clearError()

  // Clone nodes and edges to avoid mutation
  const rawNodes = JSON.parse(JSON.stringify(template.nodes))
  const rawEdges = JSON.parse(JSON.stringify(template.edges))

  // Run Dagre auto-layout
  const { nodes: layoutedNodes, edges: layoutedEdges } = layoutGraph(rawNodes, rawEdges, 'LR')

  nodes.value = layoutedNodes
  edges.value = layoutedEdges

  nextTick(() => {
    fitView({ padding: 0.2, duration: 400 })
    checkModelHealth()
  })
}

function loadCustomPayload(payload) {
  selectedPresetId.value = 'custom_generated'
  errorStore.clearError()

  const rawNodes = JSON.parse(JSON.stringify(payload.nodes))
  const rawEdges = JSON.parse(JSON.stringify(payload.edges))

  const { nodes: layoutedNodes, edges: layoutedEdges } = layoutGraph(rawNodes, rawEdges, 'LR')

  nodes.value = layoutedNodes
  edges.value = layoutedEdges

  nextTick(() => {
    fitView({ padding: 0.2, duration: 400 })
  })
}

function handleAutoLayout() {
  const { nodes: layoutedNodes, edges: layoutedEdges } = layoutGraph(nodes.value, edges.value, 'LR')
  nodes.value = layoutedNodes
  edges.value = layoutedEdges
  nextTick(() => {
    fitView({ padding: 0.2, duration: 300 })
  })
}

function clearCanvas() {
  nodes.value = []
  edges.value = []
  simulationResult.value = null
}

// ────────────────────────────────────────────────────────────
// Drag & Drop Node Palette Handler
// ────────────────────────────────────────────────────────────
const paletteItems = [
  { type: 'policyInput', label: 'Policy Parameters', icon: markRaw(FileText), badge: 'Source', color: 'border-sky-500/40 text-sky-300' },
  { type: 'inflow', label: 'Cash Inflow', icon: markRaw(DollarSign), badge: 'Inflow', color: 'border-emerald-500/40 text-emerald-300' },
  { type: 'contingency', label: 'Contingency Splitter', icon: markRaw(GitFork), badge: 'Decrement', color: 'border-indigo-500/40 text-indigo-300' },
  { type: 'outflow', label: 'Benefit Outflow', icon: markRaw(ArrowUpRight), badge: 'Outflow', color: 'border-rose-500/40 text-rose-300' },
  { type: 'accumulator', label: 'Fund Accumulator', icon: markRaw(TrendingUp), badge: 'Unit-Linked', color: 'border-amber-500/40 text-amber-300' },
  { type: 'valuationSink', label: 'Valuation Consolidator', icon: markRaw(Target), badge: 'Terminal', color: 'border-indigo-500/60 text-indigo-200' },
]

function onDragStart(event, nodeType) {
  if (event.dataTransfer) {
    event.dataTransfer.setData('application/vueflow', nodeType)
    event.dataTransfer.effectAllowed = 'move'
  }
}

function onDragOver(event) {
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'move'
  }
}

function onDrop(event) {
  const type = event.dataTransfer?.getData('application/vueflow')
  if (!type) return

  const bounds = event.currentTarget.getBoundingClientRect()
  const position = project({
    x: event.clientX - bounds.left - 130,
    y: event.clientY - bounds.top - 80,
  })

  const newNodeId = `node-${type}-${Date.now()}`
  let defaultData = {}

  if (type === 'policyInput') {
    defaultData = { product_name: 'Custom Policy', age: 35, term: 20, sum_assured: 1000000, interest_rate: 0.05 }
  } else if (type === 'inflow') {
    defaultData = { inflow_type: 'Gross Premium', mode: 'formula', amount: 0 }
  } else if (type === 'contingency') {
    defaultData = { decrement_type: 'Mortality', table_id: 'soa_ilt', multiplier: 1.0, lapse_rate: 0.03 }
  } else if (type === 'outflow') {
    defaultData = { benefit_type: 'Death Benefit', formula: '1.0 * SA', factor: 1.0 }
  } else if (type === 'accumulator') {
    defaultData = { growth_rate: 0.065, admin_charge: 100, allocation_pct: 0.95 }
  } else if (type === 'valuationSink') {
    defaultData = { label: 'Valuation Consolidator' }
  }

  addNodes([
    {
      id: newNodeId,
      type,
      position,
      data: defaultData,
    },
  ])
}

// Wire new edge connections
onConnect((params) => {
  addEdges([
    {
      ...params,
      animated: true,
      style: { stroke: '#38BDF8', strokeWidth: 2 },
    },
  ])
})

// ────────────────────────────────────────────────────────────
// Simulation Execution & Results Render
// ────────────────────────────────────────────────────────────
// Simulation & Health Execution
// ────────────────────────────────────────────────────────────
function getCurrentPayload() {
  return {
    contract_id: `GRAPH-${selectedPresetId.value || 'CUSTOM'}`,
    nodes: nodes.value.map((n) => ({
      id: n.id,
      type: n.type,
      data: n.data || {},
      position: n.position,
    })),
    edges: edges.value.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle || null,
      targetHandle: e.targetHandle || null,
    })),
  }
}

async function checkModelHealth() {
  if (nodes.value.length === 0) {
    modelHealthReport.value = null
    return
  }
  isEvaluatingHealth.value = true
  try {
    const payload = getCurrentPayload()
    const res = await evaluateContractHealth(payload)
    modelHealthReport.value = res.data || res
  } catch (err) {
    console.warn('Health evaluation error:', err)
  } finally {
    isEvaluatingHealth.value = false
  }
}

function openHealthDrawer() {
  checkModelHealth()
  isHealthDrawerOpen.value = true
}

function handleHighlightNode(nodeId) {
  if (!nodeId) return
  nodes.value = nodes.value.map((n) => ({
    ...n,
    class:
      n.id === nodeId
        ? 'ring-4 ring-amber-500 ring-offset-4 ring-offset-[#0B0F19] shadow-[0_0_30px_rgba(245,158,11,0.5)] z-50 scale-105 transition-all duration-300'
        : 'opacity-40 transition-all duration-300',
  }))
  isHealthDrawerOpen.value = false
  setTimeout(() => {
    fitView({ nodes: [nodeId], padding: 0.6, duration: 600 })
  }, 100)
}

const healthButtonClass = computed(() => {
  if (!modelHealthReport.value) return 'bg-slate-800 text-slate-300 border-slate-700'
  if (modelHealthReport.value.overall_status === 'PASS') {
    return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/20'
  }
  if (modelHealthReport.value.overall_status === 'WARNING') {
    return 'bg-amber-500/10 text-amber-300 border-amber-500/30 hover:bg-amber-500/20'
  }
  return 'bg-rose-500/10 text-rose-300 border-rose-500/30 hover:bg-rose-500/20 animate-pulse'
})

async function runSimulation() {
  if (nodes.value.length === 0) {
    errorStore.setError({ code: 'EMPTY_BLUEPRINT', message: 'Canvas is empty. Add nodes or load a preset template.' })
    return
  }

  // Pre-flight Model Health audit
  await checkModelHealth()
  if (modelHealthReport.value && !modelHealthReport.value.is_ready_to_run) {
    isHealthDrawerOpen.value = true
    errorStore.setError({
      code: 'PREFLIGHT_BLOCKED',
      message: 'Pre-flight check failed: Model has critical defects. Open Model Health to inspect blockers.'
    })
    return
  }

  isSimulating.value = true
  errorStore.clearError()
  loadingStore.startLoading()
  loadingStore.updateStep('prepare', 'active')

  // Update sink nodes with loading indicator
  nodes.value.forEach((node) => {
    if (node.type === 'valuationSink') {
      node.data = { ...node.data, isSimulating: true }
    }
  })

  try {
    const payload = {
      nodes: nodes.value.map((n) => ({
        id: n.id,
        type: n.type,
        data: n.data || {},
        position: n.position,
      })),
      edges: edges.value.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle || null,
        targetHandle: e.targetHandle || null,
      })),
    }

    loadingStore.updateStep('prepare', 'complete')
    loadingStore.updateStep('projection', 'active')
    
    let res = null
    const projectId = route.params.id

    if (projectId) {
      // Save blueprint to DB
      const saveResponse = await projectApi.saveBlueprint(projectId, "Draft Blueprint", payload)
      const contract = saveResponse.data || saveResponse
      
      loadingStore.updateStep('projection', 'complete')
      loadingStore.updateStep('stochastic', 'active')
      
      // Run Valuation
      const runResponse = await projectApi.runValuation(projectId, contract.id)
      const run = runResponse.data || runResponse
      
      // Fetch result
      if (run.status === 'completed') {
         const resultResponse = await projectApi.getValuationResult(projectId, run.id)
         const resultData = resultResponse.data || resultResponse
         res = resultData.result?.full_output || {}
      } else {
         throw new Error(`Valuation failed: ${run.status}`)
      }
    } else {
      // Standalone simulation (Sandbox or Guided Mode)
      loadingStore.updateStep('projection', 'complete')
      loadingStore.updateStep('stochastic', 'active')
      const simResponse = await simulateContractGraph(payload)
      res = simResponse.data || simResponse
    }

    loadingStore.updateStep('stochastic', 'complete')
    loadingStore.updateStep('risk', 'complete')
    loadingStore.updateStep('finalize', 'active')

    simulationResult.value = res
    showResultsDrawer.value = true

    // Pass summary back to sink nodes
    nodes.value.forEach((node) => {
      if (node.type === 'valuationSink') {
        node.data = {
          ...node.data,
          isSimulating: false,
          summary: {
            total_bel: res.total_bel,
            annual_premium: res.annual_premium,
          },
        }
      }
    })

    loadingStore.updateStep('finalize', 'complete')
    await nextTick()
    renderResultCharts()
  } catch (err) {
    console.error('Graph simulation error:', err)
    loadingStore.updateStep('projection', 'error')
    loadingStore.updateStep('stochastic', 'error')
    loadingStore.updateStep('risk', 'error')
    loadingStore.updateStep('finalize', 'error')
    
    if (err instanceof ActuaryApiError) {
      errorStore.setError(err)
    } else {
      errorStore.setError({ message: err.message || 'Failed to simulate contract logic graph.' })
    }
  } finally {
    loadingStore.stopLoading()
    isSimulating.value = false
    nodes.value.forEach((node) => {
      if (node.type === 'valuationSink') {
        node.data = { ...node.data, isSimulating: false }
      }
    })
  }
}

// ────────────────────────────────────────────────────────────
// ECharts Theme & Results Charts
// ────────────────────────────────────────────────────────────
const chartTooltip = {
  backgroundColor: 'rgba(15, 23, 42, 0.96)',
  borderColor: 'rgba(255, 255, 255, 0.08)',
  borderWidth: 1,
  textStyle: { color: '#E2E8F0', fontSize: 12, fontFamily: 'Inter, system-ui' },
}
const chartAxisLabel = { color: '#64748B', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }
const chartSplitLine = { lineStyle: { color: 'rgba(255, 255, 255, 0.04)' } }
const chartAxisLine = { lineStyle: { color: '#1E293B' } }

function formatCurrency(val) {
  if (val === undefined || val === null || isNaN(val)) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(val)
}

function renderResultCharts() {
  if (!simulationResult.value) return

  const data = simulationResult.value
  const years = data.years.map((y) => `Yr ${y}`)

  // 1. Cash Flow Waterfall Chart
  if (cashFlowChartRef.value) {
    if (!cashFlowChart) cashFlowChart = markRaw(echarts.init(cashFlowChartRef.value))
    cashFlowChart.setOption({
      backgroundColor: 'transparent',
      tooltip: { ...chartTooltip, trigger: 'axis' },
      legend: {
        data: ['Premium Income', 'Death Claims', 'Maturity Payouts', 'Expenses', 'Net Cash Flow'],
        textStyle: { color: '#94A3B8', fontSize: 11 },
        top: 0,
        right: 10,
      },
      grid: { top: 35, left: 65, right: 20, bottom: 25 },
      xAxis: { type: 'category', data: years, axisLine: chartAxisLine, axisLabel: chartAxisLabel },
      yAxis: { type: 'value', axisLabel: { ...chartAxisLabel, formatter: (v) => `$${(v / 1000).toFixed(0)}k` }, splitLine: chartSplitLine },
      series: [
        { name: 'Premium Income', type: 'bar', stack: 'inflow', data: data.premiums, itemStyle: { color: '#34D399', borderRadius: [3, 3, 0, 0] } },
        { name: 'Death Claims', type: 'bar', stack: 'outflow', data: data.death_claims, itemStyle: { color: '#F43F5E', borderRadius: [3, 3, 0, 0] } },
        { name: 'Maturity Payouts', type: 'bar', stack: 'outflow', data: data.maturity_payouts, itemStyle: { color: '#FBBF24' } },
        { name: 'Expenses', type: 'bar', stack: 'outflow', data: data.expenses, itemStyle: { color: '#818CF8' } },
        { name: 'Net Cash Flow', type: 'line', data: data.net_cash_flow, smooth: true, lineStyle: { width: 2.5, color: '#38BDF8' }, itemStyle: { color: '#38BDF8' } },
      ],
    })
  }

  // 2. Gross Reserve Profile
  if (reserveChartRef.value) {
    if (!reserveChart) reserveChart = markRaw(echarts.init(reserveChartRef.value))
    const reserveDurations = data.reserves.map((_, i) => `t=${i}`)
    reserveChart.setOption({
      backgroundColor: 'transparent',
      tooltip: { ...chartTooltip, trigger: 'axis' },
      grid: { top: 25, left: 65, right: 20, bottom: 25 },
      xAxis: { type: 'category', data: reserveDurations, boundaryGap: false, axisLine: chartAxisLine, axisLabel: chartAxisLabel },
      yAxis: { type: 'value', axisLabel: { ...chartAxisLabel, formatter: (v) => `$${(v / 1000).toFixed(0)}k` }, splitLine: chartSplitLine },
      series: [
        {
          name: 'Gross Reserve (tV)',
          type: 'line',
          data: data.reserves,
          smooth: true,
          lineStyle: { width: 2.5, color: '#818CF8' },
          itemStyle: { color: '#818CF8' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(129, 140, 248, 0.25)' },
              { offset: 1, color: 'rgba(129, 140, 248, 0.0)' },
            ]),
          },
        },
      ],
    })
  }
}

// ────────────────────────────────────────────────────────────
// Provenance Tracing Layer
// ────────────────────────────────────────────────────────────
function openTrace(metricKey) {
  if (!simulationResult.value?.provenance || !simulationResult.value.provenance[metricKey]) {
    return
  }
  selectedTrace.value = simulationResult.value.provenance[metricKey]
  isTraceDrawerOpen.value = true
}

function highlightSourceNodes() {
  if (!selectedTrace.value || !selectedTrace.value.source_nodes) return
  const sourceIds = selectedTrace.value.source_nodes
  
  // Highlight nodes in vue-flow
  nodes.value = nodes.value.map(n => ({
    ...n,
    class: sourceIds.includes(n.id) 
      ? 'ring-4 ring-amber-500 ring-offset-4 ring-offset-[#0B0F19] shadow-[0_0_30px_rgba(245,158,11,0.5)] z-50 scale-105 transition-all duration-300' 
      : 'opacity-40 transition-all duration-300'
  }))
  
  // Close drawers and fit view
  isTraceDrawerOpen.value = false
  showResultsDrawer.value = false
  setTimeout(() => {
    fitView({ nodes: sourceIds, padding: 0.5, duration: 600 })
  }, 100)
}

function clearHighlight() {
  nodes.value = nodes.value.map(n => ({ ...n, class: '' }))
  fitView({ padding: 0.2, duration: 400 })
}

// ────────────────────────────────────────────────────────────
// Lifecycle
// ────────────────────────────────────────────────────────────
onMounted(async () => {
  if (valuationStore.customBlueprintPayload) {
    loadCustomPayload(valuationStore.customBlueprintPayload)
    valuationStore.clearCustomBlueprintPayload()
  } else {
    const projectId = route.params.id
    if (projectId) {
      try {
        const response = await projectApi.listBlueprints(projectId)
        const contracts = response.data || response
        if (contracts && contracts.length > 0) {
          const contract = contracts[0] // Load latest/first contract
          const blueprint = contract.blueprint_json
          
          // Populate nodes and edges from blueprint
          if (blueprint.nodes && blueprint.edges) {
            // If nodes don't have positions (e.g. fresh from wizard preset), auto-layout them
            const needsLayout = blueprint.nodes.some(n => !n.position)
            if (needsLayout) {
              const { nodes: layoutedNodes, edges: layoutedEdges } = layoutGraph(blueprint.nodes, blueprint.edges, 'LR')
              nodes.value = layoutedNodes
              edges.value = layoutedEdges
            } else {
              nodes.value = blueprint.nodes
              edges.value = blueprint.edges
            }
            nextTick(() => fitView({ padding: 0.2, duration: 400 }))
          } else {
            loadPreset('term_life_20y')
          }
        } else {
          loadPreset('term_life_20y')
        }
      } catch (err) {
        console.error("Failed to fetch blueprint:", err)
        loadPreset('term_life_20y')
      }
    } else {
      loadPreset(selectedPresetId.value || 'term_life_20y')
    }
  }

  resizeObserver = new ResizeObserver(() => {
    cashFlowChart?.resize()
    reserveChart?.resize()
  })

  if (cashFlowChartRef.value) resizeObserver.observe(cashFlowChartRef.value)
  if (reserveChartRef.value) resizeObserver.observe(reserveChartRef.value)
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  cashFlowChart?.dispose()
  reserveChart?.dispose()
})
</script>

<template>
  <div class="h-[calc(100vh-80px)] flex flex-col bg-[#0B0F19] text-slate-100 overflow-hidden relative">
    <LoadingOverlay />

    <!-- ═══════════════════════════════════════════════════════ -->
    <!-- 1. TOP TOOLBAR & PRESET SELECTOR                        -->
    <!-- ═══════════════════════════════════════════════════════ -->
    <header class="h-14 px-6 border-b border-white/[0.06] bg-[#0F172A] flex items-center justify-between flex-shrink-0 z-20">
      <div class="flex items-center space-x-4">
        <div class="flex items-center space-x-3">
          <router-link to="/" class="h-8 w-8 rounded hover:bg-white/[0.05] flex items-center justify-center text-slate-400 hover:text-white transition-colors" title="Back to Dashboard">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-arrow-left"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>
          </router-link>
          
          <div class="h-10 w-10 rounded-xl flex-shrink-0 shadow-md border border-white/[0.05] relative overflow-hidden bg-[#070b14]">
            <img src="/logo.jpg" alt="Actura Mascot" class="absolute w-[220%] h-[220%] max-w-none -bottom-[15%] -right-[20%]" />
          </div>
          <div class="min-w-0 flex-1">
            <h1 class="text-sm font-semibold text-white tracking-tight">Actura</h1>
            <p class="text-xs text-slate-500 font-medium truncate">Actuarial Valuation & Risk Platform</p>
          </div>
        </div>

        <div class="h-4 w-[1px] bg-white/[0.1] hidden sm:block"></div>

        <!-- Template Selector Dropdown -->
        <div class="flex items-center space-x-2">
          <span class="text-xs text-slate-400 font-mono hidden md:inline">Preset:</span>
          <select
            v-model="selectedPresetId"
            @change="loadPreset(selectedPresetId)"
            class="input-field py-1.5 px-3 text-xs bg-slate-800 border-white/[0.1] text-sky-400 font-medium"
          >
            <option v-for="(tmpl, key) in PRESET_TEMPLATES" :key="key" :value="key">
              {{ tmpl.name }} ({{ tmpl.badge }})
            </option>
          </select>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="flex items-center space-x-2">
        <button
          @click="handleAutoLayout"
          class="btn-secondary text-xs px-3 py-1.5 flex items-center space-x-1.5 hover:border-slate-500 rounded-md"
          title="Auto-organize DAG node layout using Dagre"
        >
          <Layout class="h-3.5 w-3.5 text-slate-400" />
          <span class="hidden sm:inline">Auto-Layout</span>
        </button>

        <button
          v-if="nodes.some(n => n.class?.includes('ring-amber-500'))"
          @click="clearHighlight"
          class="btn-secondary text-xs px-3 py-1.5 flex items-center space-x-1.5 text-amber-400 hover:text-amber-300 border-amber-500/30 rounded-md"
        >
          <span>Clear Trace</span>
        </button>

        <button
          @click="clearCanvas"
          class="btn-secondary text-xs px-2.5 py-1.5 text-slate-400 hover:text-rose-400 rounded-md"
          title="Clear all nodes"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </button>

        <!-- Model Health Pre-flight Indicator Button -->
        <button
          @click="openHealthDrawer"
          :class="[
            'text-xs px-3 py-1.5 flex items-center space-x-1.5 rounded-md border font-medium transition',
            healthButtonClass
          ]"
          title="Inspect Model Health across 7 categories before valuation"
        >
          <ShieldCheck v-if="modelHealthReport?.overall_status === 'PASS'" class="h-3.5 w-3.5 text-emerald-400" />
          <AlertTriangle v-else-if="modelHealthReport?.overall_status === 'WARNING'" class="h-3.5 w-3.5 text-amber-400" />
          <AlertOctagon v-else class="h-3.5 w-3.5 text-rose-400" />
          <span>Health: {{ modelHealthReport?.overall_score ?? '--' }}/100</span>
        </button>

        <button
          @click="runSimulation"
          :disabled="isSimulating"
          class="btn-primary text-xs px-4 py-1.5 flex items-center space-x-1.5 shadow-lg shadow-sky-500/20 rounded-md"
        >
          <RotateCcw v-if="isSimulating" class="animate-spin h-3.5 w-3.5 text-white" />
          <Play v-else class="h-3.5 w-3.5 text-white" />
          <span>{{ isSimulating ? 'Simulating...' : 'Run Simulation' }}</span>
        </button>
      </div>
    </header>

    <ErrorBanner />

    <!-- ═══════════════════════════════════════════════════════ -->
    <!-- 2. MAIN WORKSPACE: PALETTE + CANVAS                     -->
    <!-- ═══════════════════════════════════════════════════════ -->
    <div class="flex-1 flex overflow-hidden relative">

      <!-- Left Sidebar: Draggable Node Palette -->
      <aside class="w-56 border-r border-white/[0.06] bg-[#0B0F19] p-4 flex flex-col space-y-3 z-10 select-none">
        <div class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Node Palette</div>
        <p class="text-[10px] text-slate-500">Drag components onto the blueprint canvas</p>

        <div class="space-y-2 pt-1 flex-1 overflow-y-auto">
          <div
            v-for="item in paletteItems"
            :key="item.type"
            draggable="true"
            @dragstart="onDragStart($event, item.type)"
            :class="[
              'p-2.5 rounded-lg border bg-[#0F172A] hover:bg-slate-800/80 cursor-grab active:cursor-grabbing transition shadow flex items-center justify-between',
              item.color
            ]"
          >
            <div class="flex items-center space-x-2.5">
              <component :is="item.icon" class="w-4 h-4 text-slate-400" />
              <span class="text-xs font-medium text-slate-200">{{ item.label }}</span>
            </div>
            <span class="text-[9px] font-mono px-1.5 py-0.5 rounded bg-white/[0.05] text-slate-400">
              {{ item.badge }}
            </span>
          </div>
        </div>

        <div class="card-inset p-2.5 rounded-lg text-[10px] text-slate-500 space-y-1">
          <div class="font-medium text-slate-400">Blueprint Tips:</div>
          <div>• Connect ports by dragging edges.</div>
          <div>• Wire into <strong>Valuation Consolidator</strong> to compute cash flows.</div>
        </div>
      </aside>

      <!-- Center: Vue Flow Canvas -->
      <main class="flex-1 h-full relative" @drop="onDrop" @dragover="onDragOver">
        <div v-if="nodes.length === 0" class="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
          <EmptyState 
            title="Canvas is Empty" 
            description="Drag nodes from the palette on the left to start building your actuarial blueprint."
            class="pointer-events-auto"
          >
            <template #icon>
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-box select-none"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>
            </template>
          </EmptyState>
        </div>
        <VueFlow
          v-model:nodes="nodes"
          v-model:edges="edges"
          :node-types="nodeTypes"
          :default-viewport="{ zoom: 0.85 }"
          :min-zoom="0.2"
          :max-zoom="2.5"
          fit-view-on-init
          class="w-full h-full bg-[#0B0F19]"
          @node-click="() => {}"
        >
          <Background pattern-color="rgba(255, 255, 255, 0.05)" :gap="24" />
          <MiniMap pannable zoomable class="bg-slate-800 border-slate-700" />
          <Controls class="!bg-[#0F172A] !border !border-white/[0.08] !rounded-lg !text-slate-300" />
        </VueFlow>
      </main>

    </div>

    <!-- ═══════════════════════════════════════════════════════ -->
    <!-- 3. SIMULATION RESULTS DRAWER / BOTTOM PANEL             -->
    <!-- ═══════════════════════════════════════════════════════ -->
    <div
      v-if="showResultsDrawer && simulationResult"
      class="fixed inset-x-0 bottom-0 max-h-[60vh] bg-[#0F172A] border-t border-white/[0.1] shadow-2xl z-30 flex flex-col transition-all duration-300 overflow-hidden"
    >
      <!-- Drawer Header -->
      <div class="px-6 py-3 border-b border-white/[0.06] flex items-center justify-between bg-[#182234]">
        <div class="flex items-center space-x-3">
          <span class="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
          <div>
            <h3 class="text-sm font-semibold text-white">
              Simulation Results: {{ simulationResult.product_name }}
            </h3>
            <span class="text-[10px] text-slate-400 font-mono">
              Age {{ simulationResult.issue_age }} | Term {{ simulationResult.term }} yrs | Face {{ formatCurrency(simulationResult.sum_assured) }}
            </span>
          </div>
        </div>

        <div class="flex items-center space-x-3">
          <button @click="showResultsDrawer = false" class="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-700">
            <X class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- Drawer Content -->
      <div class="p-6 overflow-y-auto space-y-6">

        <!-- KPI Strip -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div class="card p-3.5">
            <div class="flex items-center justify-between">
              <div class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Best Estimate Liability (BEL)</div>
              <button v-if="simulationResult.provenance?.total_bel" @click="openTrace('total_bel')" class="flex items-center space-x-1 text-[10px] text-amber-400 hover:text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 px-1.5 py-0.5 rounded border border-amber-500/20 transition-colors">
                <Search class="w-3 h-3" /> <span>Trace</span>
              </button>
            </div>
            <div class="text-xl font-semibold text-sky-400 mt-1 font-mono">
              {{ formatCurrency(simulationResult.total_bel) }}
            </div>
            <div class="text-[10px] text-slate-500 mt-0.5">Discounted Net Liability Outgo</div>
          </div>

          <div class="card p-3.5">
            <div class="flex items-center justify-between">
              <div class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Equivalence Gross Premium</div>
              <button v-if="simulationResult.provenance?.annual_premium" @click="openTrace('annual_premium')" class="flex items-center space-x-1 text-[10px] text-amber-400 hover:text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 px-1.5 py-0.5 rounded border border-amber-500/20 transition-colors">
                <Search class="w-3 h-3" /> <span>Trace</span>
              </button>
            </div>
            <div class="text-xl font-semibold text-emerald-400 mt-1 font-mono">
              {{ formatCurrency(simulationResult.annual_premium) }} / yr
            </div>
            <div class="text-[10px] text-slate-500 mt-0.5">Loaded Annual Equivalence</div>
          </div>

          <div class="card p-3.5">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Total Projected Claims</div>
            <div class="text-xl font-semibold text-rose-400 mt-1 font-mono">
              {{ formatCurrency(simulationResult.breakdown?.total_claims || 0) }}
            </div>
            <div class="text-[10px] text-slate-500 mt-0.5">Nominal Expected Claims Outflow</div>
          </div>

          <div class="card p-3.5">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Total Projected Inflow</div>
            <div class="text-xl font-semibold text-indigo-400 mt-1 font-mono">
              {{ formatCurrency(simulationResult.breakdown?.total_premiums || 0) }}
            </div>
            <div class="text-[10px] text-slate-500 mt-0.5">Cumulative Expected Premiums</div>
          </div>
        </div>

        <!-- Charts Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div class="card p-4 space-y-2">
            <h4 class="text-xs font-semibold text-white">Cash Flow Waterfall (NCF_t)</h4>
            <div ref="cashFlowChartRef" class="w-full h-64"></div>
          </div>
          <div class="card p-4 space-y-2">
            <h4 class="text-xs font-semibold text-white">Gross Reserve Profile (tV)</h4>
            <div ref="reserveChartRef" class="w-full h-64"></div>
          </div>
        </div>

        <!-- Year-by-Year Projection Table -->
        <div class="card p-4 space-y-3">
          <div class="flex items-center justify-between">
            <h4 class="text-xs font-semibold text-white">Year-by-Year Multi-Decrement Projection</h4>
            <span class="text-[10px] font-mono text-slate-500">{{ simulationResult.years.length }} durations</span>
          </div>

          <div class="overflow-x-auto card-inset rounded-lg max-h-60">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Age</th>
                  <th>In-Force ($l_t$)</th>
                  <th>Premium Inflow</th>
                  <th>Death Claims</th>
                  <th>Maturity Payouts</th>
                  <th>Expenses</th>
                  <th>Net Cash Flow</th>
                  <th>Gross Reserve</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(yr, idx) in simulationResult.years" :key="yr">
                  <td class="text-sky-400 font-semibold">Yr {{ yr }}</td>
                  <td>{{ simulationResult.ages[idx] }}</td>
                  <td class="font-mono text-slate-400">{{ (simulationResult.inforce_boy[idx] * 100).toFixed(2) }}%</td>
                  <td class="text-emerald-400 font-mono">{{ formatCurrency(simulationResult.premiums[idx]) }}</td>
                  <td class="text-rose-400 font-mono">{{ formatCurrency(simulationResult.death_claims[idx]) }}</td>
                  <td class="text-amber-400 font-mono">{{ formatCurrency(simulationResult.maturity_payouts[idx]) }}</td>
                  <td class="text-slate-400 font-mono">{{ formatCurrency(simulationResult.expenses[idx]) }}</td>
                  <td :class="['font-mono font-semibold', simulationResult.net_cash_flow[idx] >= 0 ? 'text-emerald-400' : 'text-rose-400']">
                    {{ formatCurrency(simulationResult.net_cash_flow[idx]) }}
                  </td>
                  <td class="text-indigo-400 font-mono font-semibold">{{ formatCurrency(simulationResult.reserves[idx]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════ -->
    <!-- 4. PROVENANCE TRACE MODAL                               -->
    <!-- ═══════════════════════════════════════════════════════ -->
    <div v-if="isTraceDrawerOpen && selectedTrace" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div class="bg-[#0F172A] border border-white/[0.1] shadow-2xl rounded-xl w-full max-w-2xl flex flex-col overflow-hidden">
        <div class="px-5 py-4 border-b border-white/[0.06] flex items-center justify-between bg-[#182234]">
          <div class="flex items-center space-x-2.5">
            <Search class="w-4 h-4 text-amber-400" />
            <h3 class="text-sm font-semibold text-white">Calculation Provenance: {{ selectedTrace.metric_name }}</h3>
          </div>
          <button @click="isTraceDrawerOpen = false" class="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition">
            <X class="w-4 h-4" />
          </button>
        </div>
        
        <div class="p-6 space-y-6">
          <div class="flex items-start justify-between">
            <div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Computed Value</div>
              <div class="text-2xl font-semibold text-amber-400 mt-1 font-mono">{{ formatCurrency(selectedTrace.value) }}</div>
            </div>
            <div class="text-right">
              <div class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Calculation Stage</div>
              <div class="text-sm font-medium text-slate-300 mt-1">{{ selectedTrace.calculation_stage }}</div>
            </div>
          </div>
          
          <div class="card p-4 space-y-2 border-amber-500/20 bg-amber-500/5">
            <h4 class="text-xs font-medium text-slate-300">Actuarial Narrative</h4>
            <p class="text-sm text-slate-400 leading-relaxed">{{ selectedTrace.calculation_description }}</p>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div class="card p-4 space-y-3">
              <h4 class="text-xs font-medium text-slate-300">Contributing Components</h4>
              <ul class="space-y-1.5">
                <li v-for="comp in selectedTrace.contributing_components" :key="comp" class="flex items-center space-x-2 text-xs text-slate-400">
                  <span class="w-1.5 h-1.5 rounded-full bg-sky-500"></span>
                  <span>{{ comp }}</span>
                </li>
              </ul>
            </div>
            <div class="card p-4 space-y-3">
              <h4 class="text-xs font-medium text-slate-300">Relevant Assumptions</h4>
              <ul class="space-y-1.5">
                <li v-for="(val, key) in selectedTrace.relevant_assumptions" :key="key" class="flex items-center justify-between text-xs text-slate-400 border-b border-white/[0.04] pb-1 last:border-0 last:pb-0">
                  <span>{{ key }}</span>
                  <span class="font-mono text-slate-300">{{ val }}</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
        
        <div class="px-5 py-4 border-t border-white/[0.06] bg-[#182234] flex items-center justify-end space-x-3">
          <button @click="isTraceDrawerOpen = false" class="btn-secondary text-xs px-4 py-1.5 rounded-md">Close</button>
          <button @click="highlightSourceNodes" class="btn-primary text-xs px-4 py-1.5 rounded-md flex items-center space-x-2 border-amber-500/50 bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 hover:text-amber-300">
            <Target class="w-3.5 h-3.5" />
            <span>Highlight Blueprint Nodes</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 5. MODEL HEALTH DRAWER -->
    <ModelHealthDrawer
      :isOpen="isHealthDrawerOpen"
      :report="modelHealthReport"
      :loading="isEvaluatingHealth"
      @close="isHealthDrawerOpen = false"
      @recheck="checkModelHealth"
      @highlightNode="handleHighlightNode"
    />

  </div>
</template>

<style>
/* Vue Flow Dark Styling Customizations */
.vue-flow__edge-path {
  stroke: #38BDF8 !important;
  stroke-width: 2 !important;
}

.vue-flow__edge.animated path {
  stroke-dasharray: 5;
  animation: vue-flow-dash 1s linear infinite;
}

@keyframes vue-flow-dash {
  from {
    stroke-dashoffset: 10;
  }
  to {
    stroke-dashoffset: 0;
  }
}
</style>
