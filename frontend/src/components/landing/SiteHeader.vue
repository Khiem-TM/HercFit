<script setup lang="ts">
import { shallowRef } from "vue";
import { Menu, UserRound, X } from "lucide-vue-next";
import { useAuth } from "@/composables/useAuth";
import ThemeToggle from "@/components/ThemeToggle.vue";

const { isAuthenticated, loginWithGoogle } = useAuth();
const menuOpen = shallowRef(false);
const links = [
  { label: "Tổng quan", href: "#archive" },
  { label: "Agent", href: "#agents" },
  { label: "Tri thức", href: "#knowledge" },
  { label: "Quy trình", href: "#protocols" },
  { label: "Bắt đầu", href: "#access" },
];

function handleEnterChat(): void {
  menuOpen.value = false;
  if (isAuthenticated.value) {
    window.history.pushState({}, "", "/chat");
    window.dispatchEvent(new PopStateEvent("popstate"));
  } else {
    loginWithGoogle();
  }
}
</script>

<template>
  <header
    class="fixed top-0 left-0 w-full z-50 bg-background/90 backdrop-blur-md border-b border-outline-variant/40"
    @keydown.esc="menuOpen = false"
  >
    <div
      class="h-16 w-full max-w-[1440px] mx-auto px-margin-mobile md:px-margin lg:px-margin-desktop flex items-center justify-between gap-4"
    >
      <a
        class="flex items-center gap-space-sm shrink-0"
        href="#archive"
        aria-label="HercFit — về đầu trang"
        @click="menuOpen = false"
      >
        <span
          class="font-label-code text-label-code text-primary tracking-[0.2em] font-medium"
          >HERCFIT</span
        >
        <span
          class="font-label-telemetry text-label-telemetry text-outline tracking-widest hidden sm:inline-block"
          >// AI NUTRITION &amp; TRAINING</span
        >
      </a>
      <nav
        class="hidden lg:flex items-center gap-5 font-label-code text-[10px] tracking-[0.14em] uppercase"
        aria-label="Điều hướng chính"
      >
        <a
          v-for="link in links"
          :key="link.href"
          :href="link.href"
          class="py-2 text-on-surface-variant hover:text-primary transition-colors"
          >{{ link.label }}</a
        >
      </nav>
      <div class="flex items-center gap-space-md">
        <button
          type="button"
          class="inline-flex items-center gap-2 px-3.5 py-1.5 bg-primary text-background font-label-code text-[11px] uppercase tracking-[0.16em] font-medium border border-primary hover:bg-background hover:text-primary transition-colors whitespace-nowrap"
          @click="handleEnterChat"
        >
          <UserRound :size="14" :stroke-width="1.8" aria-hidden="true" />
          {{ isAuthenticated ? "VÀO TRỢ LÝ" : "ĐĂNG NHẬP" }}
        </button>
        <ThemeToggle class="!h-8 !w-8 !rounded-full" />
        <button
          class="lg:hidden text-primary p-2"
          type="button"
          :aria-expanded="menuOpen"
          aria-controls="mobile-navigation"
          :aria-label="menuOpen ? 'Đóng menu' : 'Mở menu'"
          @click="menuOpen = !menuOpen"
        >
          <X v-if="menuOpen" :size="20" /><Menu v-else :size="20" />
        </button>
      </div>
    </div>
    <nav
      v-if="menuOpen"
      id="mobile-navigation"
      class="lg:hidden flex flex-col bg-background border-t border-outline-variant/40 px-margin-mobile py-4 font-label-code text-label-code uppercase tracking-widest"
      aria-label="Điều hướng trên điện thoại"
    >
      <a
        v-for="link in links"
        :key="link.href"
        :href="link.href"
        class="py-3 border-b border-outline-variant/20 hover:text-primary"
        @click="menuOpen = false"
        >{{ link.label }}</a
      >
    </nav>
  </header>
</template>
