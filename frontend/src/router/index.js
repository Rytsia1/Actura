import { createRouter, createWebHistory } from 'vue-router'
import MainDashboard from '../views/MainDashboard.vue'
import TermsOfService from '../views/TermsOfService.vue'
import PrivacyPolicy from '../views/PrivacyPolicy.vue'
import GuidedModeView from '../views/GuidedModeView.vue'
import AssumptionLibraryView from '../views/AssumptionLibraryView.vue'
import ScenarioManagementView from '../views/ScenarioManagementView.vue'
import SensitivityAnalysisView from '../views/SensitivityAnalysisView.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: MainDashboard,
  },
  {
    path: '/guided',
    name: 'GuidedMode',
    component: GuidedModeView,
  },
  {
    path: '/assumptions',
    name: 'Assumptions',
    component: AssumptionLibraryView,
  },
  {
    path: '/scenarios',
    name: 'Scenarios',
    component: ScenarioManagementView,
  },
  {
    path: '/sensitivity',
    name: 'Sensitivity',
    component: SensitivityAnalysisView,
  },
  {
    path: '/history',
    name: 'History',
    component: () => import('../views/RunHistoryView.vue'),
  },
  {
    path: '/compare',
    name: 'Compare',
    component: () => import('../views/RunComparisonView.vue'),
  },
  {
    path: '/terms',
    name: 'Terms',
    component: TermsOfService,
  },
  {
    path: '/privacy',
    name: 'Privacy',
    component: PrivacyPolicy,
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
