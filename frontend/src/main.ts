import { createApp } from "vue";
import App from "./App.vue";
import { initTheme } from "./composables/useTheme";
import { installMotionTokens } from "./motion/tokens";
import "./assets/main.css";

initTheme();
installMotionTokens();
createApp(App).mount("#app");
