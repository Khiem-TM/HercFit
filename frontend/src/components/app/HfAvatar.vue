<script setup lang="ts">
import { computed } from 'vue'
import type { UserProfile } from '@/types/api'

/** Ảnh đại diện tròn của người dùng; chưa có ảnh thì hiện chữ cái đầu của tên gọi. */
const props = withDefaults(defineProps<{ user: UserProfile | null; size?: number }>(), { size: 32 })
const name = computed(() => props.user?.nick_name || props.user?.fullname || 'Bạn')
const initial = computed(() => (name.value.trim()[0] || 'B').toUpperCase())
</script>

<template>
  <span class="avatar" :style="{ width: `${size}px`, height: `${size}px`, fontSize: `${Math.round(size * 0.4)}px` }">
    <img v-if="user?.avatar_url" :src="user.avatar_url" :alt="name" referrerpolicy="no-referrer" />
    <template v-else>{{ initial }}</template>
  </span>
</template>

<style scoped>
.avatar {
  border-radius: 50%; background: var(--hf-line); flex: none; overflow: hidden; font-weight: 700; color: var(--hf-ink);
  display: inline-flex; align-items: center; justify-content: center;
}
.avatar img { width: 100%; height: 100%; object-fit: cover; }
</style>
