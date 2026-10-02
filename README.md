# 🚌 KSRTC / NWKRTC Belagavi Division Live Tracker

A production-grade, real-time bus tracking and passenger information system for the **NWKRTC Belagavi Division**. Backed by real imported schedule rosters, geocoded station geometries, high-performance **FastAPI**, **PostgreSQL/PostGIS**, and **Redis** caching & pub/sub streaming.

---

## 🏗️ System Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                 React + TypeScript + Vite                   │
│            (Tailwind CSS, Leaflet/Mapbox Radar)             │
│                  http://localhost:5173                      │
└──────────────────────────────┬──────────────────────────────┘
                               │ REST / WebSocket
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend Server                    │
│             (SQLAlchemy, GeoAlchemy2, Pydantic)             │
│                  http://localhost:8000                      │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌─────────────────────────────┐┌──────────────────────────────┐
│    PostgreSQL / PostGIS     ││         Redis Cache          │
│   - Stations & Geofences    ││   - Geospatial GEOADD/SEARCH │
│   - search_buses Engine     ││   - 1h Station Directory     │
│   - upsert_bus_telemetry    ││   - 20s Search Query Cache   │
│   - DPDP Consent & Audit    ││   - Rate Limiter & Pub/Sub   │
└─────────────────────────────┘└──────────────────────────────┘
```

---

## ⚡ Quick Start: Running the Full Project

### Prerequisites
- **Node.js**: `v18.0.0` or higher
- **Python**: `3.11` or higher
- **Package Managers**: `npm` and `pip`
- *(Optional)* **Redis** and **PostgreSQL/PostGIS** (the backend includes automatic in-memory fallbacks with `fakeredis` and SQLite simulation for offline dev/testing).

---

## 🐍 1. Backend Setup (FastAPI + Redis + SQLAlchemy)

### Step 1: Navigate to Project Root
Open your terminal in the project root directory:
```bash
cd CBT_PROJECT
```

### Step 2: Create and Activate a Python Virtual Environment *(Recommended)*
- **Windows (PowerShell)**:
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
- **macOS / Linux**:
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### Step 3: Install Backend Dependencies
```bash
pip install -r backend/requirements.txt
```

### Step 4: Environment Variables *(Optional)*
The backend runs out-of-the-box with built-in fallbacks. To connect to dedicated local or cloud services (e.g. Supabase, Docker Redis), create a `.env` file in the project root:

```env
# PostgreSQL / PostGIS Connection String (defaults to localhost:5432)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres

# Redis Connection (defaults to localhost:6379, falls back to in-memory fakeredis)
REDIS_URL=redis://localhost:6379/0

# Optional Geofencing Tuning
DEFAULT_GEOFENCE_RADIUS_METERS=60.0
GEOFENCE_DEPARTURE_SPEED_KMH=5.0
```

### Step 5: Start the Backend Server

You can start the backend using either method:

#### Method A: Using the Launcher Script
```bash
python run_backend.py
```

#### Method B: Using the Uvicorn CLI Directly
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Once running:
- **API Base URL**: [`http://localhost:8000`](http://localhost:8000)
- **Interactive Swagger Documentation**: [`http://localhost:8000/docs`](http://localhost:8000/docs)
- **ReDoc Alternate Documentation**: [`http://localhost:8000/redoc`](http://localhost:8000/redoc)

### Step 6: Run Backend Automated Tests
Execute the comprehensive test suite (schemas, geofencing, endpoints, rate limiting, and caching):
```bash
python -m unittest discover -s backend/tests -p "test_*.py" -v
```

---

## ⚛️ 2. Frontend Setup (React + TypeScript + Vite)

### Step 1: Install Frontend Dependencies
In a new terminal window at the project root:
```bash
npm install
```

### Step 2: Configure Environment Variables *(Optional)*
Create a `.env.local` file in the project root to direct frontend requests to your FastAPI backend:
```env
VITE_API_BASE_URL=http://localhost:8000
```
*(If left empty, requests will route to relative `/api/v1` routes or Vite development proxy).*

### Step 3: Start the Vite Development Server
```bash
npm run dev
```

The application will launch locally at:
👉 **[http://localhost:5173](http://localhost:5173)**

### Step 4: Build for Production
To type-check and generate production assets:
```bash
npm run build
```
To preview the generated production build locally:
```bash
npm run preview
```

---

## 📡 3. API Endpoints Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | System health check (PostgreSQL & Redis connection status) |
| `GET` | `/api/v1/stations` | List all resolved stations (cached in Redis with 1h TTL; excludes quarantined/placeholder stops) |
| `GET` | `/api/v1/buses/search?source=...&destination=...` | Live route search with dynamic fallback, Redis geospatial position merging, and 404 validation |
| `POST`| `/api/v1/telemetry` | Rate-limited GPS intake (1 ping / 3s), vehicle auto-registration, PostGIS platform geofencing, and Pub/Sub |
| `GET` | `/api/v1/buses/near?latitude=...&longitude=...&radius_km=...` | Proximity radar query powered by Redis `GEOSEARCH` |
| `WS`  | `/ws/v1/buses/{bus_id}` | Real-time WebSocket streaming of live vehicle telemetry frames |

---

## 🧪 4. Sample Backend Commands

### Health Check
```bash
curl http://localhost:8000/health
```

### Fetch Geocoded Stations
```bash
curl http://localhost:8000/api/v1/stations
```

### Search Route (Belagavi CBT to Chikkodi)
```bash
curl "http://localhost:8000/api/v1/buses/search?source=BELAGAVI%20CBT&destination=CHIKKODI"
```

### Ingest GPS Telemetry Ping
```bash
curl -X POST http://localhost:8000/api/v1/telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "bus_number": "KA-22-F-1892",
    "latitude": 15.8573,
    "longitude": 74.5065,
    "speed": 42.5
  }'
```

---

## 🛠️ Data Engineering & Pipeline Utilities

- **Station Geocoding Pipeline**:
  Identifies placeholder stops and geocodes coordinates via CSV manual overrides and OpenStreetMap Nominatim:
  ```bash
  python scripts/geocode_stations.py --db-url "postgresql://postgres:postgres@localhost:5432/postgres"
  ```
- **Schedule PDF Parser**:
  Extracts master division rosters and generates operational datasets:
  ```bash
  python scripts/parse_all_pdfs.py
  ```

---

## 📁 Repository Structure

```text
CBT_PROJECT/
├── backend/
│   ├── config.py             # Central configuration, Redis keys, TTLs, and geofence thresholds
│   ├── database.py           # SQLAlchemy engine, session factory, and get_db() dependency
│   ├── geofence.py           # PostGIS ST_DWithin and haversine geofencing service
│   ├── main.py               # FastAPI application, CORS middleware, and route handlers
│   ├── models.py             # SQLAlchemy ORM models with GeoAlchemy2 Geometry types
│   ├── redis_client.py       # Async & sync connection pool manager with in-memory fallback
│   ├── redis_service.py      # Hot-path telemetry ingestion, sliding-window rate limit, and caching
│   ├── requirements.txt      # Python dependencies
│   ├── schemas.py            # Pydantic v2 schemas (BusSearchResponse, TelemetryInput, etc.)
│   └── tests/                # Automated test suite (schemas, geofence, endpoints)
├── scripts/
│   ├── geocode_stations.py   # OSM Nominatim geocoder with rate limiting and quarantine table
│   └── parse_all_pdfs.py     # Multi-depot operational timetable extraction script
├── src/
│   ├── components/           # React UI components (BusCard, MapContainer, SearchBar, Header)
│   ├── services/             # API client services (api.ts)
│   ├── types/                # TypeScript data contracts (database.ts)
│   └── App.tsx               # Main live tracking dashboard
├── supabase/
│   └── migrations/           # PostGIS database migrations & stored functions
├── run_backend.py            # Convenient one-click FastAPI server launcher
└── package.json              # Frontend dependencies and scripts
```

---

## 🔒 DPDP Act 2023 & DPDP Rules 2025 Privacy Engineering

The platform implements a privacy engineering architecture compliant with the **Digital Personal Data Protection Act, 2023 (DPDP Act)** and **DPDP Rules, 2025**:

### 1. Scope Boundary
- **Exempt Public Transit Telemetry**: Live bus GPS coordinates, speeds, delays, platform departure statuses, station directories, and timetables are public operational transit records. They contain zero personal data of identifiable natural persons.
- **Rider-Facing Optional Features**: Strict data protection applies exclusively to features collecting personal data:
  - **SMS / WhatsApp Alerts**: Mobile phone numbers collected solely to notify riders when a bus departs the platform or nears their stop.
  - **Email Transit Bulletins**: Email addresses collected solely for corridor advisories and timetable updates.
  - **Saved Frequent Routes**: Frequent station pairs associated with a pseudonymous rider account identifier.

### 2. Notice Registry & Transparency (Section 5)
- Standardized plain-language notices (`CURRENT_NOTICE_VERSION = "DPDP-2025-v1.0"`) specifying:
  - Exact personal data collected (`personal_data_collected`).
  - Granular, concrete purpose of processing (`specific_purpose`).
  - Clear instructions on how consent can be withdrawn at any time (`withdrawal_info`).
  - Official Grievance Officer / Data Protection Officer email (`grievance.privacy@nwkrtc-belagavi.in`).

### 3. Unbundled Affirmative Consent & Audit Trail (Section 6)
- **Unbundled Consents**: Consenting to SMS departure alerts does not bundle or activate saved routes or email bulletins.
- **Audit Logging**: Every opt-in is recorded in the PostgreSQL `consent_records` ledger with timestamps (`consent_given_at`, `consent_withdrawn_at`).

### 4. Strict Consent Gate & Field-Level PII Encryption (Section 6 & 8)
- **Zero-Storage Without Consent**: Attempting to register contact details (`POST /api/v1/users/register-alert`) or save routes (`POST /api/v1/users/saved-routes`) without prior affirmative consent is blocked with **HTTP 403 Forbidden**. No phone number or email is written to the database.
- **Encryption at Rest**: Stored personal identifiers are protected with field-level encryption at rest in PostgreSQL `BYTEA` columns (`phone_number_encrypted`, `email_encrypted`).

### 5. Immediate Consent Withdrawal & Cessation Cascade (Section 8)
- Calling `DELETE /api/v1/consent/{purpose}?user_id=...` immediately:
  - Sets the `consent_withdrawn_at` audit timestamp.
  - Disables alert subscriptions and permanently purges stored contact numbers / emails.
  - Halts all automated notification dispatching immediately.

### 6. Compliance Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/consent/notices` | Fetches plain-language notices for all optional personal data features |
| `GET` | `/api/v1/consent/status` | Queries active vs. withdrawn consent states for a Data Principal |
| `POST` | `/api/v1/consent` | Records unbundled affirmative consent for a specific purpose |
| `DELETE` | `/api/v1/consent/{purpose}` | Executes immediate consent withdrawal, cessation, and PII purge |
| `POST` | `/api/v1/users/register-alert` | Subscribes to departure alert (Strict Consent Gate: 403 if unconsented) |
| `POST` | `/api/v1/users/saved-routes` | Saves route preference (Strict Consent Gate: 403 if unconsented) |

### 7. Running Privacy Compliance Tests
Run the standalone DPDP compliance test suite:
```bash
python -m unittest backend.tests.test_dpdp -v
```
Or run the full 28-test backend verification suite:
```bash
python -m unittest discover -s backend/tests -p "test_*.py" -v
```
