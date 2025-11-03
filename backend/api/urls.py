from django.urls import path
from . import views, auth_views, chat_views, document_views

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
    path('chat/', views.chat, name='chat'),
    path('summarize/', views.summarize_document, name='summarize_document'),
    path('auth/send-otp/', auth_views.send_otp, name='send_otp'),
    path('auth/verify-otp/', auth_views.verify_otp, name='verify_otp'),
    path('auth/logout/', auth_views.logout, name='logout'),
    path('auth/profile/', auth_views.get_profile, name='get_profile'),
    path('auth/profile/update/', auth_views.update_profile, name='update_profile'),
    
    # Chat Sessions
    path('chat/sessions/', chat_views.list_chat_sessions, name='list_chat_sessions'),
    path('chat/sessions/create/', chat_views.create_chat_session, name='create_chat_session'),
    path('chat/sessions/<uuid:session_id>/', chat_views.get_chat_session, name='get_chat_session'),
    path('chat/sessions/<uuid:session_id>/update/', chat_views.update_chat_session, name='update_chat_session'),
    path('chat/sessions/<uuid:session_id>/delete/', chat_views.delete_chat_session, name='delete_chat_session'),
    path('chat/sessions/<uuid:session_id>/messages/', chat_views.get_session_messages, name='get_session_messages'),
    path('chat/sessions/<uuid:session_id>/messages/send/', chat_views.send_message, name='send_message'),
    path('chat/sessions/<uuid:session_id>/messages/clear/', chat_views.clear_session_messages, name='clear_session_messages'),
    
    # Documents
    path('documents/', document_views.list_documents, name='list_documents'),
    path('documents/upload/', document_views.upload_document, name='upload_document'),
    path('documents/<uuid:document_id>/', document_views.get_document, name='get_document'),
    path('documents/<uuid:document_id>/summarize/', document_views.summarize_user_document, name='summarize_user_document'),
    path('documents/<uuid:document_id>/delete/', document_views.delete_document, name='delete_document'),
    path('documents/<uuid:document_id>/download/', document_views.download_document, name='download_document'),

]
