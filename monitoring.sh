#!/bin/bash

# Legal AI Assistant Monitoring Script

echo "📊 Legal AI Assistant - System Status"
echo "======================================"

# Check if services are running
echo ""
echo "🔍 Service Status:"
docker-compose ps

echo ""
echo "💾 Resource Usage:"
echo "Docker containers:"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

echo ""
echo "🗄️  Database Status:"
echo "PostgreSQL:"
docker-compose exec postgres pg_isready -U postgres || echo "❌ PostgreSQL not ready"

echo "Redis:"
docker-compose exec redis redis-cli ping || echo "❌ Redis not ready"

echo ""
echo "📈 Application Metrics:"
echo "Backend health:"
curl -s http://localhost/health || echo "❌ Backend not responding"

echo ""
echo "Nginx access logs (last 10 lines):"
docker-compose logs --tail=10 nginx | grep -E "(GET|POST|PUT|DELETE)" || echo "No recent requests"

echo ""
echo "🔄 Celery Status:"
echo "Worker status:"
docker-compose exec celery_worker celery -A backend inspect active || echo "❌ Celery worker not responding"

echo ""
echo "📊 Queue Status:"
docker-compose exec celery_worker celery -A backend inspect stats || echo "❌ Cannot get queue stats"

echo ""
echo "🚨 Recent Errors (last 20 lines):"
docker-compose logs --tail=20 | grep -i error || echo "No recent errors found"

echo ""
echo "💽 Disk Usage:"
df -h | grep -E "(Filesystem|/dev/)"

echo ""
echo "🔧 Quick Actions:"
echo "  View all logs: docker-compose logs -f"
echo "  Restart backend: docker-compose restart backend"
echo "  Restart worker: docker-compose restart celery_worker"
echo "  Scale workers: docker-compose up -d --scale celery_worker=3"
echo "  Stop all: docker-compose down"