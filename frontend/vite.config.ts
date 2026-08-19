import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Served at the root, not a subpath. deep-search (the recipe this
  // scaffold started from) serves its React build under ADK's own /app/
  // mount; we haven't built that Cloud Run subpath-serving story yet
  // (Milestone 17). A "/app/" base with no matching React Router basename
  // broke every direct navigation, refresh, and bookmark — found live
  // (Milestone 6) by actually navigating the app, not just building it.
  resolve: {
    alias: {
      "@": path.resolve(new URL(".", import.meta.url).pathname, "./src"),
    },
  },
  server: {
    // Makes the server accessible on the local network (e.g., for mobile testing)
    host: true,
    // Should be disabled or limited when deployed in untrusted network environments.
    allowedHosts: true,
    proxy: {
      // Proxy API requests to the backend server
      "/api": {
        target: "http://127.0.0.1:8000", // Default backend address
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
