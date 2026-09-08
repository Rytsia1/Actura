import { createRouter, createWebHistory } from 'vue-router'
import MainDashboard from '../views/MainDashboard.vue'
import TermsOfService from '../views/TermsOfService.vue'
import PrivacyPolicy from '../views/PrivacyPolicy.vue'
import GuidedModeView from '../views/GuidedModeView.vue'
import AssumptionLibraryView from '../views/AssumptionLibraryView.vue'

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
