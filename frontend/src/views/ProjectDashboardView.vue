<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { projectApi } from '../services/projectApi'
import { useProjectStore } from '../stores/useProjectStore'
import EmptyState from '../components/EmptyState.vue'
import LoadingOverlay from '../components/LoadingOverlay.vue'
import { useErrorStore } from '../stores/useErrorStore'
import ErrorBanner from '../components/ErrorBanner.vue'

const router = useRouter()
const projectStore = useProjectStore()
const errorStore = useErrorStore()

const projects = ref([])
const isLoading = ref(true)

const showModeModal = ref(false)
const selectedProject = ref(null)

onMounted(async () => {
  projectStore.clearStore()
  errorStore.clearError()
  await loadProjects()
})

const loadProjects = async () => {
  try {
    isLoading.value = true
    const response = await projectApi.list()
    projects.value = response.data || response // depending on axios setup
  } catch (err) {
    console.error("Failed to load projects", err)
  } finally {
    isLoading.value = false
  }
}

const createProject = async () => {
  const name = prompt('Enter project name:')
  if (!name) return
  
  try {
    isLoading.value = true
    const response = await projectApi.create(name)
    const newProject = response.data || response
    router.push(`/wizard/${newProject.id}`)
  } catch (err) {
    console.error("Failed to create project", err)
  } finally {
    isLoading.value = false
  }
}

const openProject = (project) => {
  selectedProject.value = project
  showModeModal.value = true
}

const proceedToBuilder = () => {
  if (!selectedProject.value) return
  projectStore.setCurrentProject(selectedProject.value)
  router.push(`/wizard/${selectedProject.value.id}`)
}

const proceedToSandbox = () => {
  if (!selectedProject.value) return
  // We can pass project ID via query or just let the sandbox be standalone
  projectStore.setCurrentProject(selectedProject.value)
  router.push(`/sandbox`)
}

const togglePin = async (project, event) => {
  event.stopPropagation()
  try {
    isLoading.value = true
    await projectApi.update(project.id, { is_pinned: !project.is_pinned })
    await loadProjects()
  } catch (err) {
    console.error(err)
    isLoading.value = false
  }
}

const renameProject = async (project, event) => {
  event.stopPropagation()
  const newName = prompt('Enter new project name:', project.name)
  if (!newName || newName === project.name) return
  
  try {
    isLoading.value = true
    await projectApi.update(project.id, { name: newName })
    await loadProjects()
  } catch (err) {
    console.error(err)
    isLoading.value = false
  }
}

const deleteProject = async (project, event) => {
  event.stopPropagation()
  const confirmed = confirm(`Are you sure you want to delete "${project.name}"?`)
  if (!confirmed) return
  
  try {
    isLoading.value = true
    await projectApi.delete(project.id)
    await loadProjects()
  } catch (err) {
    console.error(err)
    isLoading.value = false
  }
}
</script>

<template>
  <div class="h-screen w-full bg-[#0B0F19] text-slate-200 flex flex-col font-sans relative">
    
    <ErrorBanner />
    <LoadingOverlay v-if="isLoading" />

    <!-- Header -->
    <header class="h-16 shrink-0 border-b border-white/[0.08] bg-[#0F172A] flex items-center px-6 justify-between">
      <div class="flex items-center gap-3">
        <div class="h-10 w-10 rounded-xl flex-shrink-0 shadow-md border border-white/[0.05] relative overflow-hidden bg-[#070b14]">
          <img src="/logo.jpg" alt="Actura Mascot" class="absolute w-[220%] h-[220%] max-w-none -bottom-[15%] -right-[20%]" />
        </div>
        <div class="min-w-0 flex-1">
          <h1 class="text-sm font-semibold text-white tracking-tight">Actura</h1>
          <p class="text-xs text-slate-500 font-medium truncate">Actuarial Valuation & Risk Platform</p>
        </div>
      </div>
      
      <div class="flex items-center gap-4">
        <button @click="createProject" class="h-9 px-4 rounded-md bg-indigo-500 hover:bg-indigo-600 text-white text-sm font-medium transition-colors shadow-lg shadow-indigo-500/20">
          New Project
        </button>
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 overflow-auto p-8 relative">
      <div v-if="!isLoading && projects.length === 0" class="h-full flex items-center justify-center">
        <EmptyState
          title="No projects yet"
          description="Create your first project to start building actuarial valuations and simulating cash flows."
        >
          <template #icon>
            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-folder-plus"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/><path d="M12 10v6"/><path d="M9 13h6"/></svg>
          </template>
        </EmptyState>
      </div>

      <div v-else-if="!isLoading" class="max-w-6xl mx-auto">
        <h2 class="text-2xl font-semibold text-white mb-6">My Projects</h2>
        
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <div 
            v-for="project in projects" 
            :key="project.id"
            @click="openProject(project)"
            class="group cursor-pointer rounded-xl border border-white/[0.08] bg-[#0F172A] p-6 hover:border-indigo-500/50 hover:bg-[#151f38] transition-all duration-300 hover:shadow-xl hover:shadow-indigo-500/10 flex flex-col h-48 relative"
          >
            <!-- Pin Indicator -->
            <div v-if="project.is_pinned" class="absolute -top-2 -right-2 bg-indigo-500 rounded-full p-1.5 shadow-lg shadow-indigo-500/30">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="white" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pin"><line x1="12" x2="12" y1="17" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.68V6a3 3 0 0 0-3-3 3 3 0 0 0-3 3v4.68a2 2 0 0 1-1.11 1.87l-1.78.89A2 2 0 0 0 5 15.24Z"/></svg>
            </div>

            <div class="flex items-start justify-between mb-4">
              <h3 class="text-lg font-medium text-slate-200 group-hover:text-indigo-400 transition-colors truncate pr-2">{{ project.name }}</h3>
              
              <!-- Action Menu / Icons -->
              <div class="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <!-- Pin -->
                <button @click="togglePin(project, $event)" class="text-slate-500 hover:text-indigo-400 p-1 rounded hover:bg-white/[0.05]" title="Pin Project">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-pin"><line x1="12" x2="12" y1="17" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.68V6a3 3 0 0 0-3-3 3 3 0 0 0-3 3v4.68a2 2 0 0 1-1.11 1.87l-1.78.89A2 2 0 0 0 5 15.24Z"/></svg>
                </button>
                <!-- Rename -->
                <button @click="renameProject(project, $event)" class="text-slate-500 hover:text-amber-400 p-1 rounded hover:bg-white/[0.05]" title="Rename Project">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-edit-2"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>
                </button>
                <!-- Delete -->
                <button @click="deleteProject(project, $event)" class="text-slate-500 hover:text-rose-400 p-1 rounded hover:bg-white/[0.05]" title="Delete Project">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash-2"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>
                </button>
              </div>
            </div>
            
            <p class="text-slate-400 text-sm flex-1 line-clamp-3">
              {{ project.description || 'No description provided.' }}
            </p>
            
            <div class="mt-4 pt-4 border-t border-white/[0.05] flex items-center justify-between text-xs text-slate-500">
              <span class="flex items-center gap-1.5">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-clock"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                Updated {{ new Date(project.updated_at).toLocaleDateString() }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- Mode Selection Modal -->
    <div v-if="showModeModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div class="bg-[#0F172A] border border-white/[0.1] rounded-2xl p-8 max-w-2xl w-full mx-4 shadow-2xl relative animate-in fade-in zoom-in-95 duration-200">
        <button @click="showModeModal = false" class="absolute top-4 right-4 text-slate-500 hover:text-white transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-x"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
        </button>
        
        <div class="text-center mb-8">
          <h2 class="text-2xl font-semibold text-white tracking-tight mb-2">Open "{{ selectedProject?.name }}"</h2>
          <p class="text-slate-400">Choose your workspace mode for this project. You can always switch modes later.</p>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <!-- Wizard / Blueprint Builder Option -->
          <button @click="proceedToBuilder" class="group relative flex flex-col items-center text-center p-6 rounded-xl border border-white/[0.08] bg-[#151f38] hover:border-indigo-500/50 hover:bg-[#1a2542] transition-all duration-300">
            <div class="h-12 w-12 rounded-full bg-indigo-500/10 flex items-center justify-center text-indigo-400 mb-4 group-hover:scale-110 transition-transform">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-git-merge"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>
            </div>
            <h3 class="text-lg font-medium text-white mb-2">Visual Blueprint Builder</h3>
            <p class="text-sm text-slate-400 leading-relaxed">Design cash flow logic visually using the DAG canvas and step-by-step wizard.</p>
            <div class="absolute inset-0 border-2 border-transparent group-hover:border-indigo-500/30 rounded-xl transition-colors pointer-events-none"></div>
          </button>

          <!-- Legacy Sandbox Option -->
          <button @click="proceedToSandbox" class="group relative flex flex-col items-center text-center p-6 rounded-xl border border-white/[0.08] bg-[#151f38] hover:border-emerald-500/50 hover:bg-[#1a2542] transition-all duration-300">
            <div class="h-12 w-12 rounded-full bg-emerald-500/10 flex items-center justify-center text-emerald-400 mb-4 group-hover:scale-110 transition-transform">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-flask-conical"><path d="M10 2v7.31"/><path d="M14 9.3V1.99"/><path d="M8.5 2h7"/><path d="M14 9.3a6.5 6.5 0 1 1-4 0"/><path d="M5.52 16h12.96"/></svg>
            </div>
            <h3 class="text-lg font-medium text-white mb-2">Legacy Sandbox</h3>
            <p class="text-sm text-slate-400 leading-relaxed">Classic actuarial tools: deterministic models, sensitivity analysis, and IFRS17.</p>
            <div class="absolute inset-0 border-2 border-transparent group-hover:border-emerald-500/30 rounded-xl transition-colors pointer-events-none"></div>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
