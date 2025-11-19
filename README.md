# 🏛️ Legal AI Assistant (LawD)

A sophisticated Legal AI Assistant application that provides intelligent document analysis and chat capabilities for legal documents, specifically focused on the Indian Constitution. The system combines document summarization, hybrid retrieval-augmented generation (RAG), and conversational AI to help users understand and query legal content.

## ✨ Features

- **📱 Phone-based Authentication**: Secure OTP-based login via Twilio SMS
- **📄 Document Upload & Summarization**: AI-powered analysis of legal documents (PDF, DOCX)
- **💬 Intelligent Chat Assistant**: Conversational interface for querying legal documents
- **🔍 Hybrid RAG System**: Advanced retrieval combining semantic search (Milvus) with keyword search (Neo4j)
- **📚 Document Management**: Personal document library with processing status tracking
- **🏗️ Containerized Infrastructure**: Docker-based deployment with Redis caching and Celery workers

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose
- Git

### 1. Clone Repository
```bash
git clone https://github.com/Nishanthtamil/lawD.git
cd lawD
```

### 2. Environment Setup
```bash
# Copy environment files
cp .env.example .env
cp .env.dev.example .env.dev

# Edit environment files with your credentials
nano .env.dev  # For development
nano .env      # For production
```

### 3. Development Deployment
```bash
# Quick start with Docker
./deploy-dev.sh
```

### 4. Production Deployment
```bash
# Production with Nginx reverse proxy
./deploy.sh
```

## 🌐 Access URLs

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000/api
- **Django Admin**: http://localhost:8000/admin

## 🏗️ Architecture

### Backend (Django REST API)
- **Framework**: Django 5.2+ with Django REST Framework
- **Database**: PostgreSQL (production), SQLite3 (development)
- **Authentication**: JWT tokens via djangorestframework-simplejwt
- **Phone Auth**: Twilio Verify API for OTP verification
- **Background Tasks**: Celery workers for async document processing

### Frontend (React)
- **Framework**: React 19.2+ with Create React App
- **Routing**: React Router DOM v7+
- **HTTP Client**: Axios
- **UI Components**: Custom CSS with responsive design

### Infrastructure
- **Reverse Proxy**: Nginx with rate limiting and security headers
- **Cache & Queue**: Redis for caching and Celery message broker
- **Containerization**: Docker and Docker Compose
- **Process Manager**: Gunicorn for Django WSGI

### AI/ML Stack
- **Vector Database**: Milvus for semantic search
- **Graph Database**: Neo4j for structured relationships
- **Embeddings**: Sentence Transformers (all-mpnet-base-v2)
- **LLM**: Groq API (Llama models)
- **Document Processing**: PyPDF2, python-docx, Pillow, pytesseract

## 📱 SMS OTP Setup

### Twilio Configuration
1. **Sign up** at [Twilio Console](https://console.twilio.com/)
2. **Create a Verify Service** in the Twilio Console
3. **Get your credentials**:
   - Account SID
   - Auth Token
   - Verify Service SID
4. **Add to environment variables**:
   ```env
   TWILIO_ACCOUNT_SID=your_account_sid
   TWILIO_AUTH_TOKEN=your_auth_token
   TWILIO_VERIFY_SERVICE_SID=your_verify_service_sid
   ```

### Trial Account Limitations
- Twilio trial accounts can only send SMS to verified phone numbers
- **Verify your number**: https://console.twilio.com/us1/develop/phone-numbers/manage/verified
- **Or upgrade** to a paid account for unrestricted SMS

### Development Mode
- System automatically falls back to console logging when Twilio fails
- Check backend logs for OTP: `docker compose -f docker-compose.dev.yml logs backend`

## 🛠️ Development

### Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### Frontend Setup
```bash
cd frontend
npm install
npm start
```

### Database Operations
```bash
# Django migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

## 🔧 Management Commands

### Docker Operations
```bash
# View logs
docker compose -f docker-compose.dev.yml logs -f

# Restart services
docker compose -f docker-compose.dev.yml restart

# Scale workers
docker compose -f docker-compose.dev.yml up -d --scale celery_worker=3

# Stop services
./stop-services.sh
```

### Monitoring
```bash
# System status
./monitoring.sh

# Service-specific logs
docker compose -f docker-compose.dev.yml logs -f backend
docker compose -f docker-compose.dev.yml logs -f frontend
docker compose -f docker-compose.dev.yml logs -f celery_worker
```

## 🧪 Testing

### API Testing
```bash
# Test OTP sending
curl -X POST http://localhost:8000/api/auth/send-otp/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+919876543210"}'

# Test OTP verification
curl -X POST http://localhost:8000/api/auth/verify-otp/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+919876543210", "otp": "123456", "name": "Test User"}'
```

### Twilio Testing
```bash
# Test Twilio configuration
cd backend
python twilio_setup.py
```

## 📚 Documentation

- **[Infrastructure Guide](INFRASTRUCTURE.md)**: Detailed infrastructure setup
- **[Twilio Setup Guide](TWILIO_SETUP_GUIDE.md)**: SMS OTP configuration
- **[Frontend Updates](FRONTEND_UPDATES.md)**: UI/UX improvements

## 🔐 Security Features

- **Rate Limiting**: API endpoints protected with django-ratelimit
- **JWT Authentication**: Secure token-based authentication
- **CORS Protection**: Configured for secure cross-origin requests
- **Environment Variables**: Sensitive data stored in environment files
- **Input Validation**: Comprehensive request validation

## 🎯 Target Users

- Legal professionals
- Law students and researchers
- Citizens seeking constitutional information
- Legal document analysts

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/Nishanthtamil/lawD/issues)
- **Twilio Support**: [Twilio Help Center](https://support.twilio.com/)

## 🚀 Deployment Status

- ✅ **Development**: Ready with Docker Compose
- ✅ **Production**: Nginx reverse proxy configured
- ✅ **SMS OTP**: Twilio Verify API integrated
- ✅ **Background Tasks**: Celery workers operational
- ✅ **Caching**: Redis caching implemented
- ✅ **Monitoring**: Comprehensive logging and monitoring

---

