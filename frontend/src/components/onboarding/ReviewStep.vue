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
    <label class="confirm-choice"><input v-model="form.confirmed" type="checkbox" :aria-invalid="Boolean(errors.confirmed)" /><span>Tôi đã kiểm tra và đồng ý lưu thông tin này vào hồ sơ HercFit, và đồng ý để tin nhắn cùng dữ liệu sức khoẻ của tôi được xử lý bởi các dịch vụ AI bên thứ ba như mô tả dưới đây.</span></label><p v-if="errors.confirmed" class="field-error" role="alert">{{ errors.confirmed }}</p>
    <!-- Tóm tắt docs/DATA_FLOW.md: sửa cả hai khi luồng dữ liệu thay đổi. -->
    <details class="data-flow">
      <summary>Dữ liệu của bạn đi đâu</summary>
      <ul>
        <li><strong>FPT AI</strong> (model ngôn ngữ): tin nhắn và dữ liệu bạn ghi trong HercFit cần cho câu trả lời; dữ liệu thiết bị chỉ khi bạn bật chia sẻ với trợ lý.</li>
        <li><strong>Tavily</strong> (tìm kiếm web): chỉ câu hỏi kiến thức công khai, đã bỏ số đo và thông tin định danh.</li>
        <li><strong>Jev</strong> (kiểm định câu trả lời, khi được bật): tin nhắn mới nhất và nguồn công khai, đã che thông tin định danh.</li>
        <li><strong>Langfuse</strong> (truy vết vận hành, khi được bật): ID được thay bằng bí danh; họ tên, email và số đo sức khoẻ bị che.</li>
        <li><strong>Google Health</strong> (khi bạn kết nối): đọc dữ liệu thiết bị, ghi các bản ghi bạn tự nhập.</li>
        <li><strong>Cloudinary</strong>: ảnh bạn tải lên cho bữa ăn và buổi tập.</li>
      </ul>
      <p>Bạn có thể xuất dữ liệu hoặc xoá tài khoản, kèm toàn bộ hội thoại, trong Cài đặt.</p>
    </details>
    <p class="privacy-note"><ShieldCheck :size="16" /><span>Bạn có thể cập nhật hồ sơ, ghi số đo mới và điều chỉnh mục tiêu trong quá trình sử dụng.</span></p>
  </div>
</template>
