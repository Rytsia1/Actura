<template>
  <div class="min-h-screen flex items-center justify-center bg-slate-900 py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8 bg-slate-800 p-10 rounded-xl shadow-2xl border border-slate-700">
      <div>
        <h2 class="mt-6 text-center text-3xl font-extrabold text-white">Actura</h2>
        <p class="mt-2 text-center text-sm text-slate-400">
          Sign in to the Actuarial Valuation Engine
        </p>
      </div>
      <form class="mt-8 space-y-6" @submit.prevent="handleLogin">
        <div class="rounded-md shadow-sm space-y-4">
          <div>
            <label for="username" class="sr-only">Username</label>
            <input
              id="username"
              name="username"
              type="text"
              required
              v-model="username"
              class="appearance-none rounded-lg relative block w-full px-3 py-2 border border-slate-600 bg-slate-700 placeholder-slate-400 text-white focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 focus:z-10 sm:text-sm"
              placeholder="Username"
            />
          </div>
          <div>
            <label for="password" class="sr-only">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              required
              v-model="password"
              class="appearance-none rounded-lg relative block w-full px-3 py-2 border border-slate-600 bg-slate-700 placeholder-slate-400 text-white focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 focus:z-10 sm:text-sm"
              placeholder="Password"
            />
          </div>
        </div>

        <div v-if="error" class="text-red-400 text-sm text-center font-medium bg-red-400/10 py-2 rounded">
          {{ error }}
        </div>

        <div>
          <button
            type="submit"
            :disabled="loading"
            class="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <span class="absolute left-0 inset-y-0 flex items-center pl-3">
              <svg class="h-5 w-5 text-indigo-500 group-hover:text-indigo-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd" />
              </svg>
            </span>
            {{ loading ? 'Authenticating...' : 'Sign In' }}
          </button>
        </div>
      </form>
      
      <div class="text-xs text-center text-slate-500 pt-4 border-t border-slate-700">
        <p>System Seeded Accounts:</p>
        <p class="mt-1">Admin: <code>admin</code> / <code>admin</code></p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

function decodeJwtPayload(token) {
  try {
    const parts = (token || '').split('.')
    if (parts.length < 2) return {}
    const base64Url = parts[1]
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    )
    return JSON.parse(jsonPayload)
  } catch (e) {
    console.warn('Failed to parse JWT payload:', e)
    return {}
  }
}

const handleLogin = async () => {
  loading.value = true
  error.value = ''
  
  try {
    const formData = new FormData()
    formData.append('username', username.value)
    formData.append('password', password.value)
    
    // Direct axios call to avoid httpClient interceptor loop if 401 occurs
    const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
    const url = BASE_URL ? `${BASE_URL}/api/v1/auth/token` : '/api/v1/auth/token'
    
    const response = await axios.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
    
    const token = response.data.access_token
    const payload = decodeJwtPayload(token)
    const user = { role: payload.role, org_id: payload.org_id, id: payload.sub }

    // Synchronize Pinia reactive auth store & localStorage
    authStore.setAuth(token, user)
    
    router.push('/')
  } catch (err) {
    if (err.response && err.response.status === 401) {
      error.value = 'Invalid username or password'
    } else {
      error.value = 'An error occurred during sign in. Please check backend connection.'
    }
  } finally {
    loading.value = false
  }
}
</script>
