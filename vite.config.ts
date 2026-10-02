import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { DIVISION_MASTER_STATIONS, queryDivisionBuses } from './src/server/divisionData.ts';

/**
 * Vite Dev Server API Plugin
 * Implements real HTTP endpoints for /api/v1/stations and /api/v1/buses/search
 * serving the unified NWKRTC Belagavi Division network (Belagavi CBT, Athani, Chikkodi,
 * Nippani, Sankeshwar, Raibag, and Londa bus stands).
 */
function nwkrtcApiPlugin(): Plugin {
  return {
    name: 'nwkrtc-division-api',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url) return next();

        // 1. GET /api/v1/stations
        if (req.url.startsWith('/api/v1/stations')) {
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(DIVISION_MASTER_STATIONS));
          return;
        }

        // 2. GET /api/v1/buses/search?source=...&destination=...
        if (req.url.startsWith('/api/v1/buses/search')) {
          const parsedUrl = new URL(req.url, 'http://localhost:5173');
          const source = parsedUrl.searchParams.get('source') || '';
          const destination = parsedUrl.searchParams.get('destination') || '';

          const results = queryDivisionBuses(source, destination);
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(results));
          return;
        }

        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), nwkrtcApiPlugin()],
});
