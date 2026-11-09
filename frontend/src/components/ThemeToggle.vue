<script setup lang="ts">
import { computed } from 'vue'
import { Moon, Sun } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'

/** variant "app": nút tròn của giao diện ứng dụng (thanh bên chat); mặc định là kiểu của trang giới thiệu. */
const props = defineProps<{ variant?: 'app' }>()
const { resolved, toggle } = useTheme()
const label = computed(() => (resolved.value === 'light' ? 'Chuyển sang giao diện tối' : 'Chuyển sang giao diện sáng'))
const classes = computed(() => (props.variant === 'app'
  ? 'hf-ib clear'
  : 'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-ink/10 text-outline transition-colors hover:bg-ink/[0.06] hover:text-primary'))
</script>

<template>
  <button
    type="button"
    :class="classes"
    :style="variant === 'app' ? { width: '40px', height: '40px' } : undefined"
    :aria-label="label"
    :title="label"
    @click="toggle"
  >
    <Sun v-if="resolved === 'light'" class="h-4 w-4" />
    <Moon v-else class="h-4 w-4" />
  </button>
</template>
