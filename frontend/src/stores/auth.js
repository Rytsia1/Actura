import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || null)

  const user = ref((() => {
    try {
      const stored = localStorage.getItem('user')
      return stored ? JSON.parse(stored) : null
    } catch {
      return null
    }
  })())

  const isAuthenticated = computed(() => !!token.value)
  const role = computed(() => user.value?.role || 'Viewer')

  const setAuth = (newToken, newUser) => {
    token.value = newToken
    user.value = newUser
    if (newToken) {
      localStorage.setItem('token', newToken)
    } else {
      localStorage.removeItem('token')
    }
    if (newUser) {
      localStorage.setItem('user', JSON.stringify(newUser))
    } else {
      localStorage.removeItem('user')
    }
  }

  const logout = () => {
    setAuth(null, null)
  }

  return {
    token,
    user,
    role,
    isAuthenticated,
    setAuth,
    logout
  }
})
