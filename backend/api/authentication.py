from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import AccessToken
from .models import User

class JWTAuthentication(BaseAuthentication):
    """Custom JWT authentication"""
    
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return None
        
        try:
            # Expected format: "Bearer <token>"
            prefix, token = auth_header.split(' ')
            if prefix.lower() != 'bearer':
                return None
            
            # Decode token
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            
            # Get user
            user = User.objects.get(id=user_id)
            
            return (user, token)
            
        except Exception as e:
            raise AuthenticationFailed('Invalid token')
    
    def authenticate_header(self, request):
        return 'Bearer'