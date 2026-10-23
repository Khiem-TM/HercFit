<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { Loader2 } from "lucide-vue-next";
import SiteHeader from "./components/landing/SiteHeader.vue";
import HeroSection from "./components/landing/HeroSection.vue";
import AgentSection from "./components/landing/AgentSection.vue";
import KnowledgeSection from "./components/landing/KnowledgeSection.vue";
import ProtocolSection from "./components/landing/ProtocolSection.vue";
import AccessSection from "./components/landing/AccessSection.vue";
import SiteFooter from "./components/landing/SiteFooter.vue";
import ChatPage from "./views/ChatPage.vue";
import { useAuth } from "./composables/useAuth";

import { authenticatedDestination } from './features/onboarding/model';
const OnboardingPage = defineAsyncComponent(() => import('./views/OnboardingPage.vue'));
const selectedAgent = shallowRef("");
const currentPath = ref(window.location.pathname);
const { user, isAuthenticated, isLoading, error, bootstrapAuth, loginWithGoogle } = useAuth();

function syncPath(): void {
  currentPath.value = window.location.pathname;
}

function navigateTo(path: string): void {
  if (window.location.pathname !== path) {
    window.history.pushState({}, "", path);
  }
  currentPath.value = path;
}

const isProtectedRoute = computed(
  () =>
    currentPath.value.startsWith("/chat") ||
    currentPath.value.startsWith("/onboarding") ||
    currentPath.value.startsWith("/auth/callback"),
);

watch([isAuthenticated, isLoading, () => user.value?.is_onboarding, currentPath], () => {
  if (!isAuthenticated.value || isLoading.value) return;
  const destination = authenticatedDestination(currentPath.value, user.value?.is_onboarding === true);
  if (destination !== currentPath.value) {
    window.history.replaceState({}, '', destination);
    currentPath.value = destination;
  }
}, { immediate: true });

onMounted(async () => {
  window.addEventListener("popstate", syncPath);
  await bootstrapAuth();
});

onBeforeUnmount(() => {
  window.removeEventListener("popstate", syncPath);
});
</script>

<template>
  <!-- Authenticated Chat Workspace -->
  <OnboardingPage v-if="isAuthenticated && !isLoading && !user?.is_onboarding" />
  <ChatPage v-else-if="isAuthenticated && !isLoading" />

  <!-- Loading Auth Session / Exchanging Google OAuth Code -->
  <div
    v-else-if="(isProtectedRoute || isAuthenticated) && isLoading"
    class="flex h-screen w-screen flex-col items-center justify-center bg-background text-primary"
  >
    <Loader2 class="h-7 w-7 animate-spin text-primary" />
    <p class="mt-3 font-label-code text-xs uppercase tracking-[0.2em] text-outline">
      ĐANG XÁC THỰC GOOGLE OAUTH // OLYMPUS...
    </p>
  </div>

  <!-- Unauthenticated Gate on /chat or Failed Callback -->
  <div
    v-else-if="isProtectedRoute && !isAuthenticated"
    class="relative flex h-screen w-screen flex-col items-center justify-center bg-background px-4 text-primary"
  >
    <div class="grain-overlay pointer-events-none" aria-hidden="true" />
    <div
      class="relative z-10 w-full max-w-md rounded-3xl border border-white/15 bg-[#141414] p-8 text-center shadow-2xl"
    >
      <p class="font-label-telemetry text-[10px] uppercase tracking-[0.22em] text-outline">
        PROTOCOL // AUTHENTICATION REQUIRED
      </p>
      <h1 class="mt-2 font-headline-md text-2xl font-normal text-primary">
        Đăng nhập vào HercFit AI
      </h1>
      <p class="mt-2 text-xs leading-relaxed text-on-surface-variant">
        Sử dụng tài khoản Google để đồng bộ lịch sử hội thoại, mục tiêu thể hình và nhật ký dinh dưỡng.
      </p>
      <div
        v-if="error"
        class="mt-4 rounded-xl border border-error/40 bg-error/10 px-3.5 py-2 text-xs text-error"
      >
        {{ error }}
      </div>
      <button
        type="button"
        class="mt-6 w-full rounded-xl bg-white px-5 py-3 font-label-code text-xs font-semibold uppercase tracking-[0.18em] text-[#0e0e0e] transition-transform hover:scale-[1.02]"
        @click="loginWithGoogle"
      >
        [ ĐĂNG NHẬP VỚI GOOGLE ]
      </button>
      <button
        type="button"
        class="mt-3 w-full py-2 font-label-code text-[11px] uppercase tracking-wider text-outline hover:text-primary"
        @click="navigateTo('/')"
      >
        ← Quay về Trang chủ
      </button>
    </div>
  </div>

  <!-- Default Landing Page -->
  <template v-else>
    <a class="skip-link" href="#main-content">Bỏ qua điều hướng</a>
    <SiteHeader />
    <main id="main-content" class="pt-16 relative overflow-hidden">
      <HeroSection />
      <AgentSection
        :selected-agent="selectedAgent"
        @select="selectedAgent = $event"
      />
      <KnowledgeSection />
      <ProtocolSection />
      <AccessSection :selected-agent="selectedAgent" />
    </main>
    <SiteFooter />
    <div class="grain-overlay" aria-hidden="true"></div>
  </template>
</template>
