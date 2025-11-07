# Legal AI Assistant - Infrastructure Setup

This document describes the complete infrastructure setup with Nginx reverse proxy, Redis caching, and Celery background processing.

## Architecture Overview

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Frontend  │    │    Nginx    │    │   Backend   │
│   (React)   │◄──►│ Reverse Proxy│◄──►│  (Django)   │
│   Port 3000 │    │   Port 80   │    │  Port 8000  │
└─────────────┘    └─────────────┘    └─────────────┘
                           │
                           ▼
                   ┌─────────────┐
                   │   Redis     │
                   │  (Cache &   │
                   │   Queue)    │
                   │  Port 6379  │
                   └─────────────┘
                           │
                           ▼
                   ┌─────────────┐
                   │   Celery    │
                   │  Workers    │
                   │ (Background │
                   │   Tasks)    │
                   └─────────────┘
```

## Components

### 1. Nginx Reverse Proxy
- **Purpose**: Load balancing, SSL termination, rate limiting, static file serving
- **Features**:
  - API rate limiting (10 req/s general, 5 req/s auth, 2 req/s uploads)
  - Security headers (XSS protection, CSRF, etc.)
  - Gzip compression
  - CORS handling
  - Health checks

### 2. Redis Cache & Message Broker
- **Purpose**: Caching and Celery message broker
- **Cached Data**:
  - Chat sessions (1 hour TTL)
  - Document summaries (24 hours TTL)
  - Search results
  - User sessions

### 3. Celery Background Processing
- **Workers**: Process document uploads, generate summaries
- **Beat Scheduler**: Cleanup tasks, maintenance
- **Tasks**:
  - `process_document_async`: Document text extraction and summarization
  - `cache_chat_session`: Cache chat data
  - `cleanup_expired_sessions`: Remove old sessions
  - `cleanup_old_documents`: Remove old files

### 4. PostgreSQL Database
- **Purpose**: Primary data storage
- **Models**: Users, Documents, Chat Sessions, Messages, OTP

## Quick Start

### 1. Prerequisites
```bash
# Install Docker and Docker Compose
sudo apt update
sudo apt install docker.io docker-compose

# Add user to docker group
sudo usermod -aG docker $USER
# Log out and back in
```

### 2. Configuration
```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env
```

Required environment variables:
- `DJANGO_SECRET_KEY`: Generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- `GROQ_API_KEY`: Get from Groq Console
- Database passwords
- Twilio credentials (optional, for SMS)

### 3. Deploy
```bash
# Run deployment script
./deploy.sh

# Or manual deployment:
docker-compose up -d
```

### 4. Monitor
```bash
# Check system status
./monitoring.sh

# View logs
docker-compose logs -f

# Check specific service
docker-compose logs -f backend
```

## Rate Limiting Configuration

### API Endpoints
- **General API**: 10 requests/second per IP
- **Authentication**: 5 requests/second per IP  
- **File Uploads**: 2 requests/second per IP
- **Chat Messages**: 10 requests/minute per user
- **Document Operations**: 5 requests/minute per user

### Nginx Configuration
```nginx
# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/s;
limit_req_zone $binary_remote_addr zone=upload:10m rate=2r/s;
```

## Caching Strategy

### Redis Cache Keys
- `chat_session_{session_id}`: Chat messages and metadata
- `document_summary_{document_id}`: Generated document summaries
- `document_search_index`: Searchable document index
- `indexed_doc_{document_id}`: Full document content for search

### Cache TTL
- Chat sessions: 1 hour
- Document summaries: 24 hours
- Search index: 24 hours
- User sessions: Django default

## Background Tasks

### Document Processing Pipeline
1. **Upload**: File uploaded to Django media storage
2. **Queue**: `process_document_async` task queued
3. **Extract**: Text extracted from PDF/DOCX/TXT
4. **Summarize**: AI-generated summary using Groq
5. **Index**: Document indexed for search
6. **Cache**: Summary cached in Redis

### Scheduled Tasks
- **Hourly**: Cleanup expired sessions
- **Daily**: Remove old documents and files
- **Weekly**: Database optimization (can be added)

## Security Features

### Nginx Security Headers
```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer-when-downgrade" always;
```

### Rate Limiting
- IP-based rate limiting for authentication endpoints
- User-based rate limiting for API operations
- Burst allowance with nodelay processing

### File Upload Security
- File type validation
- Size limits (10MB max)
- Virus scanning (can be added)

## Monitoring & Logging

### Health Checks
- **Nginx**: `/health` endpoint
- **Backend**: Django health check
- **Redis**: `redis-cli ping`
- **PostgreSQL**: `pg_isready`

### Log Files
- **Nginx**: Access and error logs
- **Django**: Application logs
- **Celery**: Worker and beat logs
- **PostgreSQL**: Database logs

### Metrics Collection
```bash
# Container stats
docker stats

# Service status
docker-compose ps

# Application metrics
curl http://localhost/health
```

## Scaling

### Horizontal Scaling
```bash
# Scale Celery workers
docker-compose up -d --scale celery_worker=3

# Scale backend instances (requires load balancer config)
docker-compose up -d --scale backend=2
```

### Vertical Scaling
```yaml
# In docker-compose.yml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
```

## Troubleshooting

### Common Issues

1. **Redis Connection Error**
   ```bash
   docker-compose restart redis
   docker-compose logs redis
   ```

2. **Celery Worker Not Processing**
   ```bash
   docker-compose restart celery_worker
   docker-compose exec celery_worker celery -A backend inspect active
   ```

3. **Nginx 502 Bad Gateway**
   ```bash
   docker-compose logs nginx
   docker-compose restart backend
   ```

4. **Database Connection Issues**
   ```bash
   docker-compose logs postgres
   docker-compose exec postgres pg_isready -U postgres
   ```

### Performance Tuning

1. **Redis Memory**
   ```bash
   # Check Redis memory usage
   docker-compose exec redis redis-cli info memory
   ```

2. **PostgreSQL Connections**
   ```bash
   # Check active connections
   docker-compose exec postgres psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
   ```

3. **Celery Queue Length**
   ```bash
   # Check queue length
   docker-compose exec celery_worker celery -A backend inspect active
   ```

## Production Considerations

### SSL/HTTPS Setup
1. Obtain SSL certificates (Let's Encrypt recommended)
2. Update Nginx configuration for HTTPS
3. Set up automatic certificate renewal

### Database Backup
```bash
# Automated backup script
docker-compose exec postgres pg_dump -U postgres legal_ai_db > backup_$(date +%Y%m%d).sql
```

### Log Rotation
```bash
# Configure logrotate for Docker logs
sudo nano /etc/logrotate.d/docker-containers
```

### Monitoring Setup
- Set up Prometheus + Grafana for metrics
- Configure alerting for service failures
- Monitor disk space and memory usage

## Environment Variables Reference

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DJANGO_SECRET_KEY` | Django secret key | - | Yes |
| `DEBUG` | Debug mode | False | No |
| `DB_NAME` | Database name | legal_ai_db | Yes |
| `DB_USER` | Database user | postgres | Yes |
| `DB_PASSWORD` | Database password | - | Yes |
| `REDIS_URL` | Redis connection URL | redis://redis:6379/0 | No |
| `GROQ_API_KEY` | Groq API key | - | Yes |
| `TWILIO_ACCOUNT_SID` | Twilio account SID | - | No |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | - | No |

## Support

For issues and questions:
1. Check logs: `docker-compose logs -f`
2. Run monitoring: `./monitoring.sh`
3. Check service status: `docker-compose ps`
4. Review this documentation