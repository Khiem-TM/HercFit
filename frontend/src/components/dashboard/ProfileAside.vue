<script setup lang="ts">
import { computed, defineAsyncComponent, shallowRef } from 'vue'
import { Box, Pencil } from 'lucide-vue-next'
import type { BodyMetricRead, GoalRead, HealthProfile, UserProfile } from '@/types/api'
import { num } from '@/components/knowledge/health/healthFormat'
import { goalChoices } from '@/features/onboarding/model'
import BodyFigure from './BodyFigure.vue'
import type { BodyMorph } from './bodyMorph'
import { bmiCategory, bmiOf, bmiPosition } from './bodyShape'
import { ddmm, localDate, vn } from './format'
import { latestMeasures, type ReadinessView } from './today'

const props = defineProps<{
  user: UserProfile | null
  profile: HealthProfile | null
  latest: BodyMetricRead | null
  metrics: BodyMetricRead[]
  goal: GoalRead | null
  readiness: ReadinessView
}>()
const emit = defineEmits<{ edit: [] }>()

const value = (field: { value: number | string | null } | null | undefined) => num(field?.value as number | string | null)
const height = computed(() => value(props.profile?.height_cm) ?? num(props.latest?.height_cm))
const weight = computed(() => value(props.profile?.weight_kg) ?? num(props.latest?.weight_kg))
const bmi = computed(() => bmiOf(height.value, weight.value))
const female = computed(() => props.user?.sex === 'FEMALE')
const measures = computed(() => latestMeasures(props.metrics))
const cm = (item: { value: number } | null) => (item ? `${vn(item.value, 1)} cm` : '—')
const goalLabel = computed(() => {
  const type = props.goal?.goal_types?.[0]
  return goalChoices.find(choice => choice.id === type)?.title ?? props.goal?.title ?? 'Chưa đặt'
})
const sexLabel = computed(() => (props.user?.sex === 'MALE' ? 'Nam' : props.user?.sex === 'FEMALE' ? 'Nữ' : '—'))
const age = computed(() => props.user?.age ?? value(props.profile?.age))
const score = computed(() => props.readiness.score)
const dots = computed(() => Array.from({ length: 20 }, (_, index) => score.value != null && index < Math.round(score.value / 5)))
const fat = computed(() => {
  const own = measures.value.fat
  if (own) return { text: `${vn(own.value, 1)} %`, at: ddmm(localDate(own.at)) }
  const device = value(props.profile?.body_fat_pct)
  return device != null ? { text: `${vn(device, 1)} %`, at: '' } : null
})
// three.js nằm ở chunk riêng, chỉ tải khi Dashboard mở. Trong lúc tải (hoặc khi không có WebGL) hiện hình 2D.
const BodyModel3D = defineAsyncComponent(() => import('./BodyModel3D.vue'))
const use3d = shallowRef(true)
const shown3d = shallowRef<BodyMorph | null>(null)
const fatValue = computed(() => measures.value.fat?.value ?? value(props.profile?.body_fat_pct))
const bodyInputs = computed(() => ({ sex: props.user?.sex, age: age.value, heightCm: height.value, weightKg: weight.value,
                                     fatPct: fatValue.value }))
const figureLabel = computed(() => bmi.value != null
  ? `Mô hình cơ thể theo BMI ${vn(bmi.value, 1)}, chiều cao ${vn(height.value, 0)} cm, cân nặng ${vn(weight.value, 1)} kg`
  : 'Chưa có mô hình cơ thể')
</script>

<template>
  <aside class="hf-card pcard" aria-label="Hồ sơ người dùng">
    <div class="hf-hd top">
      <div class="who">
        <div class="name">{{ user?.fullname || 'Bạn' }}</div>
        <div class="hf-mut email">{{ user?.email }}</div>
      </div>
      <button type="button" class="hf-ib soft" aria-label="Chỉnh sửa hồ sơ" @click="emit('edit')">
        <Pencil :size="18" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>
    <div class="age">{{ age ? `${age} tuổi` : 'Chưa khai báo tuổi' }}</div>
    <div class="pills">
      <span class="hf-pill">Giới tính: <b>{{ sexLabel }}</b></span>
      <span class="hf-pill">Chiều cao: <b>{{ height ? `${vn(height, 0)} cm` : '—' }}</b></span>
      <span class="hf-pill">Cân nặng: <b>{{ weight ? `${vn(weight, 1)} kg` : '—' }}</b></span>
      <span class="hf-pill">Mục tiêu: <b>{{ goalLabel }}</b></span>
    </div>

    <div class="stage">
      <template v-if="bmi != null">
        <span class="hf-pill ok bmi-pill">BMI {{ vn(bmi, 1) }}</span>
        <div class="fig">
          <BodyFigure v-if="!shown3d" class="fig2d" :bmi="bmi" :female="female" labels :label="figureLabel"
                      :height="`${vn(height, 0)} cm`" :chest="measures.chest ? cm(measures.chest) : ''"
                      :waist="measures.waist ? cm(measures.waist) : ''" :hip="measures.hip ? cm(measures.hip) : ''" />
          <BodyModel3D v-if="use3d" class="fig3d" :inputs="bodyInputs" :label="figureLabel"
                       :height="`${vn(height, 0)} cm`" :chest="measures.chest ? cm(measures.chest) : ''"
                       :waist="measures.waist ? cm(measures.waist) : ''" :hip="measures.hip ? cm(measures.hip) : ''"
                       @ready="shown3d = $event" @failed="use3d = false; shown3d = null" />
        </div>
        <div class="hf-mut caption"><Box :size="13" :stroke-width="1.8" aria-hidden="true" />
          {{ shown3d ? `Mô hình 3D theo BMI và ${shown3d.estimated ? '% mỡ ước tính' : `${vn(shown3d.fatPct, 1)}% mỡ`}` : 'Mô hình minh hoạ theo BMI' }}</div>
      </template>
      <div v-else class="nobody">
        <BodyFigure class="ghost" :bmi="22" :female="female" label="" aria-hidden="true" />
        <b>Chưa có chiều cao và cân nặng</b>
        <span class="hf-mut">Thêm số đo để xem mô hình cơ thể theo BMI.</span>
        <button type="button" class="hf-btn pri" @click="emit('edit')">Thêm số đo</button>
      </div>
    </div>

    <div v-if="bmi != null" class="bmi">
      <div class="bmi-head"><span><b>BMI {{ vn(bmi, 1) }}</b> <span class="hf-mut">· {{ bmiCategory(bmi) }}</span></span>
        <span class="hf-mut small">Phân loại BYT (người châu Á)</span></div>
      <div class="scale" role="img" :aria-label="`Thang BMI, giá trị ${vn(bmi, 1)}`">
        <span /><span /><span /><span /><span />
        <i class="mark" :style="{ left: `${bmiPosition(bmi)}%` }" />
      </div>
      <div class="ticks hf-mut"><span /><span>18,5</span><span>23</span><span>25</span><span>30</span></div>
    </div>

    <div class="score">
      <div class="score-head"><span>Điểm sẵn sàng hôm nay</span><span class="small">Hệ thống tính</span></div>
      <div class="score-num"><span class="hf-dg">{{ score ?? '—' }}</span><span class="of">/ 100</span></div>
      <div class="score-dots" aria-hidden="true">
        <span v-for="(on, index) in dots" :key="index" class="hf-dt" :class="{ on }" />
      </div>
      <div class="score-sub">{{ readiness.title }}{{ readiness.confidence && score != null ? ` · ${readiness.confidence}` : '' }}</div>
    </div>

    <div class="mgrid">
      <div class="mcell"><span>Vòng ngực</span><b>{{ cm(measures.chest) }}</b></div>
      <div class="mcell"><span>Vòng eo</span><b>{{ cm(measures.waist) }}</b></div>
      <div class="mcell"><span>Vòng hông</span><b>{{ cm(measures.hip) }}</b></div>
      <div class="mcell"><span>Mỡ cơ thể{{ fat?.at ? ` · ${fat.at}` : '' }}</span><b>{{ fat?.text ?? '—' }}</b></div>
    </div>
    <button type="button" class="hf-btn" @click="emit('edit')">Chỉnh sửa hồ sơ &amp; số đo</button>
  </aside>
</template>

<style scoped>
.pcard { gap: 14px; }
.top { align-items: flex-start; }
.who { min-width: 0; }
.name { font-size: 28px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.1; overflow-wrap: anywhere; }
.email { font-size: 13px; margin-top: 4px; overflow-wrap: anywhere; }
.age { font-size: 22px; font-weight: 600; }
.pills { display: flex; flex-wrap: wrap; gap: 6px; }
.pills .hf-pill { font-weight: 500; }
.stage {
  position: relative; border-radius: 20px; padding: 8px 6px 4px;
  background: radial-gradient(120% 80% at 50% 30%, var(--hf-card) 0%, var(--hf-fill) 70%);
}
.bmi-pill { position: absolute; top: 10px; right: 10px; }
.fig { position: relative; height: 330px; }
.fig2d, .fig3d { position: absolute; inset: 0; height: 100%; }
.caption { display: flex; align-items: center; justify-content: center; gap: 6px; font-size: 11px; padding: 2px 0 6px; }
.nobody { height: 330px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; padding: 20px; font-size: 13px; line-height: 1.5; }
.nobody b { font-size: 14px; }
.ghost { width: 70px; height: 140px; opacity: .35; }
.bmi { display: flex; flex-direction: column; gap: 8px; }
.bmi-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; font-size: 13px; }
.small { font-size: 11px; }
.scale { display: grid; grid-template-columns: 17.5fr 22.5fr 10fr 25fr 25fr; gap: 3px; position: relative; height: 8px; }
.scale span { border-radius: 4px; }
.scale span:nth-child(1) { background: #DCDCE0; } .scale span:nth-child(2) { background: #A1A1AA; }
.scale span:nth-child(3) { background: #8B8B94; } .scale span:nth-child(4) { background: #5A5A63; }
.scale span:nth-child(5) { background: #3F3F46; }
.mark { position: absolute; top: -4px; width: 4px; height: 16px; border-radius: 2px; background: var(--hf-ink); transform: translateX(-50%); box-shadow: 0 0 0 2px var(--hf-card); }
.ticks { display: grid; grid-template-columns: 17.5fr 22.5fr 10fr 25fr 25fr; font-size: 10px; }
.score { background: #141416; color: #fff; border-radius: 20px; padding: 16px 18px; display: flex; flex-direction: column; gap: 10px; }
:root.dark .score { background: var(--hf-inv); }
.score-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 13px; color: #B4B4BA; font-weight: 500; }
.score-num { display: flex; align-items: baseline; gap: 6px; }
.score-num .hf-dg { font-size: 64px; }
.of { font-size: 16px; font-weight: 600; color: #B4B4BA; }
.score-dots { display: grid; grid-template-columns: repeat(20, minmax(0, 1fr)); gap: 4px; justify-items: center; }
.score-dots .hf-dt { width: 8px; height: 8px; background: #2E2E33; }
.score-dots .hf-dt.on { background: var(--hf-acc); }
.score-sub { font-size: 13px; color: #D4D4D8; }
.mgrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.mcell { background: var(--hf-fill-2); border-radius: 14px; padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; }
.mcell span { font-size: 12px; color: var(--hf-muted); }
.mcell b { font-size: 16px; font-weight: 700; }
</style>
