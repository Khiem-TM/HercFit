<script setup lang="ts">
import { computed } from 'vue'
import { AlertCircle, Clock, TriangleAlert } from 'lucide-vue-next'
import type { BodyMetricRead, GoalRead, UserProfile } from '@/types/api'
import { useAuth } from '@/composables/useAuth'
import ProfileAside from './ProfileAside.vue'
import { longDate, stamp, vn, WEEKDAY_LONG, weekday } from './format'
import { nutritionView, readinessView, weekView, workoutView } from './today'
import type { DashboardData } from './useDashboardData'

const props = defineProps<{ data: DashboardData }>()
const emit = defineEmits<{
  detail: [kind: 'ready' | 'workout' | 'nutrition']
  settings: [tab: 'profile' | 'integrations' | 'notifications']
  ask: [text: string]
  prefill: [text: string]
  'create-plan': []
  plan: []
}>()

const { user, currentGoal, latestBodyMetric } = useAuth()
const health = computed(() => props.data.health.value)
const connection = computed(() => health.value?.connection ?? null)
const readiness = computed(() => readinessView(health.value?.assessment ?? null, connection.value))
const plan = computed(() => props.data.plan.value)
const workout = computed(() => workoutView(plan.value, props.data.today))
const week = computed(() => weekView(plan.value, props.data.today))
const nutrition = computed(() => nutritionView(props.data.targets.value))
const stale = computed(() => props.data.failed.value.length > 0 || connection.value?.status === 'NEEDS_REAUTH'
  || connection.value?.status === 'ERROR')
const badge = computed(() => ({ ready: 'b-ready', reduce: 'b-reduce', none: 'b-none' })[readiness.value.kind])
const entryCount = computed(() => String(workout.value.entry?.items.length ?? 0).padStart(2, '0'))
const proteinPct = computed(() => (nutrition.value.proteinTarget ? Math.min(100, (nutrition.value.protein / nutrition.value.proteinTarget) * 100) : 0))
const shortWeekday = (iso: string) => `${WEEKDAY_LONG[weekday(iso)]} ${iso.slice(8, 10)}/${iso.slice(5, 7)}`
const typedUser = computed(() => user.value as UserProfile | null)
const goal = computed(() => currentGoal.value as GoalRead | null)
const latest = computed(() => latestBodyMetric.value as BodyMetricRead | null)
</script>

<template>
  <div class="today">
    <div v-if="stale" class="hf-err" role="status">
      <span class="err-text"><AlertCircle :size="18" aria-hidden="true" />
        Không tải được một phần dữ liệu mới. Đang hiển thị dữ liệu đã lưu{{ connection?.last_success_at ? ` — thiết bị đồng bộ lần cuối ${stamp(connection.last_success_at)}` : '' }}.</span>
      <button type="button" class="hf-btn on-card" @click="data.refresh()">Thử lại</button>
    </div>

    <div v-if="data.loading.value" class="hf-grid" aria-busy="true" aria-label="Đang tải dữ liệu">
      <div v-for="(span, index) in [7, 5, 7, 5]" :key="index" :class="['hf-card', `hf-c${span}`]" style="min-height: 280px">
        <div class="hf-sk" style="width: 40%; height: 14px" /><div class="hf-sk" style="width: 70%; height: 40px" />
        <div class="hf-sk" style="width: 90%; height: 14px" /><div class="hf-sk" style="width: 60%; height: 14px" />
        <div style="flex: 1" /><div class="hf-sk" style="width: 160px; height: 44px; border-radius: 999px" />
      </div>
    </div>

    <div v-else class="dash">
      <div class="hf-grid hf-stagger">
        <!-- Khối 1: Sẵn sàng -->
        <section class="hf-card hf-c7" aria-labelledby="b1">
          <div class="hf-hd">
            <h2 id="b1" class="hf-lbl">Sẵn sàng tập luyện hôm nay</h2>
            <span v-if="readiness.confidence" class="hf-pill">{{ readiness.confidence }}</span>
          </div>
          <div class="headline">
            <span class="badge" :class="badge" />
            <div class="hf-big">{{ readiness.title }}</div>
          </div>
          <div class="explain">
            <p class="hf-mut">{{ readiness.explain }}</p>
            <p v-if="readiness.action" class="strong">{{ readiness.action }}</p>
          </div>
          <div v-if="readiness.signals.length" class="sigs">
            <div v-for="signal in readiness.signals" :key="signal.name" class="sig"><b>{{ signal.name }}</b><span>{{ signal.state }}</span></div>
          </div>
          <div v-if="readiness.warn" class="hf-warn"><TriangleAlert :size="16" aria-hidden="true" />{{ readiness.warn }}</div>
          <div class="grow" />
          <div class="hf-acts">
            <button v-if="readiness.canDetail" type="button" class="hf-btn pri" @click="emit('detail', 'ready')">Xem cơ sở đánh giá</button>
            <button v-if="readiness.connect" type="button" class="hf-btn" :class="{ pri: !readiness.canDetail }"
                    @click="emit('settings', 'integrations')">Kết nối dữ liệu</button>
            <button type="button" class="hf-btn" @click="emit('ask', 'Phân tích độ sẵn sàng tập luyện hôm nay của tôi và gợi ý buổi tập phù hợp.')">Hỏi trợ lý</button>
          </div>
        </section>

        <!-- Khối 2: Buổi tập -->
        <section class="hf-card hf-inv hf-c5" aria-labelledby="b2">
          <div class="hf-hd">
            <h2 id="b2" class="hf-lbl">Buổi tập hôm nay</h2>
            <span v-if="workout.mode === 'rest'" class="hf-pill">Ngày nghỉ</span>
            <span v-else-if="workout.mode === 'session'" class="hf-pill" :class="{ ok: workout.done }">
              {{ workout.done ? 'Đã ghi nhận hoàn thành' : 'Chưa ghi nhận hoàn thành' }}</span>
          </div>
          <template v-if="workout.mode === 'session' && workout.entry">
            <div class="session">
              <div class="session-name">
                <div class="hf-big">{{ workout.entry.label }}</div>
                <div class="hf-mut small">{{ plan?.name }}</div>
              </div>
              <div class="count">
                <div class="hf-dg" style="font-size: 76px">{{ entryCount }}</div>
                <div class="hf-lbl">bài tập</div>
              </div>
            </div>
            <div class="pills"><span class="hf-pill">{{ longDate(workout.entry.scheduled_date) }}</span></div>
            <div v-if="workout.others.length" class="hf-info row">
              <span>Còn {{ workout.others.length }} buổi khác hôm nay: <b>{{ workout.others.map(item => item.label).join(', ') }}</b></span>
              <button type="button" class="hf-lnk" style="color: #fff" @click="emit('detail', 'workout')">Xem tất cả ({{ workout.others.length + 1 }})</button>
            </div>
            <div v-if="workout.overdue" class="hf-warn">
              <Clock :size="16" aria-hidden="true" />
              <span><b>Quá hạn:</b> {{ workout.overdue.label }} · {{ shortWeekday(workout.overdue.scheduled_date) }} — chưa ghi nhận.
                Buổi này đã qua ngày nên không thể ghi nhận bù.</span>
            </div>
            <div class="grow" />
            <div class="hf-acts"><button type="button" class="hf-btn lt" @click="emit('detail', 'workout')">Xem buổi tập</button></div>
          </template>
          <template v-else-if="workout.mode === 'rest'">
            <div class="hf-big">Ngày nghỉ theo kế hoạch</div>
            <p class="hf-mut para">Hôm nay không có buổi tập trong lịch. Nghỉ ngơi là một phần của kế hoạch.</p>
            <div v-if="workout.next" class="hf-info">Buổi tiếp theo: <b>{{ workout.next.label }}</b> · {{ longDate(workout.next.scheduled_date) }}</div>
            <div class="grow" />
            <div class="hf-acts"><button type="button" class="hf-btn lt" @click="emit('plan')">Xem kế hoạch</button></div>
          </template>
          <template v-else>
            <div class="hf-big">Bạn chưa có lịch tập</div>
            <p class="hf-mut para">Trợ lý có thể giúp bạn lập lịch phù hợp với mục tiêu, thời gian và điều kiện tập.</p>
            <div class="grow" />
            <div class="hf-acts"><button type="button" class="hf-btn lt" @click="emit('create-plan')">Lập lịch với trợ lý</button></div>
          </template>
        </section>

        <!-- Khối 3: Dinh dưỡng -->
        <section class="hf-card hf-c7" aria-labelledby="b3">
          <div class="hf-hd">
            <h2 id="b3" class="hf-lbl">Dinh dưỡng hôm nay</h2>
            <span v-if="nutrition.has" class="hf-pill">Đã ghi {{ nutrition.meals }} bữa</span>
          </div>
          <template v-if="nutrition.has">
            <div class="energy">
              <div>
                <div class="hf-lbl" style="margin-bottom: 8px">Năng lượng đã ghi nhận</div>
                <div class="baseline-row">
                  <span class="hf-dg" style="font-size: 72px">{{ vn(nutrition.energy) }}</span>
                  <span v-if="nutrition.target" class="hf-mut unit">/ {{ vn(nutrition.target) }} kcal</span>
                  <span v-else class="hf-mut unit">kcal</span>
                </div>
              </div>
              <div v-if="nutrition.remaining != null" class="remain">
                <div class="remain-num">{{ nutrition.remaining >= 0 ? `Còn ${vn(nutrition.remaining)} kcal` : `Vượt ${vn(-nutrition.remaining)} kcal` }}</div>
                <div class="hf-mut small">so với mục tiêu hôm nay</div>
              </div>
            </div>
            <div v-if="nutrition.target" class="ndots" role="img"
                 :aria-label="`Đã ghi nhận ${vn(nutrition.energy)} trên ${vn(nutrition.target)} kcal, khoảng ${Math.round(nutrition.energy / nutrition.target * 100)} phần trăm`">
              <i v-for="(on, index) in nutrition.dots" :key="index" class="hf-dt" :class="{ on }" />
            </div>
            <div class="macro">
              <div class="protein">
                <div class="row-between"><span class="hf-mut">Protein đã ghi</span>
                  <b>{{ vn(nutrition.protein) }}{{ nutrition.proteinTarget ? ` / ${vn(nutrition.proteinTarget)}` : '' }} g</b></div>
                <div class="bar"><i :style="{ width: `${proteinPct}%` }" /></div>
              </div>
              <div class="end">
                <div v-if="nutrition.missing" class="hf-warn tight">{{ nutrition.missing }} món chưa đủ thông tin dinh dưỡng</div>
              </div>
            </div>
            <div v-if="!nutrition.target" class="hf-info">Chưa có mục tiêu năng lượng — cần hoàn thiện hồ sơ{{ nutrition.missingProfile.length ? ` (${nutrition.missingProfile.join(', ')})` : '' }}.</div>
            <div class="hf-acts">
              <button type="button" class="hf-btn pri" @click="emit('prefill', 'Ghi bữa ăn: ')">Ghi bữa ăn</button>
              <button type="button" class="hf-btn" @click="emit('detail', 'nutrition')">Xem chi tiết</button>
            </div>
          </template>
          <template v-else>
            <div class="hf-sv2">Chưa ghi nhận bữa ăn nào hôm nay</div>
            <p class="hf-mut para">Ghi bữa ăn qua trợ lý để theo dõi năng lượng và protein so với mục tiêu.</p>
            <div v-if="!nutrition.target" class="hf-info">Chưa có mục tiêu năng lượng — cần hoàn thiện hồ sơ (chiều cao, cân nặng, mức vận động, mục tiêu).</div>
            <div class="hf-acts">
              <button type="button" class="hf-btn pri" @click="emit('prefill', 'Ghi bữa ăn: ')">Ghi bữa ăn</button>
              <button v-if="!nutrition.target" type="button" class="hf-btn" @click="emit('settings', 'profile')">Hoàn thiện hồ sơ</button>
              <button v-else type="button" class="hf-btn" @click="emit('detail', 'nutrition')">Xem mục tiêu</button>
            </div>
          </template>
        </section>

        <!-- Khối 4: Nhịp tập tuần -->
        <section class="hf-card hf-c5" aria-labelledby="b4">
          <div class="hf-hd">
            <h2 id="b4" class="hf-lbl">Nhịp tập tuần này</h2>
            <span class="hf-pill">{{ week.range }}</span>
          </div>
          <template v-if="plan">
            <div class="baseline-row">
              <span class="hf-dg" style="font-size: 72px">{{ week.done }}</span>
              <span class="unit-strong">/ {{ week.due }} buổi đến hạn</span>
            </div>
            <div class="hf-mut small" style="margin-top: -6px">đã hoàn thành theo kế hoạch · Kế hoạch tuần: {{ week.total }} buổi</div>
            <div class="days">
              <div v-for="day in week.days" :key="day.sr" class="day">
                <span class="dc" :class="day.state" aria-hidden="true">{{ day.glyph }}</span>
                <span class="wd">{{ day.label }}</span>
                <span class="hf-sr">{{ day.sr }}</span>
              </div>
            </div>
            <div class="hf-lg">
              <span><i style="background: var(--hf-ink)" />Đã tập</span>
              <span><i style="border: 2px solid var(--hf-acc)" />Chưa hoàn thành</span>
              <span><i style="border: 2px dashed var(--hf-ink)" />Hôm nay / sắp tới</span>
              <span><i style="background: var(--hf-press)" />Nghỉ</span>
            </div>
            <div class="grow" />
            <div class="hf-acts"><button type="button" class="hf-btn pri" @click="emit('plan')">Xem kế hoạch</button></div>
          </template>
          <template v-else>
            <div class="hf-sv2">Chưa có kế hoạch tuần này</div>
            <p class="hf-mut para">Khi có lịch tập, tiến độ các buổi đã đến hạn sẽ hiển thị ở đây.</p>
            <div class="grow" />
            <div class="hf-acts"><button type="button" class="hf-btn pri" @click="emit('create-plan')">Lập lịch với trợ lý</button></div>
          </template>
        </section>
      </div>

      <ProfileAside :user="typedUser" :profile="health?.profile ?? null" :latest="latest" :metrics="data.metrics.value"
                    :goal="goal" :readiness="readiness" @edit="emit('settings', 'profile')" />
    </div>
  </div>
</template>

<style scoped>
.today { display: flex; flex-direction: column; gap: 16px; }
.err-text { display: flex; gap: 10px; align-items: center; }
.dash { display: grid; grid-template-columns: minmax(0, 1fr) 350px; gap: 16px; align-items: start; }
.headline { display: flex; align-items: center; gap: 18px; }
.badge { width: 14px; height: 14px; border-radius: 50%; flex: none; }
.b-ready { background: var(--hf-ink); box-shadow: 0 0 0 6px var(--hf-track); }
.b-reduce { background: #C2410C; box-shadow: 0 0 0 6px #FDE3D2; }
:root.dark .b-reduce { box-shadow: 0 0 0 6px #4A2614; }
.b-none { border: 2px dashed var(--hf-faint); }
.explain { display: flex; flex-direction: column; gap: 6px; max-width: 620px; }
.explain p { margin: 0; font-size: 15px; line-height: 1.55; }
.strong { font-weight: 600; }
.sigs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.sig { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 16px; background: var(--hf-fill-2); min-width: 0; }
.sig b { font-size: 13px; font-weight: 600; }
.sig span { font-size: 12px; color: var(--hf-muted); }
.grow { flex: 1; }
.session { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.session-name { min-width: 0; }
.count { text-align: right; flex: none; }
.count .hf-lbl { margin-top: 4px; }
.small { font-size: 13px; }
.session-name .small { font-size: 14px; margin-top: 6px; }
.pills { display: flex; gap: 8px; flex-wrap: wrap; }
.row { align-items: center; justify-content: space-between; flex-wrap: wrap; }
.para { margin: 0; font-size: 15px; line-height: 1.55; }
.energy { display: flex; align-items: flex-end; gap: 12px 28px; flex-wrap: wrap; }
.baseline-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.unit { font-size: 18px; font-weight: 600; }
.unit-strong { font-size: 18px; font-weight: 600; }
.remain { padding-bottom: 6px; }
.remain-num { font-size: 22px; font-weight: 700; }
.ndots { display: grid; grid-template-rows: repeat(4, 8px); grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 6px 4px; justify-items: center; }
.ndots .hf-dt { width: 8px; height: 8px; }
.macro { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.protein { display: flex; flex-direction: column; gap: 8px; }
.row-between { display: flex; justify-content: space-between; font-size: 13px; }
.bar { height: 8px; border-radius: 8px; background: var(--hf-line-2); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 8px; background: var(--hf-ink); }
.end { display: flex; flex-direction: column; justify-content: flex-end; }
.tight { padding: 8px 10px; }
.days { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; }
.day { display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 12px; color: var(--hf-muted); text-align: center; }
.wd { font-weight: 600; color: var(--hf-ink); }
.dc { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; }
.dc.done { background: var(--hf-ink); color: var(--hf-on-ink); }
.dc.missed { border: 2px solid var(--hf-acc); color: var(--hf-acc); }
.dc.today { border: 2px dashed var(--hf-ink); color: var(--hf-ink); }
.dc.up { border: 2px dashed var(--hf-line-3); color: var(--hf-faint); }
.dc.rest { background: var(--hf-fill); color: var(--hf-faint); }
@media (max-width: 1180px) { .dash { grid-template-columns: minmax(0, 1fr); } .dash > .pcard { order: -1; } }
@media (max-width: 760px) { .sigs { grid-template-columns: minmax(0, 1fr); } .macro { grid-template-columns: minmax(0, 1fr); } }
</style>
