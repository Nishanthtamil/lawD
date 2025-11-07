#!/bin/bash

# Legal AI Assistant Development Deployment Script

set -e

echo "🚀 Starting Legal AI Assistant development deployment..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Check if .env.dev file exists
if [ ! -f .env.dev ]; then
    echo "⚠️  .env.dev file not found. Creating from .env.example..."
    cp .env.example .env.dev
    echo "📝 Please edit .env.dev file with your configuration before continuing."
    echo "   Required: DJANGO_SECRET_KEY, GROQ_API_KEY"
    read -p "Press Enter after editing .env.dev file..."
fi

# Environment file will be loaded by docker-compose

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p backend/media/user_documents
mkdir -p backend/staticfiles

# Clean up any existing containers
echo "🧹 Cleaning up existing containers..."
docker compose -f docker-compose.dev.yml down --remove-orphans || true

# Build services
echo "🔨 Building services..."
docker compose -f docker-compose.dev.yml build

echo "🗄️  Starting database services..."
docker compose -f docker-compose.dev.yml up -d postgres redis

echo "⏳ Waiting for database to be ready..."
sleep 10

echo "🔄 Running database migrations..."
docker compose -f docker-compose.dev.yml run --rm backend python manage.py migrate

echo "👤 Creating superuser (optional)..."
read -p "Do you want to create a Django superuser? (y/n): " create_superuser
if [ "$create_superuser" = "y" ]; then
    docker compose -f docker-compose.dev.yml run --rm backend python manage.py createsuperuser
fi

echo "🚀 Starting all services..."
docker compose -f docker-compose.dev.yml up -d

echo "⏳ Waiting for services to start..."
sleep 5

echo "✅ Development deployment complete!"
echo ""
echo "🌐 Application URLs:"
echo "   Frontend: http://localhost:3000"
echo "   Backend API: http://localhost:8000/api"
echo "   Django Admin: http://localhost:8000/admin"
echo ""
echo "📊 Service Status:"
docker compose -f docker-compose.dev.yml ps

echo ""
echo "📝 To view logs:"
echo "   All services: docker compose -f docker-compose.dev.yml logs -f"
echo "   Backend only: docker compose -f docker-compose.dev.yml logs -f backend"
echo "   Frontend: docker compose -f docker-compose.dev.yml logs -f frontend"
echo "   Celery worker: docker compose -f docker-compose.dev.yml logs -f celery_worker"
echo ""
echo "🛑 To stop services:"
echo "   docker compose -f docker-compose.dev.yml down"