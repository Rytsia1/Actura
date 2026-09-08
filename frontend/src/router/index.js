import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import MainDashboard from '../views/MainDashboard.vue'
import TermsOfService from '../views/TermsOfService.vue'
import PrivacyPolicy from '../views/PrivacyPolicy.vue'
import GuidedModeView from '../views/GuidedModeView.vue'
import AssumptionLibraryView from '../views/AssumptionLibraryView.vue'
import ScenarioManagementView from '../views/ScenarioManagementView.vue'
import SensitivityAnalysisView from '../views/SensitivityAnalysisView.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
  },
  {
    path: '/',
    name: 'Dashboard',
    component: MainDashboard,
    meta: { requiresAuth: true }
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
  routes: routes.map(route => {
    // Apply requiresAuth to all routes except login, terms, privacy
    if (!['Login', 'Terms', 'Privacy'].includes(route.name)) {
      return { ...route, meta: { ...route.meta, requiresAuth: true } }
    }
    return route
  }),
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) {
    next({ name: 'Login' })
  } else if (to.name === 'Login' && token) {
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

export default router
