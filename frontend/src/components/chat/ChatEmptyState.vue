<script setup lang="ts">
import { computed } from 'vue'
import { Activity, Dumbbell, Flame } from 'lucide-vue-next'
import type { UserProfile } from '@/types/api'

const props = defineProps<{
  user: UserProfile | null
}>()

const emit = defineEmits<{
  (e: 'select-prompt', prompt: string): void
}>()

const displayName = computed(() => {
  if (props.user?.nick_name) return props.user.nick_name
  if (props.user?.fullname) return props.user.fullname
  return 'Bạn'
})

const suggestionCards = [
  {
    icon: Flame,
    title: 'Phân tích bữa ăn & Macro',
    description:
      'Ghi lại thực đơn vừa ăn và tính toán tự động lượng Calo, Protein, Carb và Fat theo mục tiêu.',
    prompt:
      'Sáng nay mình ăn 1 bát bún bò Huế và uống 1 ly cà phê sữa ít đường. Tính giúp mình lượng calo và macro của bữa này nhé.',
  },
  {
    icon: Dumbbell,
    title: 'Kiến tạo giáo án tập luyện',
    description:
      'Tối ưu hóa khối lượng vận động, số hiệp và chu kỳ phục hồi cơ bắp dựa trên thể trạng hiện tại.',
    prompt:
      'Hãy lập cho mình giáo án tập luyện 4 buổi/tuần tập trung vào phát triển cơ ngực, lưng xô và cải thiện sức bền.',
  },
  {
    icon: Activity,
    title: 'Đánh giá chỉ số & Mục tiêu',
    description:
      'Kiểm tra tiến độ cân nặng, tỷ lệ mỡ cơ thể và điều chỉnh lộ trình dinh dưỡng hàng tuần.',
    prompt:
      'Kiểm tra giúp mình hồ sơ chỉ số cơ thể hiện tại và tư vấn mức thâm hụt calo an toàn để giảm mỡ giữ cơ.',
  },
]
</script>

<template>
  <div class="mx-auto flex w-full max-w-3xl flex-col items-center justify-center px-4 py-8">
    <!-- Center Kinetic Orbital Sphere (Olympus Aesthetic + Reference Sphere) -->
    <div class="relative mb-6 flex h-28 w-28 items-center justify-center">
      <!-- Outer Subtle Glow -->
      <div
        class="pointer-events-none absolute inset-0 rounded-full bg-white/[0.06] blur-2xl"
      />

      <!-- Rotating Orbital SVG Rings -->
      <svg
        class="pointer-events-none absolute inset-0 h-full w-full animate-[spin_28s_linear_infinite] opacity-45"
        viewBox="0 0 120 120"
        fill="none"
      >
        <circle
          cx="60"
          cy="60"
          r="54"
          stroke="url(#orbRingGrad)"
          stroke-width="1"
          stroke-dasharray="5 5"
        />
        <ellipse
          cx="60"
          cy="60"
          rx="52"
          ry="24"
           transform="rotate(-28 60 60)"
          stroke="rgba(255,255,255,0.28)"
          stroke-width="1"
        />
        <ellipse
          cx="60"
          cy="60"
          rx="52"
          ry="24"
          transform="rotate(32 60 60)"
          stroke="rgba(255,255,255,0.16)"
          stroke-width="1"
        />
        <defs>
          <linearGradient id="orbRingGrad" x1="0" y1="0" x2="120" y2="120" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#ffffff" stop-opacity="0.6" />
            <stop offset="50%" stop-color="#8f918c" stop-opacity="0.15" />
            <stop offset="100%" stop-color="#ffffff" stop-opacity="0.5" />
          </linearGradient>
        </defs>
      </svg>

      <!-- 3D Metallic Obsidian Sphere Core -->
      <div
        class="relative h-16 w-16 overflow-hidden rounded-full border border-white/25 shadow-[0_12px_36px_rgba(0,0,0,0.85),inset_0_2px_12px_rgba(255,255,255,0.35)]"
        style="background: radial-gradient(circle at 32% 28%, #5a5d64 0%, #232529 42%, #0b0b0d 82%, #1f2024 100%);"
      >
        <div
          class="absolute -left-2 -top-2 h-10 w-10 rounded-full bg-white/20 blur-md"
        />
        <div
          class="absolute bottom-1 right-1 h-6 w-6 rounded-full bg-white/10 blur-sm"
        />
      </div>
    </div>

    <!-- Greeting Headlines -->
    <div class="mb-7 text-center">
      <p class="font-headline-md text-xl font-normal tracking-tight text-on-surface-variant md:text-2xl">
        Xin chào, {{ displayName }}
      </p>
      <h1 class="mt-1.5 font-body-md text-2xl font-semibold tracking-tight text-primary md:text-[30px] md:leading-tight">
        Hôm nay tôi có thể giúp gì cho bạn?
      </h1>
    </div>

    <!-- Composer Slot (Centered in Empty State) -->
    <div class="w-full">
      <slot name="composer" />
    </div>

    <!-- 3 Quick-Action Suggestion Cards -->
    <div class="mt-4 grid w-full grid-cols-1 gap-3.5 md:grid-cols-3">
      <button
        v-for="card in suggestionCards"
        :key="card.title"
        type="button"
        class="group flex flex-col items-start justify-between rounded-2xl border border-white/[0.08] bg-[#181818]/90 p-4 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-white/20 hover:bg-[#202020] hover:shadow-[0_16px_40px_rgba(0,0,0,0.5)]"
        @click="emit('select-prompt', card.prompt)"
      >
        <div
          class="mb-4 flex h-9 w-9 items-center justify-center rounded-xl border border-white/[0.09] bg-[#111111] text-on-surface-variant transition-colors group-hover:border-white/25 group-hover:text-primary"
        >
          <component :is="card.icon" class="h-4 w-4" />
        </div>

        <div>
          <h3 class="text-sm font-semibold text-primary group-hover:text-white">
            {{ card.title }}
          </h3>
          <p class="mt-1.5 line-clamp-3 text-xs leading-relaxed text-outline">
            {{ card.description }}
          </p>
        </div>
      </button>
    </div>
  </div>
</template>

