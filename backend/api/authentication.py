from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from django.utils import timezone
from django.conf import settings
import random
import string
import logging

from .models import User, OTP

logger = logging.getLogger(__name__)

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


class AuthService:
    """Authentication service for OTP and user management"""
    
    @staticmethod
    def send_otp(phone_number: str, action: str = 'login'):
        """Send OTP to phone number"""
        try:
            # Generate OTP
            otp_code = ''.join(random.choices(string.digits, k=6))
            
            # Set expiration (5 minutes)
            expires_at = timezone.now() + timezone.timedelta(minutes=5)
            
            # Save OTP
            OTP.objects.filter(phone_number=phone_number, is_verified=False).delete()
            otp_obj = OTP.objects.create(
                phone_number=phone_number,
                otp=otp_code,
                expires_at=expires_at
            )
            
            # In development, just log the OTP
            logger.info(f"OTP for {phone_number}: {otp_code}")
            
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Failed to send OTP: {str(e)}")
            return {'success': False, 'error': 'Failed to send OTP'}
    
    @staticmethod
    def verify_otp(phone_number: str, otp_code: str):
        """Verify OTP and authenticate user"""
        try:
            # Find valid OTP
            otp_obj = OTP.objects.filter(
                phone_number=phone_number,
                otp=otp_code,
                is_verified=False
            ).first()
            
            if not otp_obj or not otp_obj.is_valid():
                return {'success': False, 'error': 'Invalid or expired OTP'}
            
            # Mark OTP as verified
            otp_obj.is_verified = True
            otp_obj.save()
            
            # Get or create user
            user, created = User.objects.get_or_create(
                phone_number=phone_number,
                defaults={'is_verified': True}
            )
            
            if not created:
                user.is_verified = True
                user.last_login = timezone.now()
                user.save()
            
            # Generate tokens
            refresh = RefreshToken.for_user(user)
            
            return {
                'success': True,
                'user': user,
                'access_token': str(refresh.access_token),
                'refresh_token': str(refresh)
            }
            
        except Exception as e:
            logger.error(f"OTP verification failed: {str(e)}")
            return {'success': False, 'error': 'Verification failed'}