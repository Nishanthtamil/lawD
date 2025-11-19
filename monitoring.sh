#!/bin/bash

# Legal AI Assistant - Unified Monitoring Script
# Supports basic and enhanced monitoring modes

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
MODE="basic"
COMPOSE_FILE="docker-compose.yml"

# Function to display usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -m, --mode MODE     Monitoring mode: basic, enhanced (default: basic)"
    echo "  -f, --file FILE     Docker compose file (default: docker-compose.yml)"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                 # Basic monitoring"
    echo "  $0 -m enhanced     # Enhanced monitoring with AI services"
    echo "  $0 -f docker-compose.dev.yml  # Monitor development environment"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -m|--mode)
            MODE="$2"
            shift 2
            ;;
        -f|--file)
            COMPOSE_FILE="$2"
            shift 2
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

# Auto-detect enhanced mode if AI services are running
if [ "$MODE" = "basic" ]; then
    if docker ps --format "{{.Names}}" | grep -q "neo4j\|milvus"; then
        MODE="enhanced"
        echo -e "${BLUE}🔍 Detected AI services, switching to enhanced monitoring mode${NC}"
    fi
fi

echo -e "${BLUE}📊 Legal AI Assistant - System Status ($MODE mode)${NC}"
echo "=============================================="

# Function to check service health
check_service_health() {
    local service_name=$1
    local health_check=$2
    
    if eval "$health_check" &>/dev/null; then
        echo -e "${GREEN}✅ $service_name: Healthy${NC}"
        return 0
    else
        echo -e "${RED}❌ $service_name: Unhealthy${NC}"
        return 1
    fi
}

# Function to get container status
get_container_status() {
    local container_name=$1
    local status=$(docker inspect --format='{{.State.Status}}' "$container_name" 2>/dev/null || echo "not_found")
    
    case $status in
        "running")
            echo -e "${GREEN}🟢 Running${NC}"
            ;;
        "exited")
            echo -e "${RED}🔴 Exited${NC}"
            ;;
        "restarting")
            echo -e "${YELLOW}🟡 Restarting${NC}"
            ;;
        "not_found")
            echo -e "${RED}❓ Not Found${NC}"
            ;;
        *)
            echo -e "${YELLOW}🟡 $status${NC}"
            ;;
    esac
}

echo ""
echo -e "${BLUE}🔍 Service Status:${NC}"
echo "=================="
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo -e "${BLUE}🏥 Health Checks:${NC}"
echo "=================="

# Core service health checks
check_service_health "PostgreSQL" "docker compose -f $COMPOSE_FILE exec postgres pg_isready -U postgres"
check_service_health "Redis" "docker compose -f $COMPOSE_FILE exec redis redis-cli ping | grep -q PONG"

# Backend health check
if [ "$COMPOSE_FILE" = "docker-compose.dev.yml" ]; then
    check_service_health "Backend API" "curl -f http://localhost:8000/api/health/"
    check_service_health "Frontend" "curl -f http://localhost:3000/"
else
    check_service_health "Backend API" "curl -f http://localhost/api/health/"
    check_service_health "Frontend" "curl -f http://localhost/"
fi

# Enhanced mode health checks
if [ "$MODE" = "enhanced" ]; then
    check_service_health "Neo4j" "curl -f http://localhost:7474/db/system/tx/commit"
    check_service_health "Milvus" "curl -f http://localhost:9091/healthz"
fi

echo ""
echo -e "${BLUE}💾 Resource Usage:${NC}"
echo "==================="
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}" | head -15

echo ""
echo -e "${BLUE}🗄️ Database Statistics:${NC}"
echo "======================="

# PostgreSQL stats
echo "PostgreSQL:"
docker compose -f "$COMPOSE_FILE" exec postgres psql -U postgres -d legal_ai_db -c "
SELECT 
    schemaname,
    tablename,
    n_tup_ins as inserts,
    n_tup_upd as updates,
    n_tup_del as deletes
FROM pg_stat_user_tables 
WHERE schemaname = 'public'
ORDER BY n_tup_ins DESC LIMIT 5;" 2>/dev/null || echo "  ❌ Cannot connect to PostgreSQL"

# Enhanced mode database stats
if [ "$MODE" = "enhanced" ]; then
    # Neo4j stats
    echo ""
    echo "Neo4j:"
    if curl -s -u neo4j:${NEO4J_PASSWORD:-password} http://localhost:7474/db/neo4j/tx/commit \
       -H "Content-Type: application/json" \
       -d '{"statements":[{"statement":"MATCH (n) RETURN count(n) as total_nodes"}]}' | grep -q "total_nodes"; then
        
        nodes=$(curl -s -u neo4j:${NEO4J_PASSWORD:-password} http://localhost:7474/db/neo4j/tx/commit \
               -H "Content-Type: application/json" \
               -d '{"statements":[{"statement":"MATCH (n) RETURN count(n) as total_nodes"}]}' | \
               jq -r '.results[0].data[0].row[0]' 2>/dev/null || echo "0")
        
        relationships=$(curl -s -u neo4j:${NEO4J_PASSWORD:-password} http://localhost:7474/db/neo4j/tx/commit \
                       -H "Content-Type: application/json" \
                       -d '{"statements":[{"statement":"MATCH ()-[r]->() RETURN count(r) as total_rels"}]}' | \
                       jq -r '.results[0].data[0].row[0]' 2>/dev/null || echo "0")
        
        echo "  📊 Total Nodes: $nodes"
        echo "  🔗 Total Relationships: $relationships"
    else
        echo "  ❌ Cannot connect to Neo4j"
    fi

    # Milvus stats
    echo ""
    echo "Milvus:"
    if curl -s http://localhost:9091/healthz | grep -q "OK"; then
        echo "  ✅ Milvus is healthy"
        echo "  📊 Service running on port 19530"
    else
        echo "  ❌ Cannot connect to Milvus"
    fi
fi

echo ""
echo -e "${BLUE}🔄 Processing Queue Status:${NC}"
echo "=========================="

# Celery queue stats
if docker compose -f "$COMPOSE_FILE" exec celery_worker celery -A backend inspect active &>/dev/null; then
    echo "Active tasks:"
    docker compose -f "$COMPOSE_FILE" exec celery_worker celery -A backend inspect active | grep -E "(personal_document|public_document)" || echo "  No active document processing tasks"
    
    echo ""
    echo "Queue lengths:"
    docker compose -f "$COMPOSE_FILE" exec celery_worker celery -A backend inspect reserved | grep -c "personal_document\|public_document" | head -1 || echo "  0 queued tasks"
else
    echo "❌ Cannot connect to Celery worker"
fi

echo ""
echo -e "${BLUE}📈 Application Metrics:${NC}"
echo "======================"

# API endpoint tests
echo "Testing key endpoints:"
base_url="http://localhost"
if [ "$COMPOSE_FILE" = "docker-compose.dev.yml" ]; then
    base_url="http://localhost:8000"
fi

endpoints=(
    "/api/health/:Health Check"
    "/api/query/capabilities/:Query Capabilities"
)

if [ "$MODE" = "enhanced" ]; then
    endpoints+=(
        "/api/user/partition/:User Partition Info"
        "/api/admin/processing-queue/:Processing Queue"
    )
fi

for endpoint_info in "${endpoints[@]}"; do
    IFS=':' read -r endpoint description <<< "$endpoint_info"
    if curl -s -f "$base_url$endpoint" &>/dev/null; then
        echo -e "  ${GREEN}✅${NC} $description"
    else
        echo -e "  ${RED}❌${NC} $description"
    fi
done

echo ""
echo -e "${BLUE}🚨 Recent Errors:${NC}"
echo "================="

# Check for errors in logs (last 50 lines)
error_count=$(docker compose -f "$COMPOSE_FILE" logs --tail=50 | grep -i error | wc -l)
if [ "$error_count" -gt 0 ]; then
    echo -e "${RED}Found $error_count recent errors:${NC}"
    docker compose -f "$COMPOSE_FILE" logs --tail=50 | grep -i error | tail -5
else
    echo -e "${GREEN}No recent errors found${NC}"
fi

echo ""
echo -e "${BLUE}💽 Storage Usage:${NC}"
echo "=================="

# Docker volume usage
echo "Docker volumes:"
docker system df -v | grep -E "(VOLUME NAME|legal_ai)" | head -10

echo ""
echo "Host disk usage:"
df -h | grep -E "(Filesystem|/dev/)" | head -5

echo ""
echo -e "${BLUE}🔧 Quick Actions:${NC}"
echo "=================="
echo "  📋 View all logs:           docker compose -f $COMPOSE_FILE logs -f"
echo "  🔄 Restart backend:         docker compose -f $COMPOSE_FILE restart backend"
echo "  👷 Restart worker:          docker compose -f $COMPOSE_FILE restart celery_worker"
echo "  📊 Scale workers:           docker compose -f $COMPOSE_FILE up -d --scale celery_worker=3"

if [ "$MODE" = "enhanced" ]; then
    echo "  🗄️ Reset Milvus:           docker compose -f $COMPOSE_FILE restart milvus etcd minio"
    echo "  🔗 Reset Neo4j:            docker compose -f $COMPOSE_FILE restart neo4j"
fi

echo "  🧹 Clean system:           docker system prune -f"
echo "  🛑 Stop all:               docker compose -f $COMPOSE_FILE down"
echo "  🚀 Full restart:           docker compose -f $COMPOSE_FILE down && docker compose -f $COMPOSE_FILE up -d"

echo ""
echo -e "${BLUE}📊 Performance Summary:${NC}"
echo "======================"

# Calculate uptime for backend container
backend_container=$(docker compose -f "$COMPOSE_FILE" ps -q backend 2>/dev/null)
if [ -n "$backend_container" ]; then
    uptime_seconds=$(docker inspect --format='{{.State.StartedAt}}' "$backend_container" 2>/dev/null | xargs -I {} date -d {} +%s 2>/dev/null || echo "0")
    current_seconds=$(date +%s)
    uptime_duration=$((current_seconds - uptime_seconds))

    if [ "$uptime_duration" -gt 0 ]; then
        uptime_hours=$((uptime_duration / 3600))
        uptime_minutes=$(((uptime_duration % 3600) / 60))
        echo "  ⏱️ System uptime: ${uptime_hours}h ${uptime_minutes}m"
    else
        echo "  ⏱️ System uptime: Unknown"
    fi
else
    echo "  ⏱️ System uptime: Backend not running"
fi

# Memory usage summary
total_memory=$(docker stats --no-stream --format "{{.MemUsage}}" | grep -o '[0-9.]*GiB' | awk '{sum += $1} END {printf "%.2f", sum}' 2>/dev/null || echo "0")
echo "  🧠 Total memory usage: ${total_memory}GiB"

# Container count
running_containers=$(docker ps --filter "name=legal_ai" --format "{{.Names}}" | wc -l)
echo "  📦 Running containers: $running_containers"

echo ""
echo -e "${GREEN}✅ Monitoring complete!${NC}"