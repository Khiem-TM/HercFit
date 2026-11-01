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
    <!-- Quả cầu quỹ đạo Kinetic ở giữa (phong cách Olympus + quả cầu tham chiếu) -->
    <div class="relative mb-6 flex h-28 w-28 items-center justify-center">
      <!-- Quầng sáng mờ bên ngoài -->
      <div
        class="pointer-events-none absolute inset-0 rounded-full bg-ink/[0.06] blur-2xl"
      />

      <!-- Các vòng quỹ đạo SVG xoay -->
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
            <stop offset="0%" style="stop-color: rgb(var(--c-ink))" stop-opacity="0.6" />
            <stop offset="50%" style="stop-color: rgb(var(--c-outline))" stop-opacity="0.15" />
            <stop offset="100%" style="stop-color: rgb(var(--c-ink))" stop-opacity="0.5" />
          </linearGradient>
        </defs>
      </svg>

      <!-- Lõi quả cầu obsidian kim loại 3D -->
      <div
        class="relative h-16 w-16 overflow-hidden rounded-full border border-ink/25 shadow-[0_12px_36px_rgb(var(--c-shadow)/calc(0.85*var(--shadow-k))),inset_0_2px_12px_rgba(255,255,255,0.35)]"
        style="background: radial-gradient(circle at 32% 28%, #5a5d64 0%, #232529 42%, #0b0b0d 82%, #1f2024 100%);"
      >
        <div
          class="absolute -left-2 -top-2 h-10 w-10 rounded-full bg-ink/20 blur-md"
        />
        <div
          class="absolute bottom-1 right-1 h-6 w-6 rounded-full bg-ink/10 blur-sm"
        />
      </div>
    </div>

    <!-- Dòng chào mừng -->
    <div class="mb-7 text-center">
      <p class="font-headline-md text-xl font-normal tracking-tight text-on-surface-variant md:text-2xl">
        Xin chào, {{ displayName }}
      </p>
      <h1 class="mt-1.5 font-body-md text-2xl font-semibold tracking-tight text-primary md:text-[30px] md:leading-tight">
        Hôm nay tôi có thể giúp gì cho bạn?
      </h1>
    </div>

    <!-- Ô soạn tin (căn giữa khi trống) -->
    <div class="w-full">
      <slot name="composer" />
    </div>

    <!-- 3 thẻ gợi ý thao tác nhanh -->
    <!-- Kích thước theo cột chat, cột này hẹp lại khi bảng tri thức được kéo rộng ra. -->
    <div class="mt-4 grid w-full grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3.5">
      <button
        v-for="card in suggestionCards"
        :key="card.title"
        type="button"
        class="group flex flex-col items-start justify-between rounded-2xl border border-ink/[0.08] bg-panel-raised/90 p-4 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-ink/20 hover:bg-panel-hover hover:shadow-[0_16px_40px_rgb(var(--c-shadow)/calc(0.5*var(--shadow-k)))]"
        @click="emit('select-prompt', card.prompt)"
      >
        <div
          class="mb-4 flex h-9 w-9 items-center justify-center rounded-xl border border-ink/[0.09] bg-sunken text-on-surface-variant transition-colors group-hover:border-ink/25 group-hover:text-primary"
        >
          <component :is="card.icon" class="h-4 w-4" />
        </div>

        <div>
          <h3 class="text-sm font-semibold text-primary group-hover:text-ink">
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

