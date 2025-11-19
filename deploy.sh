#!/bin/bash

# Legal AI Assistant - Unified Deployment Script
# Supports development, production, and enhanced modes

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
MODE="production"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"
RESET_DATA=false
CREATE_SUPERUSER=false

# Function to display usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -m, --mode MODE          Deployment mode: dev, prod, enhanced (default: prod)"
    echo "  -r, --reset-data         Reset all data (remove volumes)"
    echo "  -s, --create-superuser   Create Django superuser"
    echo "  -h, --help              Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                       # Production deployment"
    echo "  $0 -m dev               # Development deployment"
    echo "  $0 -m enhanced -r       # Enhanced deployment with data reset"
    echo "  $0 -m prod -s           # Production with superuser creation"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -m|--mode)
            MODE="$2"
            shift 2
            ;;
        -r|--reset-data)
            RESET_DATA=true
            shift
            ;;
        -s|--create-superuser)
            CREATE_SUPERUSER=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Set configuration based on mode
case $MODE in
    "dev"|"development")
        COMPOSE_FILE="docker-compose.dev.yml"
        ENV_FILE=".env.dev"
        echo -e "${BLUE}🚀 Starting Legal AI Assistant (Development Mode)...${NC}"
        ;;
    "prod"|"production")
        COMPOSE_FILE="docker-compose.yml"
        ENV_FILE=".env"
        echo -e "${BLUE}🚀 Starting Legal AI Assistant (Production Mode)...${NC}"
        ;;
    "enhanced")
        COMPOSE_FILE="docker-compose.yml"
        ENV_FILE=".env"
        echo -e "${BLUE}🚀 Starting Legal AI Assistant (Enhanced Mode with AI Services)...${NC}"
        ;;
    *)
        echo -e "${RED}❌ Invalid mode: $MODE${NC}"
        show_usage
        exit 1
        ;;
esac

# Check dependencies
echo -e "${BLUE}🔍 Checking dependencies...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed. Please install Docker first.${NC}"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose is not installed. Please install Docker Compose first.${NC}"
    exit 1
fi

# Enhanced mode requires jq for JSON parsing
if [ "$MODE" = "enhanced" ] && ! command -v jq &> /dev/null; then
    echo -e "${YELLOW}⚠️ jq is not installed. Installing jq for JSON parsing...${NC}"
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y jq
    elif command -v yum &> /dev/null; then
        sudo yum install -y jq
    elif command -v brew &> /dev/null; then
        brew install jq
    else
        echo -e "${RED}❌ Cannot install jq automatically. Please install it manually.${NC}"
        exit 1
    fi
fi

# Check environment file
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}⚠️ $ENV_FILE file not found. Creating from .env.example...${NC}"
    cp .env.example "$ENV_FILE"
    echo -e "${YELLOW}📝 Please edit $ENV_FILE with your configuration before continuing.${NC}"
    echo "   Required variables:"
    echo "   - DJANGO_SECRET_KEY (generate a strong secret key)"
    echo "   - GROQ_API_KEY (your Groq API key)"
    if [ "$MODE" = "enhanced" ]; then
        echo "   - NEO4J_PASSWORD (secure password for Neo4j)"
        echo "   - DB_PASSWORD (secure password for PostgreSQL)"
    fi
    echo ""
    read -p "Press Enter after editing $ENV_FILE file..."
fi

# Validate required environment variables for enhanced mode
if [ "$MODE" = "enhanced" ]; then
    echo -e "${BLUE}🔍 Validating environment configuration...${NC}"
    source "$ENV_FILE"

    required_vars=("DJANGO_SECRET_KEY" "GROQ_API_KEY" "NEO4J_PASSWORD" "DB_PASSWORD")
    missing_vars=()

    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            missing_vars+=("$var")
        fi
    done

    if [ ${#missing_vars[@]} -ne 0 ]; then
        echo -e "${RED}❌ Missing required environment variables:${NC}"
        printf '%s\n' "${missing_vars[@]}"
        echo "Please update your $ENV_FILE file and try again."
        exit 1
    fi

    echo -e "${GREEN}✅ Environment configuration validated${NC}"
fi

# Create necessary directories
echo -e "${BLUE}📁 Creating directories...${NC}"
mkdir -p nginx/ssl
mkdir -p backend/media/user_documents
mkdir -p backend/staticfiles
mkdir -p backend/logs

# Clean up existing containers
echo -e "${BLUE}🧹 Cleaning up existing containers...${NC}"
docker compose -f "$COMPOSE_FILE" down --remove-orphans || true

# Reset data if requested
if [ "$RESET_DATA" = true ]; then
    echo -e "${YELLOW}⚠️ Removing existing volumes...${NC}"
    docker compose -f "$COMPOSE_FILE" down -v
    docker volume prune -f
fi

# Build services
echo -e "${BLUE}🔨 Building services...${NC}"

if [ "$MODE" = "enhanced" ]; then
    # Enhanced mode - build all services including AI infrastructure
    services_to_build=(
        "postgres:PostgreSQL Database"
        "redis:Redis Cache"
        "neo4j:Neo4j Graph Database"
        "etcd:Milvus etcd"
        "minio:Milvus MinIO"
        "milvus:Milvus Vector Database"
        "backend:Django Backend"
        "celery_worker:Celery Worker"
        "celery_beat:Celery Beat"
        "celery_monitor:Queue Monitor"
        "frontend:React Frontend"
        "nginx:Nginx Proxy"
    )

    for service_info in "${services_to_build[@]}"; do
        IFS=':' read -r service description <<< "$service_info"
        echo -e "${BLUE}🔨 Building $description...${NC}"
        if ! docker compose -f "$COMPOSE_FILE" build "$service"; then
            echo -e "${RED}❌ Failed to build $service${NC}"
            exit 1
        fi
    done
else
    # Standard mode - build core services
    docker compose -f "$COMPOSE_FILE" build
fi

echo -e "${GREEN}✅ All services built successfully${NC}"

# Start services based on mode
if [ "$MODE" = "enhanced" ]; then
    # Enhanced mode startup sequence
    echo -e "${BLUE}🗄️ Starting infrastructure services...${NC}"
    docker compose -f "$COMPOSE_FILE" up -d postgres redis

    echo -e "${BLUE}⏳ Waiting for PostgreSQL to be ready...${NC}"
    for i in {1..30}; do
        if docker compose -f "$COMPOSE_FILE" exec postgres pg_isready -U postgres &>/dev/null; then
            echo -e "${GREEN}✅ PostgreSQL is ready${NC}"
            break
        fi
        echo "  Attempt $i/30..."
        sleep 2
    done

    # Start Neo4j
    echo -e "${BLUE}🔗 Starting Neo4j...${NC}"
    docker compose -f "$COMPOSE_FILE" up -d neo4j

    echo -e "${BLUE}⏳ Waiting for Neo4j to be ready...${NC}"
    for i in {1..60}; do
        if curl -f http://localhost:7474/db/system/tx/commit &>/dev/null; then
            echo -e "${GREEN}✅ Neo4j is ready${NC}"
            break
        fi
        echo "  Attempt $i/60..."
        sleep 3
    done

    # Start Milvus dependencies
    echo -e "${BLUE}📊 Starting Milvus dependencies...${NC}"
    docker compose -f "$COMPOSE_FILE" up -d etcd minio

    echo -e "${BLUE}⏳ Waiting for Milvus dependencies...${NC}"
    sleep 10

    # Start Milvus
    echo -e "${BLUE}🔍 Starting Milvus...${NC}"
    docker compose -f "$COMPOSE_FILE" up -d milvus

    echo -e "${BLUE}⏳ Waiting for Milvus to be ready...${NC}"
    for i in {1..60}; do
        if curl -f http://localhost:9091/healthz &>/dev/null; then
            echo -e "${GREEN}✅ Milvus is ready${NC}"
            break
        fi
        echo "  Attempt $i/60..."
        sleep 3
    done
else
    # Standard mode startup
    echo -e "${BLUE}🗄️ Starting database services...${NC}"
    docker compose -f "$COMPOSE_FILE" up -d postgres redis

    echo -e "${BLUE}⏳ Waiting for database to be ready...${NC}"
    sleep 15

    # Check if database is ready
    echo -e "${BLUE}🔍 Checking database connection...${NC}"
    docker compose -f "$COMPOSE_FILE" exec postgres pg_isready -U postgres || {
        echo -e "${RED}❌ Database not ready. Checking logs...${NC}"
        docker compose -f "$COMPOSE_FILE" logs postgres
        exit 1
    }
fi

# Run database migrations
echo -e "${BLUE}🔄 Running database migrations...${NC}"
if ! docker compose -f "$COMPOSE_FILE" run --rm backend python manage.py migrate; then
    echo -e "${RED}❌ Database migration failed${NC}"
    exit 1
fi

# Initialize Milvus collections (enhanced mode only)
if [ "$MODE" = "enhanced" ]; then
    echo -e "${BLUE}🔍 Initializing Milvus collections...${NC}"
    if ! docker compose -f "$COMPOSE_FILE" run --rm backend python manage.py init_milvus; then
        echo -e "${YELLOW}⚠️ Milvus initialization failed, but continuing...${NC}"
    fi
fi

# Create superuser
if [ "$CREATE_SUPERUSER" = true ]; then
    echo -e "${BLUE}👤 Creating superuser...${NC}"
    docker compose -f "$COMPOSE_FILE" run --rm backend python manage.py createsuperuser
fi

# Collect static files
echo -e "${BLUE}📦 Collecting static files...${NC}"
if ! docker compose -f "$COMPOSE_FILE" run --rm backend python manage.py collectstatic --noinput; then
    echo -e "${RED}❌ Static file collection failed${NC}"
    exit 1
fi

# Start application services
echo -e "${BLUE}🚀 Starting application services...${NC}"
if [ "$MODE" = "enhanced" ]; then
    docker compose -f "$COMPOSE_FILE" up -d backend celery_worker celery_beat celery_monitor
else
    docker compose -f "$COMPOSE_FILE" up -d backend celery_worker celery_beat
fi

# Wait for backend
echo -e "${BLUE}⏳ Waiting for backend to be ready...${NC}"
for i in {1..30}; do
    backend_url="http://localhost:8000"
    if [ "$MODE" != "dev" ]; then
        backend_url="http://localhost"
    fi
    
    if curl -f "$backend_url/api/health/" &>/dev/null; then
        echo -e "${GREEN}✅ Backend is ready${NC}"
        break
    fi
    echo "  Attempt $i/30..."
    sleep 2
done

# Start frontend and nginx
echo -e "${BLUE}🌐 Starting frontend and proxy...${NC}"
docker compose -f "$COMPOSE_FILE" up -d frontend nginx

echo -e "${BLUE}⏳ Waiting for services to start...${NC}"
sleep 10

# Display deployment summary
echo ""
echo -e "${GREEN}🎉 Deployment complete!${NC}"
echo ""
echo -e "${BLUE}🌐 Application URLs:${NC}"

if [ "$MODE" = "dev" ]; then
    echo "   Frontend:           http://localhost:3000"
    echo "   Backend API:        http://localhost:8000/api"
    echo "   Django Admin:       http://localhost:8000/admin"
else
    echo "   Frontend:           http://localhost"
    echo "   Backend API:        http://localhost/api"
    echo "   Django Admin:       http://localhost/admin"
fi

if [ "$MODE" = "enhanced" ]; then
    echo "   Neo4j Browser:      http://localhost:7474"
    echo "   Milvus Admin:       http://localhost:9001 (MinIO Console)"
    echo ""
    echo -e "${BLUE}📊 Database Access:${NC}"
    echo "   PostgreSQL:         localhost:5432"
    echo "   Redis:              localhost:6379"
    echo "   Neo4j:              localhost:7687 (bolt)"
    echo "   Milvus:             localhost:19530"
fi

echo ""
echo -e "${BLUE}📊 Service Status:${NC}"
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo -e "${BLUE}🔧 Management Commands:${NC}"
echo "   View logs:          docker compose -f $COMPOSE_FILE logs -f"
echo "   Monitor system:     ./monitoring.sh"
echo "   Scale workers:      docker compose -f $COMPOSE_FILE up -d --scale celery_worker=3"
echo "   Restart service:    docker compose -f $COMPOSE_FILE restart [service_name]"
echo "   Stop all:           docker compose -f $COMPOSE_FILE down"

if [ "$MODE" = "enhanced" ]; then
    echo ""
    echo -e "${BLUE}💡 Next Steps:${NC}"
    echo "1. Upload some public documents via Django admin"
    echo "2. Test the segregated hybrid query system"
    echo "3. Monitor processing queues and performance"
    echo "4. Set up SSL certificates for production"
fi

echo ""
echo -e "${GREEN}🚀 System is ready for use!${NC}"