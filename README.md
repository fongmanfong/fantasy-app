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
   - **Homepage URL**: `http://localhost:3000`
   - **Redirect URI**: `https://localhost`
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

### 3. Install dependencies

```bash
# Python
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn sqlalchemy yahoo-fantasy-api requests beautifulsoup4 \
            pandas numpy apscheduler anthropic python-dotenv httpx aiosqlite

# Node
cd frontend && npm install && cd ..
```

### 4. Start the app

```bash
./start.sh
```

This starts both the backend (port 8000) and frontend (port 3000) in the background. Logs are written to `/tmp/fantasy-backend.log` and `/tmp/fantasy-frontend.log`.

To stop everything:
```bash
lsof -ti :8000 :3000 | xargs kill -9
```

### 5. First-run setup

Open `http://localhost:3000`. You'll be guided through:

1. **Enter Yahoo credentials** — paste your Client ID and Client Secret
2. **Authorize with Yahoo** — Yahoo opens in a new tab, you approve, then copy the full redirect URL (looks like `https://localhost?code=...`) and paste it back into the app
3. **Add your league** — enter your Yahoo Fantasy league ID (found in the league URL, e.g. `fantasysports.yahoo.com/nba/28641`)

Your league data will sync automatically in the background.

### Subsequent launches

Just run `./start.sh` — all your credentials, league connections, and synced data are persisted in `data/fantasy.db` and will be available immediately.

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
