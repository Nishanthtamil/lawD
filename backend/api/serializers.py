from rest_framework import serializers
from .models import User, ChatSession, ChatMessage, UserDocument

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'phone_number', 'name', 'email', 'is_verified', 'date_joined']
        read_only_fields = ['id', 'date_joined']


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ['id', 'role', 'content', 'created_at']
        read_only_fields = ['id', 'created_at']


class ChatSessionSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)
    message_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatSession
        fields = ['id', 'title', 'created_at', 'updated_at', 'messages', 'message_count']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_message_count(self, obj):
        return obj.messages.count()


class ChatSessionListSerializer(serializers.ModelSerializer):
    """Lighter serializer for listing sessions without messages"""
    message_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatSession
        fields = ['id', 'title', 'created_at', 'updated_at', 'message_count', 'last_message']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_message_count(self, obj):
        return obj.messages.count()
    
    def get_last_message(self, obj):
        last_msg = obj.messages.last()
        if last_msg:
            return {
                'role': last_msg.role,
                'content': last_msg.content[:100] + '...' if len(last_msg.content) > 100 else last_msg.content,
                'created_at': last_msg.created_at
            }
        return None


class UserDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = UserDocument
        fields = ['id', 'file_name', 'file_url', 'file_size', 'file_type', 
                  'summary_type', 'summary', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'file_url']
    
    def get_file_url(self, obj):
        if obj.file_path:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file_path.url)
        return None