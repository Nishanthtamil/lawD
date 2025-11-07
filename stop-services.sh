#!/bin/bash

echo "🛑 Stopping all Legal AI services..."

# Stop development services
echo "Stopping development services..."
docker compose -f docker-compose.dev.yml down --remove-orphans || true

# Stop production services
echo "Stopping production services..."
docker compose down --remove-orphans || true

# Remove any orphaned containers
echo "Cleaning up containers..."
docker container prune -f

# Remove unused networks
echo "Cleaning up networks..."
docker network prune -f

echo "✅ All services stopped and cleaned up!"