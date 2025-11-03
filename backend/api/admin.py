from django.contrib import admin
from .models import User, OTP, ChatSession, ChatMessage, UserDocument

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['phone_number', 'name', 'is_verified', 'date_joined']
    search_fields = ['phone_number', 'name']
    list_filter = ['is_verified', 'is_active']

@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ['phone_number', 'otp', 'created_at', 'is_verified']
    list_filter = ['is_verified']

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'title', 'created_at']
    search_fields = ['user__phone_number', 'title']

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['session', 'role', 'created_at']
    list_filter = ['role']

@admin.register(UserDocument)
class UserDocumentAdmin(admin.ModelAdmin):
    list_display = ['user', 'file_name', 'status', 'created_at']
    list_filter = ['status', 'file_type']