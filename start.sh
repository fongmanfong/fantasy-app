#!/bin/zsh
# Fantasy IQ — start backend and frontend

cd "$(dirname "$0")"

# Check .env
if [ ! -f .env ]; then
  echo "Error: .env not found. Copy .env.example and add your ANTHROPIC_API_KEY."
  exit 1
fi

# Kill any previous instances
lsof -ti :8000 | xargs kill -9 2>/dev/null
lsof -ti :3000 | xargs kill -9 2>/dev/null
sleep 1

echo "Starting backend on http://localhost:8000 ..."
nohup .venv/bin/python -m uvicorn backend.main:app --reload --port 8000 > /tmp/fantasy-backend.log 2>&1 &
BACKEND_PID=$!

# Wait for backend to be ready
for i in {1..15}; do
  if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "Backend ready."
    break
  fi
  sleep 1
done

echo "Starting frontend on http://localhost:3000 ..."
cd frontend
nohup npm run dev > /tmp/fantasy-frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..

# Wait for frontend to be ready
for i in {1..20}; do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null | grep -q "200\|304"; then
    echo "Frontend ready."
    break
  fi
  sleep 1
done

echo ""
echo "Fantasy IQ is running."
echo "  App:      http://localhost:3000"
echo "  API:      http://localhost:8000"
echo "  Logs:     tail -f /tmp/fantasy-backend.log"
echo "            tail -f /tmp/fantasy-frontend.log"
echo ""
echo "To stop: kill $BACKEND_PID $FRONTEND_PID"
echo "   (or run: lsof -ti :8000 :3000 | xargs kill -9)"
