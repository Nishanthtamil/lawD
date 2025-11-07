#!/bin/bash

# Legal AI Assistant Deployment Script

set -e

echo "🚀 Starting Legal AI Assistant deployment..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env file with your configuration before continuing."
    echo "   Required: DJANGO_SECRET_KEY, GROQ_API_KEY, database passwords"
    read -p "Press Enter after editing .env file..."
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p nginx/ssl
mkdir -p backend/media/user_documents
mkdir -p backend/staticfiles

# Clean up any existing containers
echo "🧹 Cleaning up existing containers..."
docker compose down --remove-orphans || true

# Build services one by one to handle errors better
echo "🔨 Building backend services..."
docker compose build postgres redis backend celery_worker celery_beat

echo "🔨 Building frontend..."
docker compose build frontend

echo "🔨 Building nginx..."
docker compose build nginx

echo "🗄️  Starting database services..."
docker compose up -d postgres redis

echo "⏳ Waiting for database to be ready..."
sleep 15

# Check if database is ready
echo "🔍 Checking database connection..."
docker compose exec postgres pg_isready -U postgres || {
    echo "❌ Database not ready. Checking logs..."
    docker compose logs postgres
    exit 1
}

echo "🔄 Running database migrations..."
docker compose run --rm backend python manage.py migrate

echo "👤 Creating superuser (optional)..."
read -p "Do you want to create a Django superuser? (y/n): " create_superuser
if [ "$create_superuser" = "y" ]; then
    docker compose run --rm backend python manage.py createsuperuser
fi

echo "📦 Collecting static files..."
docker compose run --rm backend python manage.py collectstatic --noinput

echo "🚀 Starting all services..."
docker compose up -d

echo "⏳ Waiting for services to start..."
sleep 10

echo "✅ Deployment complete!"
echo ""
echo "🌐 Application URLs:"
echo "   Frontend: http://localhost"
echo "   Backend API: http://localhost/api"
echo "   Django Admin: http://localhost/admin"
echo ""
echo "📊 Service Status:"
docker compose ps

echo ""
echo "🔍 Health Check:"
echo "Testing backend health..."
curl -f http://localhost/health || echo "⚠️  Backend health check failed"

echo ""
echo "📝 To view logs:"
echo "   All services: docker compose logs -f"
echo "   Backend only: docker compose logs -f backend"
echo "   Celery worker: docker compose logs -f celery_worker"
echo "   Frontend: docker compose logs -f frontend"
echo ""
echo "🛑 To stop services:"
echo "   docker compose down"