<script setup lang="ts">
import { watch } from "vue";
import { useAccessRequest } from "../../composables/useAccessRequest";
import { useAuth } from "@/composables/useAuth";

const props = defineProps<{ selectedAgent: string }>();
const { email, saved, error, submit, reset, remove } = useAccessRequest();
const { isAuthenticated, loginWithGoogle } = useAuth();
watch(() => props.selectedAgent, reset);

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
          class="lg:col-span-5 relative min-h-[480px] lg:min-h-[580px] overflow-hidden border-b lg:border-b-0 lg:border-r border-outline-variant/40 group"
        >
          <img
            alt="Celestial Mythic Sculpture"
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
              >ARCHIVE // CANON 09</span
            ><span
              class="backdrop-blur-sm bg-background/50 px-space-sm py-1 border border-outline-variant/30"
              >ASCENSION</span
            >
          </div>
          <div
            class="absolute bottom-0 left-0 right-0 z-10 p-space-md border-t border-outline-variant/40 backdrop-blur-sm bg-background/50 flex justify-between items-center font-label-code text-[10px] text-on-surface-variant"
          >
            <span>DIVINE ARCHITECTURE</span
            ><span class="text-primary font-medium">[IMMORTAL]</span>
          </div>
        </div>
        <div
          class="lg:col-span-7 p-space-lg md:p-space-xl flex flex-col justify-between text-left"
        >
          <div class="space-y-space-md">
            <div>
              <span
                class="font-label-telemetry text-label-telemetry text-outline uppercase tracking-widest block mb-space-xs"
                >[RESTRICTED SANCTUM // ALPHA REGISTRY]</span
              >
              <h3
                class="font-headline-lg text-primary uppercase tracking-tight font-normal leading-tight text-headline-lg-mobile md:text-headline-lg"
              >
                BUILD YOUR BODY,<br />BUILD YOUR CONSISTENCY
              </h3>
              <div class="w-12 h-px bg-outline-variant/60 my-space-md"></div>
              <p
                class="font-quote-editorial text-[18px] text-primary italic leading-relaxed"
              >
                “Mỗi bước chuyển động là sự rèn giũa thể xác, mỗi ngày kiên định
                là sự tạo tác thần thể.”
              </p>
              <p
                class="font-body-sm text-body-sm text-on-surface-variant leading-relaxed mt-space-sm"
              >
                Quyền truy cập hạn chế vào hệ thống giải mã sinh học đa tác tử.
                Vượt qua ngưỡng giới hạn tự nhiên qua sự kỷ luật tuyệt đối và
                trí tuệ nhân tạo tương hỗ.
              </p>
            </div>
            <label class="sr-only" for="access-email">Địa chỉ email</label>
            <p
              aria-live="polite"
              class="font-label-telemetry text-label-telemetry text-outline uppercase tracking-wider"
            >
              PROTOCOL // {{ selectedAgent || "OLYMPUS — ALL AGENTS" }}
            </p>
            <div class="pt-space-xs">
              <button
                type="button"
                class="w-full px-space-md py-3.5 bg-primary text-background font-label-code text-label-code uppercase tracking-[0.2em] font-medium border border-primary hover:bg-background hover:text-primary transition-colors flex items-center justify-center gap-2.5"
                @click="handleOAuthLogin"
              >
                <span>[ ĐĂNG NHẬP BẰNG GOOGLE // TRUY CẬP TRỢ LÝ AI ]</span>
              </button>
            </div>
            <form
              @submit.prevent="submit(selectedAgent)"
              aria-label="Đăng ký truy cập Olympus"
              class="w-full flex flex-col sm:flex-row gap-space-xs items-stretch pt-space-sm"
            >
              <input
                @input="reset"
                autocomplete="email"
                class="flex-1 px-space-md py-3 bg-surface-container-low border border-outline-variant/60 font-label-code text-label-code text-on-surface placeholder:text-outline focus:outline-none focus:border-primary transition-colors min-w-0 w-full"
                id="access-email"
                maxlength="254"
                name="email"
                placeholder="YOUR EMAIL // ĐỊA CHỈ EMAIL"
                :required="true"
                type="email"
                v-model="email"
              /><button
                :disabled="saved"
                class="px-space-md py-3 bg-primary text-background font-label-code text-label-code uppercase tracking-[0.2em] font-medium border border-primary hover:bg-background hover:text-primary transition-colors shrink-0"
                type="submit"
              >
                {{ saved ? "SAVED LOCALLY ✓" : "REQUEST ACCESS" }}
              </button>
            </form>
            <div
              aria-live="polite"
              class="font-body-sm text-body-sm text-on-surface-variant"
            >
              <p class="text-error" role="alert" v-if="error">{{ error }}</p>
              <div v-else-if="saved">
                <p>
                  Đã lưu yêu cầu trên thiết bị này. Email chưa được gửi đến máy
                  chủ.
                </p>
                <button
                  @click="remove"
                  class="underline underline-offset-4 mt-2 hover:text-primary"
                  type="button"
                >
                  Xoá yêu cầu đã lưu
                </button>
              </div>
              <p class="text-outline" v-else="">
                Bản xem trước — yêu cầu chỉ được lưu trong trình duyệt của bạn.
              </p>
            </div>
          </div>
          <div
            class="pt-space-lg border-t border-outline-variant/30 mt-space-lg flex flex-wrap items-center justify-between gap-space-sm font-label-telemetry text-[9px] text-outline uppercase tracking-widest"
          >
            <span>ENCRYPTION // 4096-BIT RSA</span
            ><span>SLOTS REMAINING // 14</span><span>COORD // 37.9838° N</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
