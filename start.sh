#!/bin/bash
set -e

echo "=========================================="
echo "  BetWise — Starting Docker Compose Stack"
echo "=========================================="
echo ""

# Build and start all services
docker-compose up -d --build

echo ""
echo "Waiting for services to be healthy..."

# Wait for backend
echo -n "  Backend: "
for i in $(seq 1 30); do
  if curl -sf http://localhost:2323/api/health > /dev/null 2>&1; then
    echo "ready"
    break
  fi
  echo -n "."
  sleep 2
done

# Wait for frontend
echo -n "  Frontend: "
for i in $(seq 1 30); do
  if curl -sf http://localhost:3000 > /dev/null 2>&1; then
    echo "ready"
    break
  fi
  echo -n "."
  sleep 2
done

echo ""
echo "=========================================="
echo "  BetWise is running!"
echo ""
echo "  Dashboard: http://localhost:3000/admin"
echo "  Chat:      http://localhost:3000/chat"
echo "  API:       http://localhost:2323/api/health"
echo "=========================================="
