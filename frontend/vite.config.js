import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";

export default defineConfig({
  plugins: [
    vue(),
    Components({ resolvers: [ElementPlusResolver()], dts: false }),
  ],
  optimizeDeps: {
    include: [
      "vue",
      "vue-router",
      "pinia",
      "element-plus",
      "element-plus/es",
      "@element-plus/icons-vue",
    ],
  },
  resolve: {
    dedupe: ["vue"],
    preserveSymlinks: true,
  },
  server: {
    host: "0.0.0.0",
    port: 5174,
    proxy: {
      "/uploads": {
        target: "http://127.0.0.1:5002",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:5002",
        changeOrigin: true,
      },
    },
  },
});
