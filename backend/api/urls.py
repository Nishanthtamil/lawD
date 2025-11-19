from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import admin_document_views

router = DefaultRouter()

urlpatterns = [
    path('', include(router.urls)),
    
    # ============================================================================
    # AUTHENTICATION ENDPOINTS
    # ============================================================================
    path('auth/phone/', views.PhoneAuthView.as_view(), name='phone_auth'),
    path('auth/verify/', views.OTPVerifyView.as_view(), name='otp_verify'),
    path('auth/profile/', views.user_profile, name='user_profile'),
    
    # ============================================================================
    # CHAT ENDPOINTS
    # ============================================================================
    path('chat/sessions/', views.ChatSessionListCreateView.as_view(), name='chat_sessions'),
    path('chat/sessions/<int:pk>/', views.ChatSessionDetailView.as_view(), name='chat_session_detail'),
    path('chat/sessions/<int:session_id>/messages/', views.ChatMessageListCreateView.as_view(), name='chat_messages'),
    
    # ============================================================================
    # DOCUMENT ENDPOINTS
    # ============================================================================
    path('documents/', views.UserDocumentListCreateView.as_view(), name='user_documents'),
    path('documents/<int:pk>/', views.UserDocumentDetailView.as_view(), name='user_document_detail'),
    path('documents/<int:document_id>/summarize/', views.summarize_document, name='summarize_document'),
    
    # ============================================================================
    # AI QUERY ENDPOINTS
    # ============================================================================
    path('query/', views.HybridQueryView.as_view(), name='hybrid_query'),
    path('query/chat/', views.ChatQueryView.as_view(), name='chat_query'),
    
    # ============================================================================
    # ADMIN ENDPOINTS
    # ============================================================================
    path('admin/documents/', views.AdminDocumentListView.as_view(), name='admin_documents'),
    path('admin/documents/upload/', admin_document_views.upload_public_document, name='admin_upload_document'),
    path('admin/documents/list/', admin_document_views.list_public_documents, name='admin_list_documents'),
    path('admin/documents/<uuid:document_id>/', admin_document_views.get_public_document, name='admin_get_document'),
    path('admin/documents/<uuid:document_id>/update/', admin_document_views.update_public_document, name='admin_update_document'),
    path('admin/documents/<uuid:document_id>/delete/', admin_document_views.delete_public_document, name='admin_delete_document'),
    path('admin/documents/<uuid:document_id>/reprocess/', admin_document_views.reprocess_public_document, name='admin_reprocess_document'),
    path('admin/processing-queue/', admin_document_views.admin_processing_queue, name='admin_processing_queue'),
    path('admin/system-health/', views.SystemHealthView.as_view(), name='system_health'),
    
    # ============================================================================
    # HEALTH CHECK
    # ============================================================================
    path('health/', views.health_check, name='health_check'),
]