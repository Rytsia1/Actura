<script setup>
const props = defineProps({
  type: String,
  title: String,
  description: String
})
const emit = defineEmits(['select'])
</script>

<template>
  <div 
    class="bg-slate-800 rounded-xl border-2 border-white/[0.06] p-6 cursor-pointer hover:border-indigo-500 hover:bg-[#151f38] transition-all group text-left"
    @click="emit('select', type)"
  >
    <div class="flex justify-between items-start mb-4">
      <div class="h-10 w-10 rounded bg-indigo-500/10 flex items-center justify-center text-indigo-400 group-hover:bg-indigo-500 group-hover:text-white transition-colors">
        <slot name="icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-file-text"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>
        </slot>
      </div>
      <div class="h-4 w-4 rounded-full border-2 border-slate-600 group-hover:border-indigo-500 group-hover:bg-indigo-500 transition-colors flex items-center justify-center">
        <div class="h-2 w-2 rounded-full bg-white opacity-0 group-hover:opacity-100"></div>
      </div>
    </div>
    <h3 class="text-lg font-medium text-white mb-2">{{ title || type }}</h3>
    <p class="text-sm text-slate-400 leading-relaxed">{{ description }}</p>
  </div>
</template>
