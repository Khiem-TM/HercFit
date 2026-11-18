<script setup lang="ts">
import { useAuth } from "@/composables/useAuth";

const { isAuthenticated, loginWithGoogle } = useAuth();

// Những gì có ngay sau khi đăng nhập; mỗi dòng là một tính năng đang chạy, không phải lời hứa.
const features = [
  ["CHAT · GIỌNG NÓI", "Ghi bữa ăn, buổi tập, số đo bằng tiếng Việt; duyệt thẻ bằng nút hoặc câu “xác nhận”."],
  ["DASHBOARD", "Hôm nay, tiến độ, kế hoạch tập và bản đồ dữ liệu cá nhân."],
  ["THÔNG BÁO", "Cảnh báo chỉ số theo ngưỡng của Bộ Y tế, WHO và hội chuyên môn; không phải chẩn đoán."],
  ["DỮ LIỆU CỦA BẠN", "Google Health chỉ dùng khi bạn cho phép; xuất hoặc xoá toàn bộ dữ liệu trong cài đặt."],
];

function handleOAuthLogin(): void {
  if (isAuthenticated.value) {
    window.history.pushState({}, "", "/chat");
    window.dispatchEvent(new PopStateEvent("popstate"));
  } else {
    loginWithGoogle();
  }
}
</script>

<template>
  <section
    class="w-full px-margin-mobile md:px-margin lg:px-margin-desktop py-space-xl"
    id="access"
  >
    <div
      class="max-w-5xl mx-auto border border-outline-variant/60 p-2 bg-surface-container-lowest relative overflow-hidden"
    >
      <div
        class="border border-outline-variant/40 relative grid grid-cols-1 lg:grid-cols-12 overflow-hidden bg-surface-container-lowest"
      >
        <div
          class="lg:col-span-5 relative min-h-[360px] lg:min-h-[560px] overflow-hidden border-b lg:border-b-0 lg:border-r border-outline-variant/40 group"
        >
          <img
            alt="Tượng cẩm thạch vươn lên, nền trời"
            class="absolute inset-0 w-full h-full object-cover object-center filter grayscale contrast-125 brightness-95 select-none pointer-events-none transition-transform duration-700 group-hover:scale-105"
            decoding="async"
            height="1024"
            loading="lazy"
            src="/images/ascension.png"
            width="768"
          />
          <div
            class="absolute inset-0 bg-gradient-to-b from-background/80 via-transparent to-background/90 pointer-events-none"
          ></div>
          <div
            class="relative z-10 w-full p-space-md flex justify-between font-label-telemetry text-label-telemetry text-outline"
          >
            <span
              class="backdrop-blur-sm bg-background/50 px-space-sm py-1 border border-outline-variant/30"
              >FIG 04</span
            ><span
              class="backdrop-blur-sm bg-background/50 px-space-sm py-1 border border-outline-variant/30"
              >BẮT ĐẦU</span
            >
          </div>
          <div
            class="absolute bottom-0 left-0 right-0 z-10 p-space-md border-t border-outline-variant/40 backdrop-blur-sm bg-background/50 flex justify-between items-center font-label-code text-[11px] text-on-surface-variant"
          >
            <span>HERCFIT</span
            ><span class="text-primary font-medium">[GOOGLE OAUTH]</span>
          </div>
        </div>
        <div
          class="lg:col-span-7 p-space-lg md:p-space-xl flex flex-col justify-between text-left"
        >
          <div class="space-y-space-md">
            <div>
              <span
                class="font-label-telemetry text-label-telemetry text-outline uppercase tracking-widest block mb-space-xs"
                >[BẮT ĐẦU]</span
              >
              <h3
                class="font-headline-lg text-primary uppercase tracking-tight font-bold leading-tight text-headline-lg-mobile md:text-headline-lg"
              >
                GHI BỮA ĂN ĐẦU TIÊN<br />TRONG MỘT CÂU
              </h3>
              <div class="w-12 h-px bg-outline-variant/60 my-space-md"></div>
              <p
                class="font-body-md text-body-md text-on-surface-variant leading-relaxed"
              >
                Đăng nhập bằng Google, khai báo vài thông tin cơ bản (số đo và
                mục tiêu có thể bổ sung sau), rồi nhắn như với một huấn luyện
                viên.
              </p>
            </div>
            <dl
              class="border-t border-outline-variant/30 divide-y divide-outline-variant/20"
            >
              <div
                v-for="[label, text] in features"
                :key="label"
                class="py-space-sm grid grid-cols-1 sm:grid-cols-[150px_1fr] gap-1 sm:gap-space-md"
              >
                <dt
                  class="font-label-code text-label-code text-primary uppercase tracking-wider"
                >
                  {{ label }}
                </dt>
                <dd class="font-body-sm text-body-sm text-on-surface-variant">
                  {{ text }}
                </dd>
              </div>
            </dl>
            <div class="pt-space-xs">
              <button
                type="button"
                class="w-full px-space-md py-3.5 bg-primary text-background font-label-code text-label-code uppercase tracking-[0.2em] font-medium border border-primary hover:bg-background hover:text-primary transition-colors flex items-center justify-center gap-2.5"
                @click="handleOAuthLogin"
              >
                <span>{{
                  isAuthenticated
                    ? "[ VÀO TRỢ LÝ ]"
                    : "[ ĐĂNG NHẬP BẰNG GOOGLE ]"
                }}</span>
              </button>
            </div>
          </div>
          <div
            class="pt-space-lg border-t border-outline-variant/30 mt-space-lg flex flex-wrap items-center justify-between gap-space-sm font-label-telemetry text-[10px] text-outline uppercase tracking-widest"
          >
            <span>ĐĂNG NHẬP // GOOGLE OAUTH</span
            ><span>TOKEN THIẾT BỊ // MÃ HOÁ KHI LƯU</span
            ><span>DỮ LIỆU // XUẤT · XOÁ</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
