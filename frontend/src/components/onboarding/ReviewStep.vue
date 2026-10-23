<script setup lang="ts">
import { Check, ShieldCheck } from 'lucide-vue-next'
import { activityChoices, type OnboardingForm, type FieldErrors } from '@/features/onboarding/model'
const form = defineModel<OnboardingForm>({required:true})
defineProps<{errors:FieldErrors; existingGoal?:string}>()
</script>
<template>
  <div class="step-fields">
    <section class="review-section"><span class="review-icon"><Check :size="15" /></span><div><h3>Hồ sơ cá nhân</h3><p>{{ form.fullname }}<span v-if="form.nickname"> · {{ form.nickname }}</span><span v-if="form.age"> · {{ form.age }} tuổi</span></p><p v-if="form.activity">{{ activityChoices.find(c=>c.value===form.activity)?.label }}</p><p v-if="form.notes" class="review-notes">{{ form.notes }}</p></div></section>
    <section class="review-section"><span class="review-icon"><Check :size="15" /></span><div><h3>Số đo đầu tiên</h3><p v-if="!form.metricsEnabled">Sẽ bổ sung sau</p><template v-else><p>{{ form.weight }} kg <span v-if="form.height">· {{ form.height }} cm</span></p><p v-if="form.bodyFat || form.muscleMass"><span v-if="form.bodyFat">Mỡ cơ thể: {{ form.bodyFat }}% </span><span v-if="form.muscleMass">· Khối lượng cơ: {{ form.muscleMass }} kg</span></p></template></div></section>
    <section class="review-section"><span class="review-icon"><Check :size="15" /></span><div><h3>Mục tiêu</h3><p v-if="existingGoal">Giữ mục tiêu: {{ existingGoal }}</p><p v-else-if="!form.goalEnabled">Sẽ khám phá sau</p><template v-else><p>{{ form.goalTitle }}</p><p>{{ form.startDate }}<span v-if="form.targetDate"> → {{ form.targetDate }}</span><span v-if="form.targetWeight"> · Đích {{ form.targetWeight }} kg</span></p></template></div></section>
    <label class="confirm-choice"><input v-model="form.confirmed" type="checkbox" :aria-invalid="Boolean(errors.confirmed)" /><span>Tôi đã kiểm tra và đồng ý lưu thông tin này vào hồ sơ HercFit.</span></label><p v-if="errors.confirmed" class="field-error" role="alert">{{ errors.confirmed }}</p>
    <p class="privacy-note"><ShieldCheck :size="16" /><span>Bạn có thể cập nhật hồ sơ, ghi số đo mới và điều chỉnh mục tiêu trong quá trình sử dụng.</span></p>
  </div>
</template>
