from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
    path('chat/', views.chat, name='chat'),
    path('summarize/', views.summarize_document, name='summarize_document'),
]
