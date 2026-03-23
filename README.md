# Fantasy IQ — NBA Fantasy Intelligence Platform

AI-powered NBA Fantasy Basketball optimization. Connects to Yahoo Fantasy, analyzes your league, and uses Claude to recommend optimal moves — all contextualized to your league's specific scoring format.

## Features

- **Multi-league support** — add any Yahoo Fantasy league; all intelligence adapts to that league's scoring type and categories
- **AI recommendations** — Claude analyzes your roster, matchup, free agents, and player news to suggest the best moves (or tell you to stand pat)
- **Natural language chat** — ask anything about your league in plain English
- **Live matchup analysis** — category-by-category breakdown, winning/losing projection
- **Waiver wire intelligence** — free agents ranked by value for your specific league
- **Automatic data sync** — configurable schedule keeps everything fresh

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (install via `brew install node`)
- An [Anthropic API key](https://console.anthropic.com/)
- A Yahoo Developer account (free)

### 1. Create a Yahoo Developer App

1. Go to [developer.yahoo.com/apps](https://developer.yahoo.com/apps/) and sign in
2. Click **Create an App**
3. Fill in:
   - **Application Name**: Fantasy IQ (or anything)
   - **Application Type**: Installed Application
   - **Redirect URI(s)**: `http://localhost:8000/api/auth/yahoo/callback`
   - **API Permissions**: Fantasy Sports → Read
4. Save. Copy your **Client ID** and **Client Secret**

### 2. Clone and configure

```bash
cd fantasy-app
cp .env.example .env
```

Edit `.env`:
```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

### 3. Start the backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn sqlalchemy yahoo-fantasy-api requests beautifulsoup4 \
            pandas numpy apscheduler anthropic python-dotenv httpx aiosqlite

cd fantasy-app   # repo root
python -m uvicorn backend.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The app will be available at `http://localhost:3000`.

### 5. First-run setup

Open `http://localhost:3000`. You'll be guided through:

1. **Enter Yahoo credentials** — paste your Client ID and Client Secret
2. **Authorize with Yahoo** — browser redirect to Yahoo and back
3. **Add your league** — enter your Yahoo Fantasy league ID (found in the league URL)

Your league data will sync automatically in the background.

---

## Usage

| Page | What it does |
|------|-------------|
| **My Team** | Full roster with stats, injury status, and value scores |
| **Matchup** | This week's matchup — category breakdown, projected outcome |
| **League** | Standings for all teams |
| **Free Agents** | Available players ranked by value for your league's scoring |
| **Recommendations** | AI-generated analysis: add/drop, trades, start/sit |
| **Chat** | Ask anything about your league in natural language |
| **Settings** | Manage leagues, sync schedule, and credentials |

### Syncing data

- Click **Sync Now** in the sidebar at any time
- Or configure an automatic schedule in Settings (default: every 6 hours)
- Player news refreshes every 3 hours automatically

---

## Project Structure

```
fantasy-app/
├── backend/
│   ├── main.py                 # FastAPI app + lifespan
│   ├── scheduler.py            # APScheduler background sync
│   ├── database/
│   │   ├── models.py           # SQLAlchemy models
│   │   └── connection.py       # DB session management
│   ├── services/
│   │   ├── yahoo_service.py    # Yahoo OAuth + data extraction
│   │   ├── news_service.py     # Player news scraping
│   │   ├── stats_engine.py     # Statistical analysis (pandas)
│   │   └── agent_service.py    # Claude AI agent with tools
│   └── routers/
│       ├── auth.py             # Yahoo OAuth endpoints
│       ├── leagues.py          # League management + sync
│       ├── teams.py            # Teams, rosters, matchups
│       └── agent.py            # Chat + recommendations
├── frontend/
│   ├── app/                    # Next.js app router pages
│   ├── components/             # React components
│   ├── hooks/                  # useLeague context
│   └── lib/                    # API client + utilities
└── data/
    └── fantasy.db              # SQLite database (auto-created)
```

---

## Adding More Leagues

You can add multiple Yahoo Fantasy leagues (any sport, any format). Each league's intelligence is fully independent and contextualized to that league's settings. Go to Settings → Add League and enter the league ID.

---

## Notes

- All data is stored locally in `data/fantasy.db`
- Yahoo credentials and tokens are stored in the database, not in `.env`
- The app never writes back to Yahoo — it is read-only
