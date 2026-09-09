<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { Search, Play, Download, Upload, Clock, Activity, LayoutDashboard, Target } from 'lucide-vue-next'

const emit = defineEmits(['action'])

const containerRef = ref(null)
const searchInput = ref(null)
const searchQuery = ref('')
const isOpen = ref(false)
const selectedIndex = ref(0)

const actions = [
  { id: 'run_valuation', title: 'Run Valuation Engine', subtitle: 'Execute deterministic and stochastic engines', icon: Play, color: 'text-sky-400', group: 'ACTIONS' },
  { id: 'export_csv', title: 'Export Valuation CSV', subtitle: 'Download reserve profiles as CSV', icon: Download, color: 'text-emerald-400', group: 'ACTIONS' },
  { id: 'upload_table', title: 'Upload Mortality Table', subtitle: 'Import custom CSV mortality assumptions', icon: Upload, color: 'text-amber-400', group: 'ACTIONS' },
  { id: 'view_scenarios', title: 'Scenario Workbench', subtitle: 'Define and run assumption scenarios against base models', icon: Activity, color: 'text-indigo-400', group: 'ACTIONS' },
  { id: 'view_history', title: 'View Run History', subtitle: 'See previous valuation parameters', icon: Clock, color: 'text-purple-400', group: 'ACTIONS' },
  { id: 'tab_overview', title: 'Overview Dashboard', subtitle: 'Switch to main summary', icon: LayoutDashboard, color: 'text-slate-400', group: 'NAVIGATION' },
  { id: 'tab_sensitivity', title: 'Sensitivity Analysis', subtitle: 'Switch to stress testing', icon: Target, color: 'text-rose-400', group: 'NAVIGATION' }
]

const filteredActions = computed(() => {
  if (!searchQuery.value) return actions
  const q = searchQuery.value.toLowerCase()
  return actions.filter(a => 
    a.title.toLowerCase().includes(q) || a.subtitle.toLowerCase().includes(q)
  )
})

const groupedActions = computed(() => {
  const groups = {}
  filteredActions.value.forEach(action => {
    if (!groups[action.group]) groups[action.group] = []
    groups[action.group].push(action)
  })
  return groups
})

watch(searchQuery, () => {
  selectedIndex.value = 0
  if (searchQuery.value && !isOpen.value) {
    isOpen.value = true
  }
})

function close() {
  isOpen.value = false
  searchQuery.value = ''
  searchInput.value?.blur()
}

function open() {
  isOpen.value = true
  searchInput.value?.focus()
}

function handleKeydown(e) {
  // Global shortcut to open
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    open()
    return
  }

  if (!isOpen.value) return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIndex.value = (selectedIndex.value + 1) % filteredActions.value.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIndex.value = (selectedIndex.value - 1 + filteredActions.value.length) % filteredActions.value.length
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (filteredActions.value[selectedIndex.value]) {
      executeAction(filteredActions.value[selectedIndex.value])
    }
  } else if (e.key === 'Escape') {
    close()
  }
}

function handleClickOutside(e) {
  if (isOpen.value && containerRef.value && !containerRef.value.contains(e.target)) {
    close()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('click', handleClickOutside)
})

function executeAction(action) {
  emit('action', action.id)
  close()
}

function getGlobalIndex(groupName, idx) {
  let globalIdx = 0
  for (const g of Object.keys(groupedActions.value)) {
    if (g === groupName) {
      return globalIdx + idx
    }
    globalIdx += groupedActions.value[g].length
  }
  return 0
}
</script>

<template>
  <div class="relative w-full" ref="containerRef">
    <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
    <input
      ref="searchInput"
      v-model="searchQuery"
      @focus="open"
      type="text"
      placeholder="⌘K Quick Actions"
      class="input-field pl-9 pr-14 py-2 text-[13px] w-full focus:ring-1 focus:ring-sky-500/50 focus:border-sky-500/50 transition-colors"
    />
    <span class="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded font-mono pointer-events-none">⌘K</span>

    <!-- Dropdown -->
    <div v-if="isOpen" class="absolute top-full left-0 mt-2 w-full min-w-[300px] z-50 bg-[#0B0F19] border border-slate-700 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[400px]">
      <ul v-if="filteredActions.length > 0" class="custom-scrollbar overflow-y-auto py-2" role="listbox">
        <template v-for="(items, group) in groupedActions" :key="group">
          <li class="text-[10px] font-semibold text-slate-500 tracking-wider uppercase px-4 py-2 mt-1 first:mt-0 select-none">
            {{ group }}
          </li>
          <li
            v-for="(action, idx) in items"
            :key="action.id"
            @click="executeAction(action)"
            @mouseenter="selectedIndex = getGlobalIndex(group, idx)"
            :class="[
              'cursor-pointer select-none px-4 py-3 border-l-2 transition-colors',
              selectedIndex === getGlobalIndex(group, idx) ? 'bg-slate-800/80 border-sky-500' : 'border-transparent text-slate-300'
            ]"
            role="option"
            :aria-selected="selectedIndex === getGlobalIndex(group, idx)"
          >
            <div class="flex items-center space-x-3">
              <component :is="action.icon" :class="['h-4 w-4 flex-shrink-0', action.color]" />
              <div class="flex flex-col">
                <span :class="['text-[13px] font-medium', selectedIndex === getGlobalIndex(group, idx) ? 'text-white' : 'text-slate-200']">{{ action.title }}</span>
                <span class="text-[11px] text-slate-400 mt-0.5">{{ action.subtitle }}</span>
              </div>
            </div>
          </li>
        </template>
      </ul>

      <div v-else class="px-6 py-10 text-center text-sm">
        <Search class="mx-auto h-5 w-5 text-slate-500 mb-2" />
        <p class="font-medium text-slate-300">No results found</p>
        <p class="text-[11px] text-slate-500 mt-1">Try searching for a different action.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.custom-scrollbar {
  scrollbar-width: none;
}
.custom-scrollbar::-webkit-scrollbar {
  display: none;
}
</style>
