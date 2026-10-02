# 🚀 Vercel Deployment Guide for Belagavi Yatri

A complete, production-ready guide to deploying the **Belagavi Yatri** real-time bus tracking system on [Vercel](https://vercel.com).

---

## 📋 Architecture Overview

This project consists of two core layers:

1. **Frontend (Vercel)**:
   - **Tech**: React 18, Vite, TypeScript, Tailwind CSS, Leaflet.js
   - **Hosting**: Vercel (Edge CDN, global distribution, automatic HTTPS, continuous deployment from GitHub)
   - **Routing**: Single Page Application (SPA) handled via `vercel.json`

2. **Backend Engine (Persistent Cloud)**:
   - **Tech**: Python 3.11, FastAPI, SQLAlchemy, GeoAlchemy2, PostGIS, Redis
   - **Features**: REST API, Redis Pub/Sub, live WebSockets (`/ws/v1/buses/{bus_id}` and `/api/v1/ws/division`)
   - **Hosting**: [Render](https://render.com), [Railway](https://railway.app), or [Fly.io](https://fly.io) *(WebSockets require a persistent server environment rather than 10-second serverless functions)*.

---

## ⚡ Method 1: Deploy via Vercel Web Dashboard (Recommended)

### Step 1: Connect Your GitHub Repository
1. Navigate to [vercel.com](https://vercel.com) and log in with your GitHub account.
2. On your Vercel Dashboard, click **Add New…** → **Project**.
3. Under **Import Git Repository**, locate:
   ```text
   Neminath-jain/Belgavi-yatri
   ```
4. Click **Import**.

---

### Step 2: Configure Build & Project Settings
Vercel will automatically detect the `vercel.json` file in your repository. Verify the following settings:

| Setting | Value |
| :--- | :--- |
| **Framework Preset** | `Vite` |
| **Root Directory** | `./` |
| **Build Command** | `npm run build` |
| **Output Directory** | `dist` |
| **Install Command** | `npm install` |

---

### Step 3: Add Environment Variables
Under the **Environment Variables** section on Vercel, add:

| Key | Example Value | Description |
| :--- | :--- | :--- |
| `VITE_API_BASE_URL` | `https://your-backend-api.onrender.com` | Base URL of your live FastAPI backend |
| `VITE_WS_BASE_URL` | `wss://your-backend-api.onrender.com` | (Optional) WebSocket URL if different |

> **Note:** If you haven't deployed the backend yet, you can leave `VITE_API_BASE_URL` empty or provide `http://localhost:8000` for initial testing. The app will gracefully fall back to local offline mock schedules.

---

### Step 4: Click Deploy
1. Click **Deploy**.
2. Vercel will clone your repository, run `npm install`, compile TypeScript via `tsc -b`, and bundle the app with Vite.
3. Once completed (usually 45–60 seconds), Vercel will assign a public production URL (e.g. `https://belgavi-yatri.vercel.app`).

---

## 💻 Method 2: Deploy via Vercel CLI

If you prefer deploying directly from your terminal:

### 1. Install Vercel CLI
```powershell
npm install -g vercel
```

### 2. Login to Vercel
```powershell
vercel login
```

### 3. Deploy to Preview
From the project root (`D:\Projects-For-Hustle\CBT_PROJECT`):
```powershell
vercel
```
Follow the interactive prompts:
- **Set up and deploy?** → `Y`
- **Which scope?** → Select your personal account
- **Link to existing project?** → `N`
- **Project name?** → `belagavi-yatri`
- **Directory?** → `./`
- **Want to modify settings?** → `N`

### 4. Deploy to Production
```powershell
vercel --prod
```

---

## 🛠️ Configuration Files Included in This Project

### `vercel.json` (SPA Client-Side Routing)
Located at the root of the project to ensure deep links and page refreshes do not result in 404 errors:

```json
{
  "framework": "vite",
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ]
}
```

---

## 🌐 Deploying the FastAPI Backend (Render / Railway)

Because real-time bus tracking utilizes continuous **WebSocket streams** and **PostGIS geofencing**, the backend requires a persistent container service:

### Option A: Render (Free & Fast)
1. Go to [render.com](https://render.com) and create a **New Web Service**.
2. Connect `https://github.com/Neminath-jain/Belgavi-yatri`.
3. Configure settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r backend/requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Add Environment Variables:
   - `DATABASE_URL`: Your PostgreSQL / Supabase connection string.
   - `REDIS_URL`: Your Upstash / Redis connection string.
   - `CORS_ORIGINS`: `https://belgavi-yatri.vercel.app` (your Vercel domain).
5. Copy your Render service URL (e.g. `https://belgavi-yatri-api.onrender.com`) and paste it into Vercel's `VITE_API_BASE_URL`.

---

## 🔍 Verification & Testing After Deployment

Once deployed on Vercel:

1. **Verify UI & Map Loading**:
   - Open your Vercel URL.
   - Confirm that the Leaflet map and station markers load correctly.
2. **Verify Search**:
   - Select Origin: `BELAGAVI CBT` and Destination: `CHIKKODI`.
   - Click **Search Buses** and verify active vehicle cards appear.
3. **Verify HTTPS / SSL**:
   - Ensure Vercel provides a valid SSL certificate (`https://`).
   - If calling your backend, ensure the backend URL also starts with `https://` (to prevent browser Mixed-Content blocking).
4. **Continuous Deployment**:
   - Any time you run `git push origin main`, Vercel will automatically build and publish the latest version!

---

## 🆘 Troubleshooting Common Issues

| Problem | Cause | Solution |
| :--- | :--- | :--- |
| **404 Not Found on Page Refresh** | SPA router cannot find static file | Verify `vercel.json` has the rewrite rule pointing to `/index.html`. |
| **Mixed Content Warning** | Frontend is HTTPS, but API is HTTP | Ensure `VITE_API_BASE_URL` uses `https://` and backend has SSL enabled. |
| **CORS Error in Console** | Backend blocked the Vercel domain | Add your `*.vercel.app` domain to `CORS_ORIGINS` in your backend configuration. |
| **Map Tiles Blank** | Network blocking CartoDB/OSM tiles | Ensure browser permits requests to `basemaps.cartocdn.com` and `tile.openstreetmap.org`. |
