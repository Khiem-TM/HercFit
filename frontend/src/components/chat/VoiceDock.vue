<script setup lang="ts">
import { computed } from 'vue'
import { Mic, MicOff, X } from 'lucide-vue-next'
import type { VoiceCaption, VoiceState } from '@/composables/useVoice'

/** Thanh hội thoại giọng nói thay chỗ ô soạn tin khi micro bật: quả cầu và sóng âm theo người đang nói, phụ đề. */
const props = defineProps<{
  state: VoiceState
  userLevel: number
  agentLevel: number
  caption: VoiceCaption | null
  muted: boolean
}>()

const emit = defineEmits<{
  (e: 'mute'): void
  (e: 'end'): void
}>()

const LABELS: Record<VoiceState, string> = {
  idle: '',
  connecting: 'Đang kết nối…',
  listening: 'Đang nghe',
  thinking: 'Đang suy nghĩ…',
  speaking: 'Đang nói',
}

const HINTS: Partial<Record<VoiceState, string>> = {
  connecting: 'Đang mời trợ lý giọng nói vào cuộc trò chuyện',
  listening: 'Bạn cứ nói tự nhiên, ví dụ "Trưa nay mình ăn một bát phở bò"',
}

// Người đang nói quyết định quả cầu và sóng âm chuyển động theo ai.
const level = computed(() => (props.state === 'speaking' ? props.agentLevel : props.state === 'listening' && !props.muted ? props.userLevel : 0))
const label = computed(() => (props.muted && props.state === 'listening' ? 'Micro đang tắt' : LABELS[props.state]))
const line = computed(() => props.caption?.text || HINTS[props.state] || '')
const BARS = [0.45, 0.75, 1, 0.75, 0.45]
</script>

<template>
  <div class="dock" :class="[state, { muted }]" :style="{ '--lv': level.toFixed(3) }">
    <div class="orb" aria-hidden="true">
      <span class="glow" />
      <span class="core" />
    </div>

    <div class="mid">
      <div class="label" :class="{ shimmer: state === 'thinking' || state === 'connecting' }" role="status" aria-live="polite">
        {{ label }}
      </div>
      <p class="cap" :class="caption?.who">
        <span v-if="caption" class="who">{{ caption.who === 'user' ? 'Bạn' : 'HercFit' }}</span>{{ line }}
      </p>
    </div>

    <div class="wave" aria-hidden="true">
      <i v-for="(weight, index) in BARS" :key="index" :style="{ '--w': weight, '--i': index }" />
    </div>

    <button type="button" class="ib" :class="{ on: muted }" :aria-pressed="muted"
            :title="muted ? 'Bật micro' : 'Tắt micro'" :aria-label="muted ? 'Bật micro' : 'Tắt micro'" @click="emit('mute')">
      <MicOff v-if="muted" :size="17" aria-hidden="true" />
      <Mic v-else :size="17" aria-hidden="true" />
    </button>
    <button type="button" class="end" title="Kết thúc trò chuyện bằng giọng nói" @click="emit('end')">
      <X :size="15" :stroke-width="2.4" aria-hidden="true" />Kết thúc
    </button>
  </div>
</template>

<style scoped>
.dock {
  --lv: 0;
  position: relative; display: flex; align-items: center; gap: 14px; min-height: 84px; padding: 12px 12px 12px 14px;
  background: var(--hf-card); border: 1px solid var(--hf-line); border-radius: 24px; box-shadow: 0 6px 24px var(--hf-shadow);
  overflow: hidden; animation: dock-in 260ms cubic-bezier(.2, .8, .2, 1);
}
/* Viền sáng chạy quanh thanh khi trợ lý đang suy nghĩ hoặc nói. */
.dock::before {
  content: ''; position: absolute; inset: -1px; border-radius: inherit; padding: 1px; pointer-events: none; opacity: 0;
  background: conic-gradient(from var(--spin, 0deg), transparent 0 60%, var(--hf-acc), var(--hf-violet), var(--hf-blue), transparent 92%);
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor; mask-composite: exclude;
  transition: opacity .3s;
}
.dock.thinking::before, .dock.speaking::before { opacity: 1; animation: spin-border 2.4s linear infinite; }
@property --spin { syntax: '<angle>'; inherits: false; initial-value: 0deg; }
@keyframes spin-border { to { --spin: 360deg; } }
@keyframes dock-in { from { opacity: 0; transform: translateY(8px) scale(.98); } to { opacity: 1; transform: none; } }

.orb { position: relative; width: 52px; height: 52px; flex: none; display: grid; place-items: center; }
.core, .glow { position: absolute; border-radius: 50%; }
.core {
  inset: 6px; background: radial-gradient(circle at 32% 30%, #fff 0 8%, transparent 40%),
    conic-gradient(from 200deg, var(--hf-acc), var(--hf-violet), var(--hf-blue), var(--hf-acc));
  transform: scale(calc(.9 + var(--lv) * .45)); transition: transform 90ms linear;
  box-shadow: 0 4px 16px color-mix(in srgb, var(--hf-violet) 35%, transparent);
}
.glow {
  inset: 0; background: conic-gradient(from 0deg, var(--hf-acc), var(--hf-violet), var(--hf-blue), var(--hf-acc));
  filter: blur(10px); opacity: calc(.25 + var(--lv) * .6); transform: scale(calc(1 + var(--lv) * .5)); transition: transform 90ms linear;
}
.thinking .core { animation: orb-spin 2.2s linear infinite, orb-breathe 1.6s ease-in-out infinite; }
.thinking .glow { animation: orb-spin 3.2s linear infinite reverse; opacity: .45; }
.connecting .core { animation: orb-breathe 1.2s ease-in-out infinite; filter: saturate(.4); }
.muted .core { filter: grayscale(1); opacity: .6; }
@keyframes orb-spin { to { rotate: 360deg; } }
@keyframes orb-breathe { 50% { scale: .9; } }

.mid { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.label { font-size: 13px; font-weight: 600; color: var(--hf-sub); }
.shimmer {
  background: linear-gradient(90deg, var(--hf-faint) 0%, var(--hf-ink) 45%, var(--hf-faint) 90%) 0 0 / 200% 100%;
  -webkit-background-clip: text; background-clip: text; color: transparent; animation: shimmer 1.6s linear infinite;
}
@keyframes shimmer { to { background-position: -200% 0; } }
.cap {
  margin: 0; font-size: 15px; line-height: 1.45; color: var(--hf-text); overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.cap:not(.user):not(.agent) { color: var(--hf-muted); font-size: 14px; }
.who { font-weight: 700; color: var(--hf-ink); margin-right: 6px; }
.cap.agent .who { color: var(--hf-plan); }

.wave { display: flex; align-items: center; gap: 3px; height: 30px; flex: none; }
.wave i {
  width: 4px; border-radius: 4px; background: var(--hf-ink);
  height: calc(5px + var(--lv) * var(--w) * 24px); transition: height 80ms linear;
}
.speaking .wave i { background: var(--hf-plan); }
.thinking .wave i { animation: bounce 1.1s ease-in-out infinite; animation-delay: calc(var(--i) * 90ms); background: var(--hf-faint); }
@keyframes bounce { 0%, 100% { height: 5px; } 40% { height: 14px; } }

.ib {
  width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--hf-line); background: var(--hf-card); color: var(--hf-sub);
  display: inline-flex; align-items: center; justify-content: center; flex: none;
}
.ib:hover { background: var(--hf-fill-3); }
.ib.on { background: var(--hf-err-bg); color: var(--hf-err-text); border-color: transparent; }
.end {
  display: inline-flex; align-items: center; gap: 6px; height: 40px; padding: 0 16px; border-radius: 999px; border: 0; flex: none;
  background: var(--hf-ink); color: var(--hf-on-ink); font-size: 14px; font-weight: 600;
}
.end:hover { background: var(--hf-ink-hover); }

@media (max-width: 560px) {
  .dock { flex-wrap: wrap; gap: 10px; }
  .mid { order: 3; flex-basis: 100%; }
  .wave { margin-left: auto; }
}
@media (prefers-reduced-motion: reduce) {
  .dock, .dock::before, .core, .glow, .shimmer, .wave i { animation: none !important; transition: none; }
}
</style>
