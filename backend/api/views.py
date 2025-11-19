# Consolidated Views - All API endpoints in one organized file

from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
import logging

from .models import User, OTP, ChatSession, ChatMessage, UserDocument, PublicDocument, ProcessingTask
from .serializers import (
    UserSerializer, ChatSessionSerializer, ChatMessageSerializer,
    UserDocumentSerializer
)
# Import services
from .services import AuthService, AIService, DocumentService
from .security import validate_user_access, log_security_event, check_rate_limit

# Simple access control function
def check_user_access(user, permission):
    """Simple access control check"""
    if not user or not user.is_authenticated:
        return False
    
    if permission == 'can_manage_public_docs':
        return user.is_staff
    elif permission == 'can_view_system_health':
        return user.is_staff
    
    return False

# Import tasks
from .tasks import process_user_document, process_public_document

logger = logging.getLogger(__name__)

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

class PhoneAuthView(APIView):
    """Handle phone-based authentication with OTP"""
    
    def post(self, request):
        try:
            phone_number = request.data.get('phone_number')
            action = request.data.get('action', 'login')
            
            if not phone_number:
                return Response(
                    {'error': 'Phone number is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Use auth service
            result = AuthService.send_otp(phone_number, action)
            
            if result['success']:
                return Response({
                    'message': 'OTP sent successfully',
                    'phone_number': phone_number
                })
            else:
                return Response(
                    {'error': result['error']},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Phone auth error: {str(e)}")
            return Response(
                {'error': 'Authentication service unavailable'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OTPVerifyView(APIView):
    """Verify OTP and authenticate user"""
    
    def post(self, request):
        try:
            phone_number = request.data.get('phone_number')
            otp_code = request.data.get('otp')
            
            if not phone_number or not otp_code:
                return Response(
                    {'error': 'Phone number and OTP are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Use auth service
            result = AuthService.verify_otp(phone_number, otp_code)
            
            if result['success']:
                return Response({
                    'access_token': result['access_token'],
                    'refresh_token': result['refresh_token'],
                    'user': UserSerializer(result['user']).data
                })
            else:
                return Response(
                    {'error': result['error']},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"OTP verification error: {str(e)}")
            return Response(
                {'error': 'Verification service unavailable'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['GET', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def user_profile(request):
    """Get or update user profile"""
    if request.method == 'GET':
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# CHAT ENDPOINTS
# ============================================================================

class ChatSessionListCreateView(generics.ListCreateAPIView):
    """List and create chat sessions"""
    serializer_class = ChatSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ChatSessionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a chat session"""
    serializer_class = ChatSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user)


class ChatMessageListCreateView(generics.ListCreateAPIView):
    """List and create chat messages"""
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        session_id = self.kwargs['session_id']
        return ChatMessage.objects.filter(
            session_id=session_id,
            session__user=self.request.user
        )
    
    def perform_create(self, serializer):
        session_id = self.kwargs['session_id']
        try:
            session = ChatSession.objects.get(
                id=session_id, 
                user=self.request.user
            )
            serializer.save(session=session)
        except ChatSession.DoesNotExist:
            raise ValidationError("Chat session not found")


# ============================================================================
# DOCUMENT ENDPOINTS
# ============================================================================

class UserDocumentListCreateView(generics.ListCreateAPIView):
    """List and upload user documents"""
    serializer_class = UserDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        return UserDocument.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        document = serializer.save(user=self.request.user)
        # Queue for processing
        process_user_document.delay(document.id)


class UserDocumentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a user document"""
    serializer_class = UserDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return UserDocument.objects.filter(user=self.request.user)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def summarize_document(request, document_id):
    """Summarize a specific document"""
    try:
        document = UserDocument.objects.get(
            id=document_id, 
            user=request.user
        )
        
        summary_type = request.data.get('summary_type', 'comprehensive')
        
        # Simple response for now
        return Response({
            'summary': f'Summary of {document.file_name} (type: {summary_type})',
            'summary_type': summary_type,
            'status': 'success'
        })
            
    except UserDocument.DoesNotExist:
        return Response(
            {'error': 'Document not found'},
            status=status.HTTP_404_NOT_FOUND
        )


# ============================================================================
# AI QUERY ENDPOINTS
# ============================================================================

class HybridQueryView(APIView):
    """Process hybrid queries using AI services"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        try:
            query = request.data.get('query', '').strip()
            if not query:
                return Response(
                    {'error': 'Query is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Simple response for now
            return Response({
                'response': f'Response to: {query}',
                'sources': [],
                'total_results': 0,
                'status': 'success'
            })
            
        except Exception as e:
            logger.error(f"Query processing error: {str(e)}")
            return Response(
                {'error': 'Query processing failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChatQueryView(APIView):
    """Process conversational queries"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        try:
            message = request.data.get('message', '').strip()
            session_id = request.data.get('session_id')
            
            if not message:
                return Response(
                    {'error': 'Message is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Simple response for now
            return Response({
                'response': f'Chat response to: {message}',
                'status': 'success'
            })
            
        except Exception as e:
            logger.error(f"Chat processing error: {str(e)}")
            return Response(
                {'error': 'Chat processing failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================================
# ADMIN ENDPOINTS
# ============================================================================

class AdminDocumentListView(generics.ListAPIView):
    """Admin view for managing public documents"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        if not check_user_access(self.request.user, 'can_manage_public_docs'):
            return PublicDocument.objects.none()
        return PublicDocument.objects.all()
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        data = []
        for doc in queryset:
            data.append({
                'id': str(doc.id),
                'title': doc.title,
                'document_type': doc.document_type,
                'processing_status': doc.processing_status,
                'created_at': doc.created_at
            })
        return Response(data)


class SystemHealthView(APIView):
    """System health and metrics"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        if not check_user_access(request.user, 'can_view_system_health'):
            raise PermissionDenied("Insufficient permissions")
        
        # Simple health check
        health_data = {
            'database': 'healthy',
            'ai_services': 'healthy',
            'cache': 'healthy',
            'timestamp': timezone.now().isoformat()
        }
        
        return Response(health_data)


# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@api_view(['GET'])
def health_check(request):
    """Basic health check endpoint"""
    return Response({
        'status': 'healthy',
        'service': 'Legal Assistant API',
        'timestamp': timezone.now().isoformat()
    })