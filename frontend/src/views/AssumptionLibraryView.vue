<script setup>
import { ref, onMounted, computed } from 'vue'
import {
  fetchAssumptions,
  fetchAssumptionHistory,
  createAssumption,
  createAssumptionVersion,
  updateAssumptionStatus
} from '../services/actuaryApi'
import {
  Database,
  Plus,
  History,
  Edit2,
  Trash2,
  CheckCircle2,
  XCircle,
  Search,
  BookOpen,
  Filter
} from 'lucide-vue-next'

const assumptions = ref([])
const loading = ref(false)
const error = ref(null)

const searchQuery = ref('')
const selectedType = ref('All')

// Modal State
const showModal = ref(false)
const modalMode = ref('create') // 'create' | 'version' | 'view'
const selectedAssumption = ref(null)
const historyRecords = ref([])

const form = ref({
  name: '',
  type: 'mortality',
  description: '',
  source: '',
  effective_date: '',
  parameters: '{}'
})

const ASSUMPTION_TYPES = ['mortality', 'lapse', 'expense', 'interest', 'inflation', 'economic']

async function loadAssumptions() {
  loading.value = true
  error.value = null
  try {
    const res = await fetchAssumptions()
    assumptions.value = Array.isArray(res) ? res : (res?.data || [])
  } catch (err) {
    error.value = 'Failed to load assumptions.'
    console.error(err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadAssumptions()
})

const filteredAssumptions = computed(() => {
  return assumptions.value.filter(a => {
    const matchesSearch = a.name.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
                          a.id.toLowerCase().includes(searchQuery.value.toLowerCase())
    const matchesType = selectedType.value === 'All' || a.type === selectedType.value
    return matchesSearch && matchesType
  })
})

function openCreateModal() {
  modalMode.value = 'create'
  form.value = { name: '', type: 'mortality', description: '', source: '', effective_date: '', parameters: '{}' }
  selectedAssumption.value = null
  showModal.value = true
}

async function openVersionModal(assumption) {
  modalMode.value = 'version'
  selectedAssumption.value = assumption
  form.value = {
    name: assumption.name,
    type: assumption.type,
    description: assumption.description,
    source: assumption.source,
    effective_date: assumption.effective_date,
    parameters: JSON.stringify(assumption.parameters, null, 2)
  }
  showModal.value = true
}

async function viewHistory(assumption) {
  modalMode.value = 'history'
  selectedAssumption.value = assumption
  try {
    const res = await fetchAssumptionHistory(assumption.id)
    historyRecords.value = Array.isArray(res) ? res : (res?.data || [])
    showModal.value = true
  } catch (err) {
    console.error('Failed to load history', err)
  }
}

async function handleSave() {
  try {
    const payload = {
      ...form.value,
      parameters: JSON.parse(form.value.parameters || '{}')
    }
    if (modalMode.value === 'create') {
      await createAssumption(payload)
    } else if (modalMode.value === 'version') {
      await createAssumptionVersion(selectedAssumption.value.id, payload)
    }
    showModal.value = false
    await loadAssumptions()
  } catch (err) {
    alert('Failed to save: ' + (err.response?.data?.detail || err.message))
  }
}

async function toggleStatus(assumption) {
  try {
    const newStatus = assumption.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE'
    await updateAssumptionStatus(assumption.id, newStatus)
    await loadAssumptions()
  } catch (err) {
    alert('Failed to update status.')
  }
}

function formatDate(timestamp) {
  if (!timestamp) return '—'
  const date = typeof timestamp === 'number' ? new Date(timestamp > 1e11 ? timestamp : timestamp * 1000) : new Date(timestamp)
  return isNaN(date.getTime()) ? '—' : date.toLocaleString()
}
</script>

<template>
  <div class="h-full flex flex-col space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
      <div>
        <h1 class="text-2xl font-bold text-white flex items-center space-x-2">
          <Database class="w-6 h-6 text-indigo-400" />
          <span>Assumption Library</span>
        </h1>
        <p class="text-slate-400 text-sm mt-1">Manage version-controlled actuarial parameters.</p>
      </div>
      <button @click="openCreateModal" class="btn-primary flex items-center space-x-2 px-4 py-2">
        <Plus class="w-4 h-4" />
        <span>New Assumption</span>
      </button>
    </div>

    <!-- Filters -->
    <div class="flex flex-wrap items-center gap-4 bg-slate-800/50 p-4 rounded-xl border border-slate-700/50">
      <div class="relative flex-1 min-w-[200px]">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input 
          v-model="searchQuery" 
          type="text" 
          placeholder="Search by name or ID..." 
          class="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-4 py-2 text-sm text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition-all"
        />
      </div>
      <div class="flex items-center space-x-2 text-sm">
        <Filter class="w-4 h-4 text-slate-400" />
        <select v-model="selectedType" class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white outline-none focus:ring-2 focus:ring-indigo-500">
          <option value="All">All Types</option>
          <option v-for="t in ASSUMPTION_TYPES" :key="t" :value="t">{{ t.charAt(0).toUpperCase() + t.slice(1) }}</option>
        </select>
      </div>
    </div>

    <!-- Table -->
    <div class="flex-1 bg-slate-800/30 rounded-xl border border-slate-700/50 overflow-hidden flex flex-col">
      <div class="overflow-x-auto">
        <table class="data-table w-full">
          <thead>
            <tr>
              <th class="w-64">Name</th>
              <th>Type</th>
              <th>Version</th>
              <th>Effective</th>
              <th>Status</th>
              <th>Updated At</th>
              <th class="text-right">Actions</th>
            </tr>
          </thead>
          <tbody v-if="loading">
            <tr><td colspan="7" class="text-center py-8 text-slate-400">Loading assumptions...</td></tr>
          </tbody>
          <tbody v-else-if="filteredAssumptions.length === 0">
            <tr><td colspan="7" class="text-center py-8 text-slate-500">No assumptions found.</td></tr>
          </tbody>
          <tbody v-else>
            <tr v-for="item in filteredAssumptions" :key="item.id" class="hover:bg-slate-800/50">
              <td>
                <div class="font-medium text-white">{{ item.name }}</div>
                <div class="text-xs text-slate-500 font-mono mt-0.5 truncate max-w-[200px]">{{ item.id }}</div>
              </td>
              <td>
                <span class="px-2.5 py-1 text-[10px] uppercase font-bold tracking-wider rounded-full bg-slate-700 text-slate-300">
                  {{ item.type }}
                </span>
              </td>
              <td>
                <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-indigo-500/20 text-indigo-400 text-xs font-bold font-mono">
                  v{{ item.version }}
                </span>
              </td>
              <td class="text-slate-400 text-sm">{{ item.effective_date || '—' }}</td>
              <td>
                <button @click="toggleStatus(item)" class="flex items-center space-x-1 text-xs font-medium px-2 py-1 rounded transition-colors"
                  :class="item.status === 'ACTIVE' ? 'text-emerald-400 hover:bg-emerald-400/10' : 'text-slate-500 hover:bg-slate-500/10'"
                >
                  <component :is="item.status === 'ACTIVE' ? CheckCircle2 : XCircle" class="w-3.5 h-3.5" />
                  <span>{{ item.status }}</span>
                </button>
              </td>
              <td class="text-slate-400 text-sm">{{ formatDate(item.updated_at) }}</td>
              <td class="text-right">
                <div class="flex items-center justify-end space-x-2">
                  <button @click="viewHistory(item)" class="p-1.5 text-slate-400 hover:text-white hover:bg-slate-700 rounded" title="View History">
                    <History class="w-4 h-4" />
                  </button>
                  <button @click="openVersionModal(item)" class="p-1.5 text-sky-400 hover:text-sky-300 hover:bg-sky-400/10 rounded" title="Create New Version">
                    <Edit2 class="w-4 h-4" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Modal Form -->
    <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-2xl flex flex-col max-h-[90vh] overflow-hidden shadow-2xl">
        
        <div class="px-6 py-4 border-b border-slate-800 flex justify-between items-center">
          <h2 class="text-lg font-bold text-white">
            <span v-if="modalMode === 'create'">Create New Assumption</span>
            <span v-else-if="modalMode === 'version'">Create Version {{ selectedAssumption.version + 1 }}</span>
            <span v-else>Assumption History: {{ selectedAssumption.name }}</span>
          </h2>
          <button @click="showModal = false" class="text-slate-400 hover:text-white"><XCircle class="w-5 h-5" /></button>
        </div>

        <div class="p-6 overflow-y-auto" v-if="modalMode !== 'history'">
          <div class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
              <div class="space-y-1">
                <label class="text-xs font-medium text-slate-400">Name</label>
                <input v-model="form.name" type="text" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm outline-none focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div class="space-y-1">
                <label class="text-xs font-medium text-slate-400">Type</label>
                <select v-model="form.type" :disabled="modalMode === 'version'" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50">
                  <option v-for="t in ASSUMPTION_TYPES" :key="t" :value="t">{{ t }}</option>
                </select>
              </div>
            </div>
            
            <div class="space-y-1">
              <label class="text-xs font-medium text-slate-400">Description</label>
              <textarea v-model="form.description" rows="2" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm outline-none focus:ring-1 focus:ring-indigo-500"></textarea>
            </div>

            <div class="grid grid-cols-2 gap-4">
              <div class="space-y-1">
                <label class="text-xs font-medium text-slate-400">Source / Reference</label>
                <input v-model="form.source" type="text" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm outline-none focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div class="space-y-1">
                <label class="text-xs font-medium text-slate-400">Effective Date</label>
                <input v-model="form.effective_date" type="date" class="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm outline-none focus:ring-1 focus:ring-indigo-500 [color-scheme:dark]" />
              </div>
            </div>

            <div class="space-y-1">
              <label class="text-xs font-medium text-slate-400">Parameters (JSON)</label>
              <textarea v-model="form.parameters" rows="6" class="w-full bg-black/50 border border-slate-700 rounded-lg px-3 py-2 text-emerald-400 font-mono text-sm outline-none focus:ring-1 focus:ring-indigo-500"></textarea>
            </div>
          </div>
        </div>

        <!-- History View -->
        <div class="p-0 overflow-y-auto" v-else>
          <table class="w-full text-left text-sm">
            <thead class="bg-slate-800/50 text-slate-400 text-xs uppercase">
              <tr>
                <th class="px-4 py-2">Version</th>
                <th class="px-4 py-2">Effective</th>
                <th class="px-4 py-2">Created At</th>
                <th class="px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800">
              <tr v-for="rec in historyRecords" :key="rec.version" class="hover:bg-slate-800/30">
                <td class="px-4 py-3 font-mono font-bold text-indigo-400">v{{ rec.version }}</td>
                <td class="px-4 py-3 text-slate-300">{{ rec.effective_date || '—' }}</td>
                <td class="px-4 py-3 text-slate-400">{{ formatDate(rec.created_at) }}</td>
                <td class="px-4 py-3">
                  <span class="text-xs font-medium px-2 py-0.5 rounded" :class="rec.status === 'ACTIVE' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-slate-500/10 text-slate-400'">
                    {{ rec.status }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="px-6 py-4 border-t border-slate-800 flex justify-end space-x-3 bg-slate-900/50" v-if="modalMode !== 'history'">
          <button @click="showModal = false" class="px-4 py-2 text-sm font-medium text-slate-300 hover:text-white transition-colors">Cancel</button>
          <button @click="handleSave" class="btn-primary text-sm px-5 py-2">
            {{ modalMode === 'create' ? 'Create Assumption' : 'Save New Version' }}
          </button>
        </div>
      </div>
    </div>

  </div>
</template>
