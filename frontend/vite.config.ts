import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Served at the root, not a subpath. deep-search (the recipe this
  // scaffold started from) serves its React build under ADK's own /app/
  // mount; a "/app/" base with no matching React Router basename broke
  // every direct navigation, refresh, and bookmark — found live
  // (Milestone 6) by actually navigating the app, not just building it.
  // Milestone 17 bundles this build into the same Cloud Run service as
  // the backend at root (fast_api_app.py's `_mount_frontend`), so root
  // stays correct in both dev and prod.
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
      // Proxy API requests to the backend server. No path rewrite — the
      // backend mounts its REST routes under /api itself (fast_api_app.py),
      // the same prefix used when this app is bundled into the same Cloud
      // Run service in production, so dev and prod hit the same paths.
      "/api": {
        target: "http://127.0.0.1:8000", // Default backend address
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
