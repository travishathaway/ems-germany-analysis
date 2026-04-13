import { defineConfig } from 'vite';
import { buildQuarto, QMD_SRC, INDEX_HTML } from './scripts/build-quarto.js';

const DATA_DIR = process.env.VITE_DATA_DIR ?? '.';

/** Vite plugin: watches full_report.qmd and rebuilds index.html on change. */
function quartoWatchPlugin() {
  let isServe = false;
  return {
    name: 'quarto-watch',
    config(_, { command }) {
      isServe = command === 'serve';
    },
    // On dev-server start, do an initial render so index.html exists.
    async buildStart() {
      if (isServe) await buildQuarto();
    },
    configureServer(server) {
      // Tell Vite to watch the .qmd file (it lives outside web/, so we must
      // add it explicitly).
      server.watcher.add(QMD_SRC);

      server.watcher.on('change', async (file) => {
        if (file !== QMD_SRC) return;
        console.log('[quarto-watch] full_report.qmd changed — re-rendering…');
        await buildQuarto();
        // Invalidate index.html in Vite's module graph so it picks up the new
        // content, then trigger a full page reload in the browser.
        const mod = server.moduleGraph.getModuleById(INDEX_HTML);
        if (mod) server.moduleGraph.invalidateModule(mod);
        server.ws.send({ type: 'full-reload' });
      });
    },
  };
}

export default defineConfig({
  root: '.',
  plugins: [quartoWatchPlugin()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // Vendor chunks (plotly, maplibre) exceed 500 kB pre-gzip by design.
    // Gzip transfer sizes are well within reason: plotly ~478 kB, maplibre ~218 kB.
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      input: 'index.html',
      output: {
        // Content-hashed filenames for long-lived caching
        entryFileNames: 'bundle.[hash].js',
        chunkFileNames: 'chunk.[name].[hash].js',
        assetFileNames: 'assets/[name].[hash][extname]',
        // Split heavy vendors into separate cacheable chunks so a JS-only
        // change doesn't bust the large vendor caches.
        manualChunks: {
          'vendor-plotly':   ['plotly.js-cartesian-dist'],
          'vendor-maplibre': ['maplibre-gl'],
          'vendor-pmtiles':  ['pmtiles'],
        },
      },
    },
  },
  define: {
    __DATA_DIR__: JSON.stringify(DATA_DIR),
  },
});
