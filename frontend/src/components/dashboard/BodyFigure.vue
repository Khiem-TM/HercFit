<script setup lang="ts">
import { computed, useId } from 'vue'
import { bodyShape } from './bodyShape'

/** Bóng dáng theo BMI; `labels` vẽ thước chiều cao và đường chú thích ngực / eo / hông. */
const props = defineProps<{
  bmi: number | null
  female?: boolean
  height?: string
  chest?: string
  waist?: string
  hip?: string
  labels?: boolean
  label: string
}>()

const id = useId()
const shape = computed(() => bodyShape(props.bmi, props.female))
</script>

<template>
  <svg :viewBox="labels ? '0 0 220 432' : '40 0 140 432'" role="img" :aria-label="label" class="figure">
    <defs>
      <linearGradient :id="`${id}-skin`" x1="0" x2="1" y1="0" y2="0">
        <stop offset="0" class="s-edge" /><stop offset="0.32" class="s-mid" /><stop offset="0.5" class="s-light" />
        <stop offset="0.68" class="s-mid" /><stop offset="1" class="s-edge" />
      </linearGradient>
      <radialGradient :id="`${id}-head`" cx="0.42" cy="0.35" r="0.75">
        <stop offset="0" class="s-light" /><stop offset="1" class="s-edge" />
      </radialGradient>
    </defs>
    <template v-if="labels">
      <line x1="14" y1="16" x2="14" y2="416" class="rule" />
      <line x1="10" y1="16" x2="18" y2="16" class="rule" />
      <line x1="10" y1="416" x2="18" y2="416" class="rule" />
      <text x="7" y="216" transform="rotate(-90 7 216)" text-anchor="middle" class="tag dim">{{ height }}</text>
      <ellipse cx="110" cy="421" :rx="shape.shadow" ry="6" class="ground" />
    </template>
    <path :d="shape.armL" :fill="`url(#${id}-skin)`" class="skin" />
    <path :d="shape.armR" :fill="`url(#${id}-skin)`" class="skin" />
    <path :d="shape.torso" :fill="`url(#${id}-skin)`" class="skin" />
    <ellipse cx="110" cy="38" :rx="shape.headRx" ry="22" :fill="`url(#${id}-head)`" class="skin" />
    <template v-if="labels">
      <template v-if="chest">
        <line :x1="shape.chest[0]" y1="130" x2="214" y2="130" class="guide" />
        <circle :cx="shape.chest[1]" cy="130" r="2.6" class="pin" />
        <text x="214" y="123" text-anchor="end" class="tag">Ngực {{ chest }}</text>
      </template>
      <template v-if="waist">
        <line x1="24" y1="192" :x2="shape.waist[1]" y2="192" class="guide" />
        <circle :cx="shape.waist[0]" cy="192" r="2.6" class="pin" />
        <text x="24" y="185" class="tag">Eo {{ waist }}</text>
      </template>
      <template v-if="hip">
        <line :x1="shape.hip[0]" y1="228" x2="214" y2="228" class="guide" />
        <circle :cx="shape.hip[1]" cy="228" r="2.6" class="pin" />
        <text x="214" y="221" text-anchor="end" class="tag">Hông {{ hip }}</text>
      </template>
    </template>
  </svg>
</template>

<style scoped>
.figure { display: block; width: 100%; }
.s-edge { stop-color: #B9BAC2; }
.s-mid { stop-color: #E6E7EB; }
.s-light { stop-color: #FAFAFB; }
:root.dark .s-edge { stop-color: #4A4A52; }
:root.dark .s-mid { stop-color: #6E6E78; }
:root.dark .s-light { stop-color: #8C8C96; }
.skin { stroke: #A9AAB3; stroke-width: .8; }
.rule { stroke: var(--hf-ghost); stroke-width: 1; }
.ground { fill: #000; opacity: .09; }
.guide { stroke: var(--hf-acc); stroke-width: 1; stroke-dasharray: 3 3; }
.pin { fill: var(--hf-acc); }
.tag { font-size: 10px; font-weight: 600; fill: var(--hf-ink); font-family: var(--hf-font); }
.tag.dim { fill: var(--hf-sub-2); }
</style>
