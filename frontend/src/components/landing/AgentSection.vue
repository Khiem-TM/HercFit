<script setup lang="ts">
/**
 * Kiến trúc multi-agent như đang chạy (backend/agentic/core/roster.py): supervisor phân loại một lần rồi giao cho agent
 * sở hữu miền dữ liệu; research tra nguồn, synthesizer viết câu trả lời. Chỉ mô tả việc hệ thống làm, không số liệu.
 */
const agents = [
  {
    name: "SUPERVISOR",
    category: "ĐIỀU PHỐI",
    description:
      "Luật định tuyến do code sở hữu chạy trước và sau lời gọi model: đường nhanh cho câu ghi đơn giản, chặn an toàn, hỏi lại khi thiếu thông tin, tách câu nhiều việc cho các agent chạy song song.",
    metrics: [
      ["ĐỊNH TUYẾN", "LUẬT + MODEL"],
      ["NHIỀU VIỆC", "SONG SONG"],
    ],
  },
  {
    name: "NUTRITION",
    category: "DINH DƯỠNG",
    description:
      "Bữa ăn và món ăn theo gam/ml từ danh mục có ảnh. Món chưa có trong danh mục được hỏi lại; macro do AI gợi ý luôn được gắn nhãn ước tính, tách khỏi số liệu có nguồn.",
    metrics: [
      ["MIỀN", "MEALS · FOODS"],
      ["GHI", "QUA THẺ XÁC NHẬN"],
    ],
  },
  {
    name: "TRAINING · COACH",
    category: "TẬP LUYỆN",
    description:
      "Nhật ký buổi tập và bài tập, calo theo MET của Compendium of Physical Activities; coach lập lịch tập theo mục tiêu, lịch chỉ được lưu khi bạn duyệt.",
    metrics: [
      ["MIỀN", "TRAININGS · PLANS"],
      ["CALO", "MET · ACSM"],
    ],
  },
  {
    name: "BODY · DAILY HEALTH",
    category: "SỨC KHOẺ",
    description:
      "Số đo, tiến độ và dữ liệu thiết bị từ Google Health (chỉ khi bạn cho phép). Đánh giá sẵn sàng hằng ngày do code tính tất định; agent chỉ đọc và giải thích.",
    metrics: [
      ["MIỀN", "METRICS · HEALTH"],
      ["QUYỀN", "CHỈ ĐỌC THIẾT BỊ"],
    ],
  },
];
</script>

<template>
  <section
    id="agents"
    class="px-margin-mobile md:px-margin lg:px-margin-desktop py-space-xl border-b border-outline-variant/30"
  >
    <div
      class="flex flex-col md:flex-row md:items-end justify-between mb-space-xl gap-space-md"
    >
      <div>
        <span class="eyebrow">// MULTI-AGENT · LANGGRAPH</span>
        <h2 class="section-heading">AGENT CHUYÊN TRÁCH THEO MIỀN</h2>
      </div>
      <p class="font-body-sm text-body-sm text-on-surface-variant max-w-sm">
        Supervisor phân loại yêu cầu một lần rồi giao cho agent sở hữu miền dữ
        liệu đó; mỗi agent có thể chạy model riêng. Research tra nguồn đã kiểm
        chứng, synthesizer viết câu trả lời cuối.
      </p>
    </div>
    <div
      class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-outline-variant/30 p-px"
    >
      <article
        v-for="(agent, index) in agents"
        :key="agent.name"
        class="agent-card bg-surface p-space-lg flex flex-col justify-between min-h-[300px] lg:min-h-[340px] hover:bg-surface-container-low transition-colors duration-200"
      >
        <div class="flex flex-col gap-space-md">
          <div
            class="flex justify-between gap-2 font-label-telemetry text-label-telemetry text-outline"
          >
            <span>[AGENT 0{{ index + 1 }}]</span
            ><span class="text-primary tracking-widest">{{
              agent.category
            }}</span>
          </div>
          <h3
            class="font-headline-md text-headline-md text-primary tracking-wide"
          >
            {{ agent.name }}
          </h3>
          <p
            class="font-body-sm text-body-sm text-on-surface-variant leading-relaxed"
          >
            {{ agent.description }}
          </p>
        </div>
        <div
          class="space-y-space-sm pt-space-md mt-8 border-t border-outline-variant/20 font-label-code text-[11px] text-outline"
        >
          <div
            v-for="metric in agent.metrics"
            :key="metric[0]"
            class="flex justify-between gap-3"
          >
            <span>{{ metric[0] }}</span
            ><span class="text-primary text-right">{{ metric[1] }}</span>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
