<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm flex justify-end transition-opacity">
    <div
      class="w-full max-w-2xl bg-[#0F172A] border-l border-white/[0.08] shadow-2xl flex flex-col h-full overflow-hidden animate-in slide-in-from-right duration-200"
      @click.stop
    >
      <!-- 1. DRAWER HEADER -->
      <div class="px-6 py-5 border-b border-white/[0.08] bg-slate-900/60 flex items-center justify-between flex-shrink-0">
        <div class="flex items-center space-x-3">
          <div
            :class="[
              'h-10 w-10 rounded-xl flex items-center justify-center font-bold text-lg border',
              scoreBadgeStyle
            ]"
          >
            <ShieldCheck v-if="report?.overall_status === 'PASS'" class="w-6 h-6 text-emerald-400" />
            <AlertTriangle v-else-if="report?.overall_status === 'WARNING'" class="w-6 h-6 text-amber-400" />
            <AlertOctagon v-else class="w-6 h-6 text-rose-400" />
          </div>
          <div>
            <div class="flex items-center space-x-2">
              <h2 class="text-base font-bold text-white tracking-tight">Model Health Audit</h2>
              <span :class="['px-2 py-0.5 rounded text-[11px] font-bold border uppercase tracking-wider', statusBadgeStyle]">
                {{ statusLabel }}
              </span>
            </div>
            <p class="text-xs text-slate-400 mt-0.5">
              Readiness verification &amp; calculation trust audit across 7 categories
            </p>
          </div>
        </div>

        <div class="flex items-center space-x-2">
          <button
            @click="$emit('recheck')"
            :disabled="loading"
            class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
            title="Re-run Model Health Evaluation"
          >
            <RefreshCw :class="['w-4 h-4', loading ? 'animate-spin' : '']" />
          </button>
          <button
            @click="$emit('close')"
            class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition"
          >
            <X class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- 2. OVERALL SCORE & HEADLINE HERO -->
      <div class="px-6 py-4 border-b border-white/[0.06] bg-slate-950/40 flex-shrink-0">
        <div class="flex items-center justify-between">
          <div>
            <span class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Model Readiness Score</span>
            <div class="flex items-baseline space-x-2 mt-0.5">
              <span class="text-3xl font-extrabold text-white font-mono">{{ report?.overall_score ?? '--' }}</span>
              <span class="text-xs text-slate-500 font-mono">/ 100</span>
            </div>
          </div>
          <div class="text-right">
            <span class="text-xs font-medium text-slate-300">Execution Readiness</span>
            <div class="mt-0.5">
              <span
                v-if="report?.is_ready_to_run"
                class="inline-flex items-center text-xs font-semibold text-emerald-400 gap-1"
              >
                <CheckCircle2 class="w-3.5 h-3.5" /> Ready for Valuation
              </span>
              <span
                v-else
                class="inline-flex items-center text-xs font-semibold text-rose-400 gap-1"
              >
                <AlertOctagon class="w-3.5 h-3.5" /> Blocked — Fix Issues
              </span>
            </div>
          </div>
        </div>

        <!-- Headline -->
        <p class="text-xs text-slate-300 mt-2.5 p-2.5 rounded-lg bg-slate-900 border border-slate-800 flex items-center gap-2">
          <Info class="w-4 h-4 text-sky-400 flex-shrink-0" />
          <span>{{ report?.summary_headline || 'Evaluating model health...' }}</span>
        </p>

        <!-- Score Breakdown Toggle -->
        <div class="mt-2.5">
          <button
            @click="showScoreBreakdown = !showScoreBreakdown"
            class="text-[11px] text-sky-400 hover:text-sky-300 flex items-center gap-1 font-medium"
          >
            <span>{{ showScoreBreakdown ? 'Hide' : 'Explain' }} Score Calculation (No Arbitrary Weights)</span>
            <ChevronDown :class="['w-3.5 h-3.5 transition-transform', showScoreBreakdown ? 'rotate-180' : '']" />
          </button>

          <div v-if="showScoreBreakdown" class="mt-2 p-3 rounded-lg bg-slate-900/90 border border-slate-800 text-xs font-mono space-y-1">
            <div
              v-for="(line, idx) in report?.score_breakdown || []"
              :key="idx"
              :class="[
                line.startsWith('Base') ? 'text-emerald-400 font-bold' :
                line.startsWith('BLOCKER') ? 'text-rose-400 font-bold' :
                line.startsWith('-') ? 'text-amber-300' : 'text-slate-300'
              ]"
            >
              {{ line }}
            </div>
          </div>
        </div>
      </div>

      <!-- 3. CATEGORY SELECTOR TABS -->
      <div class="px-6 py-3 border-b border-white/[0.06] bg-slate-900/30 flex space-x-2 overflow-x-auto flex-shrink-0 scrollbar-none">
        <button
          v-for="(catKey) in categoryKeys"
          :key="catKey"
          @click="selectedCategoryKey = catKey"
          :class="[
            'px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition flex items-center gap-1.5 border',
            selectedCategoryKey === catKey
              ? 'bg-sky-500/10 text-sky-300 border-sky-500/30 shadow-sm'
              : 'bg-slate-800/40 text-slate-400 border-transparent hover:bg-slate-800 hover:text-slate-200'
          ]"
        >
          <span :class="['w-2 h-2 rounded-full', getCategoryDotColor(categories[catKey]?.status)]"></span>
          <span>{{ categories[catKey]?.name || catKey }}</span>
          <span class="font-mono text-[10px] opacity-75">({{ categories[catKey]?.score }}%)</span>
        </button>
      </div>

      <!-- 4. ACTIVE CATEGORY DETAILS BODY -->
      <div class="flex-1 p-6 overflow-y-auto space-y-5">
        <div v-if="activeCategory" class="space-y-4">
          <!-- Category Title Bar -->
          <div class="flex items-center justify-between pb-3 border-b border-slate-800">
            <div>
              <h3 class="text-sm font-bold text-white flex items-center gap-2">
                <span>{{ activeCategory.name }}</span>
                <span :class="['px-2 py-0.5 rounded text-[10px] font-bold uppercase border', getCategoryBadgeClass(activeCategory.status)]">
                  {{ activeCategory.status }}
                </span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">
                Category Score: <strong class="text-white font-mono">{{ activeCategory.score }}/100</strong>
              </p>
            </div>

            <!-- Key Metrics Tag -->
            <div v-if="activeCategory.metrics" class="flex flex-wrap gap-1.5 justify-end">
              <span
                v-for="(val, key) in activeCategory.metrics"
                :key="key"
                class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono text-[10px] border border-slate-700"
              >
                {{ key }}: {{ val }}
              </span>
            </div>
          </div>

          <!-- BLOCKING ISSUES (ERRORS) -->
          <div v-if="activeCategory.issues && activeCategory.issues.length > 0" class="space-y-2.5">
            <h4 class="text-xs font-bold text-rose-400 uppercase tracking-wider flex items-center gap-1.5">
              <AlertOctagon class="w-4 h-4" />
              <span>Blocking Issues ({{ activeCategory.issues.length }})</span>
            </h4>

            <div
              v-for="(issue, idx) in activeCategory.issues"
              :key="idx"
              class="p-3.5 rounded-xl bg-rose-950/20 border border-rose-500/30 space-y-2"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="space-y-1">
                  <div class="flex items-center gap-2">
                    <span class="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 font-mono text-[10px] font-bold">
                      {{ issue.code }}
                    </span>
                    <span class="text-xs font-semibold text-white">{{ issue.message }}</span>
                  </div>
                </div>

                <!-- Deep Link Pill -->
                <div class="flex items-center gap-1 flex-shrink-0">
                  <button
                    v-if="issue.node_id"
                    @click="$emit('highlightNode', issue.node_id)"
                    class="px-2 py-1 rounded bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 font-mono text-[10px] flex items-center gap-1 border border-amber-500/40 transition"
                    title="Focus and highlight this node in the blueprint DAG"
                  >
                    <Crosshair class="w-3 h-3" />
                    <span>Node: {{ issue.node_id }}</span>
                  </button>

                  <button
                    v-if="issue.field"
                    @click="$emit('inspectField', issue.field)"
                    class="px-2 py-1 rounded bg-sky-500/20 text-sky-300 hover:bg-sky-500/30 font-mono text-[10px] flex items-center gap-1 border border-sky-500/40 transition"
                    title="Inspect parameter field"
                  >
                    <Sliders class="w-3 h-3" />
                    <span>Field: {{ issue.field }}</span>
                  </button>
                </div>
              </div>

              <!-- Suggested Fix -->
              <div v-if="issue.suggested_fix" class="text-xs text-slate-300 flex items-center gap-1.5 bg-slate-900/80 p-2 rounded-lg border border-slate-800">
                <Wrench class="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
                <span><strong>Fix:</strong> {{ issue.suggested_fix }}</span>
              </div>
            </div>
          </div>

          <!-- ADVISORY WARNINGS -->
          <div v-if="activeCategory.warnings && activeCategory.warnings.length > 0" class="space-y-2.5">
            <h4 class="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center gap-1.5">
              <AlertTriangle class="w-4 h-4" />
              <span>Advisory Warnings ({{ activeCategory.warnings.length }})</span>
            </h4>

            <div
              v-for="(warn, idx) in activeCategory.warnings"
              :key="idx"
              class="p-3.5 rounded-xl bg-amber-950/20 border border-amber-500/30 space-y-2"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="space-y-1">
                  <div class="flex items-center gap-2">
                    <span class="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-mono text-[10px] font-bold">
                      {{ warn.code }}
                    </span>
                    <span class="text-xs font-medium text-slate-200">{{ warn.message }}</span>
                  </div>
                </div>

                <!-- Deep Link Pill -->
                <div class="flex items-center gap-1 flex-shrink-0">
                  <button
                    v-if="warn.node_id"
                    @click="$emit('highlightNode', warn.node_id)"
                    class="px-2 py-1 rounded bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 font-mono text-[10px] flex items-center gap-1 border border-amber-500/40 transition"
                    title="Focus and highlight this node in the blueprint DAG"
                  >
                    <Crosshair class="w-3 h-3" />
                    <span>Node: {{ warn.node_id }}</span>
                  </button>

                  <button
                    v-if="warn.field"
                    @click="$emit('inspectField', warn.field)"
                    class="px-2 py-1 rounded bg-sky-500/20 text-sky-300 hover:bg-sky-500/30 font-mono text-[10px] flex items-center gap-1 border border-sky-500/40 transition"
                  >
                    <Sliders class="w-3 h-3" />
                    <span>Field: {{ warn.field }}</span>
                  </button>
                </div>
              </div>

              <!-- Suggested Fix -->
              <div v-if="warn.suggested_fix" class="text-xs text-slate-300 flex items-center gap-1.5 bg-slate-900/80 p-2 rounded-lg border border-slate-800">
                <CheckCircle2 class="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                <span><strong>Recommendation:</strong> {{ warn.suggested_fix }}</span>
              </div>
            </div>
          </div>

          <!-- ZERO DEFECTS STATE -->
          <div
            v-if="(!activeCategory.issues || activeCategory.issues.length === 0) && (!activeCategory.warnings || activeCategory.warnings.length === 0)"
            class="p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/30 flex items-center gap-3 text-emerald-300 text-xs"
          >
            <CheckCircle2 class="w-5 h-5 text-emerald-400 flex-shrink-0" />
            <div>
              <p class="font-bold text-white">All Checks Passed</p>
              <p class="text-slate-300 mt-0.5">This category satisfies all actuarial standards and computational requirements.</p>
            </div>
          </div>

          <!-- RECOMMENDATIONS LIST -->
          <div v-if="activeCategory.recommendations && activeCategory.recommendations.length > 0" class="space-y-2">
            <h4 class="text-xs font-bold text-sky-400 uppercase tracking-wider flex items-center gap-1.5">
              <Lightbulb class="w-4 h-4" />
              <span>Actuarial Guidance &amp; Best Practices</span>
            </h4>

            <ul class="space-y-1.5">
              <li
                v-for="(rec, idx) in activeCategory.recommendations"
                :key="idx"
                class="text-xs text-slate-300 flex items-start gap-2 bg-slate-900/50 p-2.5 rounded-lg border border-slate-800/80"
              >
                <ArrowRight class="w-3.5 h-3.5 text-sky-400 flex-shrink-0 mt-0.5" />
                <span>{{ rec }}</span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- 5. DRAWER FOOTER -->
      <div class="px-6 py-4 border-t border-white/[0.08] bg-slate-900/70 flex items-center justify-between flex-shrink-0">
        <div class="text-[11px] text-slate-400">
          Evaluated at {{ formatTimestamp(report?.created_at) }}
        </div>
        <div class="flex items-center space-x-3">
          <button
            @click="$emit('close')"
            class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import {
  X,
  RefreshCw,
  ShieldCheck,
  AlertTriangle,
  AlertOctagon,
  CheckCircle2,
  Info,
  ChevronDown,
  Crosshair,
  Sliders,
  Wrench,
  Lightbulb,
  ArrowRight,
} from 'lucide-vue-next'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false,
  },
  report: {
    type: Object,
    default: null,
  },
  loading: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['close', 'recheck', 'highlightNode', 'inspectField'])

const showScoreBreakdown = ref(false)
const selectedCategoryKey = ref('structure')

const categoryKeys = [
  'structure',
  'data',
  'assumptions',
  'validation',
  'coverage',
  'reproducibility',
  'configuration',
]

const categories = computed(() => props.report?.categories || {})

const activeCategory = computed(() => {
  return categories.value[selectedCategoryKey.value] || null
})

const statusLabel = computed(() => {
  if (props.report?.overall_status === 'PASS') return 'Production Ready'
  if (props.report?.overall_status === 'WARNING') return 'Ready with Warnings'
  return 'Not Ready (Blocked)'
})

const scoreBadgeStyle = computed(() => {
  if (props.report?.overall_status === 'PASS') {
    return 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
  }
  if (props.report?.overall_status === 'WARNING') {
    return 'bg-amber-500/10 border-amber-500/30 text-amber-400'
  }
  return 'bg-rose-500/10 border-rose-500/30 text-rose-400'
})

const statusBadgeStyle = computed(() => {
  if (props.report?.overall_status === 'PASS') {
    return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
  }
  if (props.report?.overall_status === 'WARNING') {
    return 'bg-amber-500/20 text-amber-300 border-amber-500/40'
  }
  return 'bg-rose-500/20 text-rose-300 border-rose-500/40'
})

function getCategoryDotColor(status) {
  if (status === 'PASS') return 'bg-emerald-400'
  if (status === 'WARNING') return 'bg-amber-400'
  return 'bg-rose-400'
}

function getCategoryBadgeClass(status) {
  if (status === 'PASS') return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
  if (status === 'WARNING') return 'bg-amber-500/20 text-amber-300 border-amber-500/40'
  return 'bg-rose-500/20 text-rose-300 border-rose-500/40'
}

function formatTimestamp(ts) {
  if (!ts) return 'just now'
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>
