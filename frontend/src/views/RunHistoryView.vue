<template>
  <div class="run-history-container">
    <div class="header">
      <h2>Valuation Run History</h2>
      <p>Persistent record of all executed valuations and simulations.</p>
    </div>

    <div class="actions">
      <button class="btn btn-primary" @click="loadJobs" :disabled="loading">
        <span v-if="loading">Refreshing...</span>
        <span v-else>Refresh</span>
      </button>
      <button
        class="btn btn-compare"
        @click="goToCompare"
      >
        <span v-if="selectedForCompare.length === 2">Compare Selected (2)</span>
        <span v-else-if="selectedForCompare.length === 1">Compare (1 Selected)</span>
        <span v-else>Compare Runs</span>
      </button>
    </div>

    <div v-if="error" class="error-banner">
      {{ error }}
    </div>

    <div class="table-container">
      <table class="run-table">
        <thead>
          <tr>
            <th style="width: 40px; text-align: center;">Select</th>
            <th>Run ID</th>
            <th>Status</th>
            <th>Type</th>
            <th>Model Version</th>
            <th>Engine</th>
            <th>Created At</th>
            <th>Completed At</th>
            <th>Progress</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="jobs.length === 0 && !loading">
            <td colspan="10" class="empty-state">No valuation runs found.</td>
          </tr>
          <tr v-for="job in jobs" :key="job.job_id">
            <td style="text-align: center;">
              <input
                type="checkbox"
                :checked="selectedForCompare.includes(job.job_id)"
                @change="toggleSelect(job.job_id)"
                class="compare-checkbox"
                :disabled="job.status !== 'COMPLETED'"
                title="Select run for side-by-side comparison"
              />
            </td>
            <td class="font-mono text-sm" :title="job.job_id">{{ shortenId(job.job_id) }}</td>
            <td>
              <span :class="['status-badge', job.status.toLowerCase()]">{{ job.status }}</span>
            </td>
            <td>
              {{ getValuationType(job) }}
            </td>
            <td>{{ getModelVersion(job) }}</td>
            <td>{{ getEngineVersion(job) }}</td>
            <td>{{ formatDate(job.created_at) }}</td>
            <td>{{ formatDate(job.updated_at) }}</td>
            <td>
              <div class="progress-bar-container">
                <div class="progress-bar" :style="{ width: `${job.progress}%` }"></div>
              </div>
              <span class="progress-text">{{ job.progress.toFixed(0) }}%</span>
            </td>
            <td style="white-space: nowrap;">
              <button class="btn btn-sm btn-outline" @click="viewDetails(job)">Details</button>
              <button
                class="btn btn-sm btn-outline-compare"
                style="margin-left: 0.35rem;"
                @click="compareSingleRun(job.job_id)"
                :disabled="job.status !== 'COMPLETED'"
              >
                Compare
              </button>
              <div class="export-dropdown" style="display: inline-block; position: relative; margin-left: 0.35rem;">
                <button
                  class="btn btn-sm btn-outline-export"
                  :disabled="job.status !== 'COMPLETED'"
                  @click.stop="toggleExportMenu(job.job_id)"
                  title="Export valuation results"
                >
                  Export ▾
                </button>
                <div v-if="activeExportJobId === job.job_id" class="export-menu" @click.stop>
                  <button class="export-item" @click="handleExport(job.job_id, 'xlsx')">
                    <span class="export-icon">📊</span> Excel (.xlsx)
                  </button>
                  <button class="export-item" @click="handleExport(job.job_id, 'csv')">
                    <span class="export-icon">📄</span> CSV (.csv)
                  </button>
                  <button class="export-item" @click="handleExport(job.job_id, 'csv-zip')">
                    <span class="export-icon">📦</span> CSV Bundle (.zip)
                  </button>
                  <button class="export-item" @click="handleExport(job.job_id, 'json')">
                    <span class="export-icon">⚙️</span> JSON (.json)
                  </button>
                </div>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Details Modal -->
    <div v-if="selectedJob" class="modal-backdrop" @click.self="selectedJob = null">
      <div class="modal-content">
        <div class="modal-header">
          <div>
            <h3 style="margin-bottom: 0.25rem;">Run Details</h3>
            <span class="font-mono text-xs text-muted">{{ selectedJob.job_id }}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <button
              v-if="selectedJob.status === 'COMPLETED'"
              class="btn btn-sm btn-export"
              @click="handleExport(selectedJob.job_id, 'xlsx')"
              title="Export all 9 logical sheets to Excel"
            >
              📊 Excel (.xlsx)
            </button>
            <button
              v-if="selectedJob.status === 'COMPLETED'"
              class="btn btn-sm btn-outline"
              @click="handleExport(selectedJob.job_id, 'csv')"
              title="Export full multi-section CSV"
            >
              📄 CSV
            </button>
            <button
              v-if="selectedJob.status === 'COMPLETED'"
              class="btn btn-sm btn-outline"
              @click="handleExport(selectedJob.job_id, 'json')"
              title="Export structured JSON"
            >
              ⚙️ JSON
            </button>
            <button
              class="btn btn-sm btn-compare"
              @click="compareSingleRun(selectedJob.job_id)"
              :disabled="selectedJob.status !== 'COMPLETED'"
            >
              Compare This Run
            </button>
            <button class="btn-close" @click="selectedJob = null">&times;</button>
          </div>
        </div>
        <div class="modal-body">
          <div class="detail-grid">
            <div class="detail-item">
              <span class="label">Job ID</span>
              <span class="value font-mono">{{ selectedJob.job_id }}</span>
            </div>
            <div class="detail-item">
              <span class="label">Status</span>
              <span :class="['status-badge', selectedJob.status.toLowerCase()]">{{ selectedJob.status }}</span>
            </div>
            <div class="detail-item">
              <span class="label">Type</span>
              <span class="value">{{ getValuationType(selectedJob) }}</span>
            </div>
            <div class="detail-item">
              <span class="label">Total Paths</span>
              <span class="value">{{ selectedJob.total_paths }}</span>
            </div>
            <div class="detail-item">
              <span class="label">Completed Paths</span>
              <span class="value">{{ selectedJob.completed_paths }}</span>
            </div>
            <div class="detail-item">
              <span class="label">Created</span>
              <span class="value">{{ formatDate(selectedJob.created_at) }}</span>
            </div>
            <div class="detail-item">
              <span class="label">Last Updated</span>
              <span class="value">{{ formatDate(selectedJob.updated_at) }}</span>
            </div>
          </div>

          <div class="detail-section" v-if="selectedJob.run_metadata">
            <h4>Run Metadata</h4>
            <pre class="json-viewer">{{ JSON.stringify(selectedJob.run_metadata, null, 2) }}</pre>
          </div>
          
          <div class="detail-section" v-if="selectedJob.original_request">
            <h4>Configuration</h4>
            <pre class="json-viewer">{{ JSON.stringify(selectedJob.original_request, null, 2) }}</pre>
          </div>

          <div class="detail-section" v-if="selectedJob.result">
            <h4>Results</h4>
            <pre class="json-viewer">{{ typeof selectedJob.result === 'string' ? selectedJob.result : JSON.stringify(selectedJob.result, null, 2) }}</pre>
          </div>

          <div class="detail-section" v-if="selectedJob.error">
            <h4>Error Information</h4>
            <div class="error-box">{{ selectedJob.error }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchJobs, downloadValuationExport } from '../services/actuaryApi'

const router = useRouter()
const jobs = ref([])
const loading = ref(false)
const error = ref(null)
const selectedJob = ref(null)
const selectedForCompare = ref([])
const activeExportJobId = ref(null)
const exporting = ref(false)

let pollInterval = null

const toggleSelect = (jobId) => {
  if (selectedForCompare.value.includes(jobId)) {
    selectedForCompare.value = selectedForCompare.value.filter((id) => id !== jobId)
  } else {
    if (selectedForCompare.value.length >= 2) {
      selectedForCompare.value = [selectedForCompare.value[1], jobId]
    } else {
      selectedForCompare.value.push(jobId)
    }
  }
}

const compareSingleRun = (jobId) => {
  router.push({
    path: '/compare',
    query: { runA: jobId },
  })
}

const goToCompare = () => {
  if (selectedForCompare.value.length === 2) {
    router.push({
      path: '/compare',
      query: {
        runA: selectedForCompare.value[0],
        runB: selectedForCompare.value[1],
      },
    })
  } else if (selectedForCompare.value.length === 1) {
    router.push({
      path: '/compare',
      query: { runA: selectedForCompare.value[0] },
    })
  } else {
    router.push('/compare')
  }
}

const loadJobs = async () => {
  loading.value = true
  error.value = null
  try {
    const res = await fetchJobs(100)
    jobs.value = res.data
  } catch (err) {
    console.error('Failed to load run history', err)
    error.value = err.message || 'Failed to load run history. Please try again later.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadJobs()
  pollInterval = setInterval(loadJobs, 5000)
  window.addEventListener('click', closeExportMenu)
})

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
  window.removeEventListener('click', closeExportMenu)
})

const toggleExportMenu = (jobId) => {
  activeExportJobId.value = activeExportJobId.value === jobId ? null : jobId
}

const closeExportMenu = () => {
  activeExportJobId.value = null
}

const handleExport = async (jobId, format) => {
  try {
    exporting.value = true
    await downloadValuationExport(jobId, format)
  } catch (err) {
    console.error('Export failed:', err)
    alert(`Failed to export valuation results: ${err.message || err}`)
  } finally {
    exporting.value = false
    activeExportJobId.value = null
  }
}

const shortenId = (id) => {
  if (!id) return ''
  return id.substring(0, 8) + '...'
}

const formatDate = (timestamp) => {
  if (!timestamp) return 'N/A'
  return new Date(timestamp * 1000).toLocaleString()
}

const getValuationType = (job) => {
  if (job.run_metadata && job.run_metadata.valuation_type) {
    return job.run_metadata.valuation_type
  }
  return 'Unknown'
}

const getModelVersion = (job) => {
  if (job.original_request && job.original_request.contract_id) {
    return job.original_request.contract_id
  }
  return 'N/A'
}

const getEngineVersion = (job) => {
  if (job.run_metadata && job.run_metadata.engine_version) {
    return job.run_metadata.engine_version
  }
  return 'N/A'
}

const viewDetails = (job) => {
  selectedJob.value = job
  // Try to parse result if it is stringified JSON
  if (typeof selectedJob.value.result === 'string') {
    try {
      selectedJob.value.result = JSON.parse(selectedJob.value.result)
    } catch (e) {
      // Ignore parse error
    }
  }
}
</script>

<style scoped>
.run-history-container {
  padding: 1.5rem;
  background-color: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  color: var(--text-primary);
}

.header {
  margin-bottom: 1.5rem;
}

.header h2 {
  margin: 0 0 0.5rem 0;
  color: var(--primary);
}

.header p {
  margin: 0;
  color: var(--text-secondary);
}

.actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1rem;
}

.error-banner {
  background-color: rgba(239, 68, 68, 0.1);
  color: var(--danger);
  padding: 1rem;
  border-radius: var(--radius);
  margin-bottom: 1rem;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.table-container {
  overflow-x: auto;
  border-radius: var(--radius);
  border: 1px solid var(--border);
}

.run-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.run-table th,
.run-table td {
  padding: 1rem;
  border-bottom: 1px solid var(--border);
}

.run-table th {
  background-color: var(--surface-hover);
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.run-table tbody tr:hover {
  background-color: var(--surface-hover);
}

.empty-state {
  text-align: center;
  padding: 3rem !important;
  color: var(--text-secondary);
  font-style: italic;
}

.font-mono {
  font-family: 'Fira Code', monospace;
}

.text-sm {
  font-size: 0.875rem;
}

.status-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.status-badge.completed {
  background-color: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.status-badge.running,
.status-badge.processing {
  background-color: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.status-badge.queued {
  background-color: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.status-badge.failed {
  background-color: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.status-badge.cancelled {
  background-color: rgba(107, 114, 128, 0.1);
  color: #6b7280;
}

.progress-bar-container {
  width: 100%;
  height: 6px;
  background-color: var(--border);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 0.25rem;
}

.progress-bar {
  height: 100%;
  background-color: var(--primary);
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

/* Modal Styles */
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-content {
  background-color: var(--surface);
  border-radius: var(--radius-lg);
  width: 90%;
  max-width: 800px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--border);
}

.modal-header {
  padding: 1.5rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  margin: 0;
  color: var(--text-primary);
}

.btn-close {
  background: transparent;
  border: none;
  font-size: 1.5rem;
  color: var(--text-secondary);
  cursor: pointer;
  line-height: 1;
}

.btn-close:hover {
  color: var(--text-primary);
}

.modal-body {
  padding: 1.5rem;
  overflow-y: auto;
  flex: 1;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.5rem;
  margin-bottom: 2rem;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.detail-item .label {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.detail-item .value {
  font-weight: 500;
  color: var(--text-primary);
}

.detail-section {
  margin-top: 1.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1.5rem;
}

.detail-section h4 {
  margin: 0 0 1rem 0;
  color: var(--primary);
  font-size: 1.1rem;
}

.json-viewer {
  background-color: var(--background);
  padding: 1rem;
  border-radius: var(--radius);
  font-family: 'Fira Code', monospace;
  font-size: 0.875rem;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid var(--border);
}

.error-box {
  background-color: rgba(239, 68, 68, 0.1);
  color: var(--danger);
  padding: 1rem;
  border-radius: var(--radius);
  border: 1px solid rgba(239, 68, 68, 0.2);
  white-space: pre-wrap;
  font-family: 'Fira Code', monospace;
  font-size: 0.875rem;
}

.btn-compare {
  background-color: #6366f1;
  color: white;
  margin-left: 0.75rem;
  border-radius: var(--radius);
  padding: 0.5rem 1rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: background-color 0.2s;
}

.btn-compare:hover {
  background-color: #4f46e5;
}

.btn-outline-compare {
  border: 1px solid #6366f1;
  color: #818cf8;
  background: transparent;
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background-color 0.2s;
}

.btn-outline-compare:hover:not(:disabled) {
  background-color: rgba(99, 102, 241, 0.1);
}

.btn-outline-compare:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.compare-checkbox {
  cursor: pointer;
  accent-color: #6366f1;
  width: 16px;
  height: 16px;
}

/* Valuation Export Styles */
.btn-outline-export {
  border: 1px solid #10b981;
  color: #10b981;
  background: transparent;
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-outline-export:hover:not(:disabled) {
  background-color: rgba(16, 185, 129, 0.1);
}

.btn-outline-export:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-export {
  background-color: #10b981;
  color: white;
  border-radius: var(--radius);
  padding: 0.35rem 0.75rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  transition: background-color 0.2s;
}

.btn-export:hover {
  background-color: #059669;
}

.export-menu {
  position: absolute;
  right: 0;
  top: 100%;
  margin-top: 0.25rem;
  background: var(--surface, #1e293b);
  border: 1px solid var(--border, #334155);
  border-radius: var(--radius, 6px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5);
  z-index: 50;
  min-width: 160px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.export-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.8125rem;
  color: var(--text-primary, #f8fafc);
  background: transparent;
  border: none;
  width: 100%;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s;
}

.export-item:hover {
  background-color: rgba(255, 255, 255, 0.08);
  color: #10b981;
}

.export-icon {
  font-size: 0.9rem;
}
</style>
