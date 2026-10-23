<script setup lang="ts">
import OnboardingField from './OnboardingField.vue'
import { activityChoices, type OnboardingForm, type FieldErrors } from '@/features/onboarding/model'
const form = defineModel<OnboardingForm>({ required:true })
defineProps<{ errors:FieldErrors }>()
</script>
<template>
  <div class="step-fields">
    <OnboardingField id="fullname" v-model="form.fullname" label="Họ và tên *" autocomplete="name" maxlength="255" :error="errors.fullname" placeholder="Tên của bạn" />
    <div class="two-columns"><OnboardingField id="nickname" v-model="form.nickname" label="Bạn muốn được gọi là gì?" autocomplete="nickname" maxlength="100" :error="errors.nickname" placeholder="Biệt danh (tùy chọn)" /><OnboardingField id="age" v-model="form.age" label="Tuổi (tùy chọn)" type="number" inputmode="numeric" min="1" max="120" step="1" :error="errors.age" placeholder="Ví dụ: 28" /></div>
    <div class="select-field"><label for="activity">Nhịp vận động thường ngày</label><select id="activity" v-model="form.activity" :aria-invalid="Boolean(errors.activity)"><option value="">Chưa cung cấp</option><option v-for="choice in activityChoices" :key="choice.value" :value="choice.value">{{ choice.label }}</option></select><p v-if="errors.activity" class="field-error" role="alert">{{ errors.activity }}</p></div>
    <div class="select-field"><label for="notes">Điều bạn muốn HercFit biết <span>· Tùy chọn</span></label><textarea id="notes" v-model="form.notes" rows="3" placeholder="Thói quen ăn uống, sở thích tập luyện, thời gian có thể dành cho bản thân…" /><p class="field-hint">Chỉ chia sẻ những điều bạn muốn lưu vào hồ sơ cá nhân.</p></div>
  </div>
</template>
