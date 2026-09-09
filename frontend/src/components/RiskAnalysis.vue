<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: {
    type: Object,
    required: true
  }
})

const chartRef = ref(null)
let chart = null
let resizeObserver = null

const chartTooltip = {
  backgroundColor: 'rgba(15, 23, 42, 0.96)',
  borderColor: 'rgba(255, 255, 255, 0.08)',
  borderWidth: 1,
  textStyle: { color: '#E2E8F0', fontSize: 12, fontFamily: 'Inter, system-ui' },
}

function formatCurrency(val) {
  if (val === undefined || val === null || isNaN(val)) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(val)
}

function renderChart() {
  if (!chartRef.value || !props.data) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  // Assuming data has full_output.net_cash_flow or we just plot a placeholder distribution
  // If distribution array was provided in stochastic:
  const distribution = props.data.distribution || []
  
  // If no distribution provided, we'll just mock a normal distribution around BEL for demonstration
  let chartData = []
  let bins = []
  
  if (distribution.length > 0) {
    const histogram = distribution.reduce((acc, val) => {
      const bin = Math.floor(val / 1000) * 1000
      acc[bin] = (acc[bin] || 0) + 1
      return acc
    }, {})
    
    bins = Object.keys(histogram).sort((a,b) => a-b)
    chartData = bins.map(bin => histogram[bin])
  } else {
    // Mock distribution for the visual
    const bel = props.data.bel || 100000
    for(let i=0; i<20; i++) {
        bins.push(`Bin ${i+1}`)
        chartData.push(Math.exp(-Math.pow(i-10, 2)/10) * 100)
    }
  }

  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { ...chartTooltip, trigger: 'axis' },
    grid: { top: 20, left: 40, right: 20, bottom: 20 },
    xAxis: { 
      type: 'category', 
      data: bins,
      axisLabel: { color: '#64748B', fontSize: 10 }
    },
    yAxis: { 
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.04)' } },
      axisLabel: { color: '#64748B', fontSize: 10 }
    },
    series: [
      {
        name: 'Frequency',
        type: 'bar',
        data: chartData,
        itemStyle: { color: '#34D399', borderRadius: [2, 2, 0, 0] }
      }
    ]
  })
}

watch(() => props.data, () => {
  renderChart()
}, { deep: true })

onMounted(() => {
  renderChart()
  resizeObserver = new ResizeObserver(() => {
    chart?.resize()
  })
  if (chartRef.value) resizeObserver.observe(chartRef.value)
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div class="card p-5">
        <div class="text-xs text-slate-400 uppercase tracking-wider font-medium mb-1">Best Estimate Liability (BEL)</div>
        <div class="text-2xl font-semibold text-sky-400 font-mono">{{ formatCurrency(data?.bel) }}</div>
      </div>
      <div class="card p-5">
        <div class="text-xs text-slate-400 uppercase tracking-wider font-medium mb-1">Value at Risk (95%)</div>
        <div class="text-2xl font-semibold text-rose-400 font-mono">{{ formatCurrency(data?.var_95) }}</div>
      </div>
      <div class="card p-5">
        <div class="text-xs text-slate-400 uppercase tracking-wider font-medium mb-1">Conditional Tail Expectation (95%)</div>
        <div class="text-2xl font-semibold text-amber-400 font-mono">{{ formatCurrency(data?.cvar_95) }}</div>
      </div>
    </div>
    
    <div class="card p-6">
      <h4 class="text-sm font-semibold text-white mb-4">Distribution of Outcomes (Stochastic)</h4>
      <div ref="chartRef" class="w-full h-64"></div>
    </div>
  </div>
</template>
