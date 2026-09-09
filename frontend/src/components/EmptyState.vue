<template>
  <div class="empty-state">
    <div class="empty-icon">
      <slot name="icon">📊</slot>
    </div>
    <h3 class="empty-title">{{ title }}</h3>
    <p class="empty-description">{{ description }}</p>
    
    <button 
      v-if="actionLabel" 
      class="empty-action" 
      @click="$emit('action')"
    >
      {{ actionLabel }}
    </button>
  </div>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    default: 'No data available'
  },
  description: {
    type: String,
    default: 'There is nothing to display here yet.'
  },
  actionLabel: {
    type: String,
    default: ''
  }
})

defineEmits(['action'])
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
  background-color: #f9fafb;
  border: 2px dashed #e5e7eb;
  border-radius: 12px;
  margin: 2rem auto;
  max-width: 600px;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
  color: #9ca3af;
  line-height: 1;
}

.empty-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 0.5rem 0;
}

.empty-description {
  font-size: 0.875rem;
  color: #6b7280;
  margin: 0 0 1.5rem 0;
  max-width: 400px;
}

.empty-action {
  background-color: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.empty-action:hover {
  background-color: #2563eb;
}
</style>
