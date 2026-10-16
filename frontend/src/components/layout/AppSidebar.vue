<script setup lang="ts">
// TODO: Cấu hình danh sách điều hướng chính (Dashboard, Chat, Workouts, Nutrition, Habits, Profile)
</script>

<template>
  <aside class="w-64 border-r border-slate-800 bg-slate-900 p-4">
    <div class="font-bold text-lg text-emerald-400 mb-6">HercFit</div>
    <nav class="space-y-2 text-sm">
      <RouterLink to="/" class="block px-3 py-2 rounded hover:bg-slate-800">Tổng quan</RouterLink>
      <RouterLink to="/chat" class="block px-3 py-2 rounded hover:bg-slate-800">AI Coach</RouterLink>
      <RouterLink to="/workouts" class="block px-3 py-2 rounded hover:bg-slate-800">Tập luyện</RouterLink>
      <RouterLink to="/nutrition" class="block px-3 py-2 rounded hover:bg-slate-800">Dinh dưỡng</RouterLink>
      <RouterLink to="/habits" class="block px-3 py-2 rounded hover:bg-slate-800">Thói quen</RouterLink>
      <RouterLink to="/profile" class="block px-3 py-2 rounded hover:bg-slate-800">Hồ sơ</RouterLink>
    </nav>
  </aside>
</template>
