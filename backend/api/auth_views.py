import random
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, OTP
from .serializers import UserSerializer
import dotenv


def send_otp_sms(phone_number, otp):
    """
    Send OTP via SMS using Twilio
    """
    try:

        from twilio.rest import Client
        import os
        dotenv.load_dotenv()
        
        # Twilio credentials from environment
        TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
        TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
        TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
        
        # For development: if Twilio credentials not set, just print OTP
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
            print(f"\n{'='*50}")
            print(f"📱 DEV MODE - OTP for {phone_number}: {otp}")
            print(f"{'='*50}\n")
            return True
        
        # Send via Twilio
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        message = client.messages.create(
            body=f"Your Legal Assistant verification code is: {otp}\n\nThis code expires in 5 minutes.",
            from_=TWILIO_PHONE_NUMBER,
            to=phone_number
        )
        
        print(f"✅ OTP sent successfully via Twilio. SID: {message.sid}")
        return True
        
    except ImportError:
        # Twilio not installed - fallback to print
        print(f"\n{'='*50}")
        print(f"⚠️  Twilio not installed - DEV MODE")
        print(f"📱 OTP for {phone_number}: {otp}")
        print(f"{'='*50}\n")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send SMS via Twilio: {str(e)}")
        # Fallback to printing OTP
        print(f"\n{'='*50}")
        print(f"📱 FALLBACK - OTP for {phone_number}: {otp}")
        print(f"{'='*50}\n")
        return True


@api_view(['POST'])
@permission_classes([AllowAny])
def send_otp(request):
    """
    Send OTP to phone number
    
    Request body:
    {
        "phone_number": "+919876543210"
    }
    """
    phone_number = request.data.get('phone_number')
    
    if not phone_number:
        return Response(
            {"error": "Phone number is required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate phone number format (basic validation)
    if not phone_number.startswith('+') or len(phone_number) < 10:
        return Response(
            {"error": "Invalid phone number format. Use format: +919876543210"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        
        # Set expiry time (5 minutes from now)
        expires_at = timezone.now() + timedelta(minutes=5)
        
        # Invalidate previous OTPs for this number
        OTP.objects.filter(phone_number=phone_number, is_verified=False).update(is_verified=True)
        
        # Create new OTP
        otp = OTP.objects.create(
            phone_number=phone_number,
            otp=otp_code,
            expires_at=expires_at
        )
        
        # Send OTP via SMS
        send_otp_sms(phone_number, otp_code)
        
        return Response({
            "message": "OTP sent successfully",
            "phone_number": phone_number,
            "expires_in": 300  # seconds
        })
        
    except Exception as e:
        return Response(
            {"error": f"Failed to send OTP: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    """
    Verify OTP and login/register user
    
    Request body:
    {
        "phone_number": "+919876543210",
        "otp": "123456",
        "name": "John Doe"  // Optional, for registration
    }
    """
    phone_number = request.data.get('phone_number')
    otp_code = request.data.get('otp')
    name = request.data.get('name', '')
    
    if not phone_number or not otp_code:
        return Response(
            {"error": "Phone number and OTP are required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Find valid OTP
        otp = OTP.objects.filter(
            phone_number=phone_number,
            otp=otp_code,
            is_verified=False
        ).first()
        
        if not otp:
            return Response(
                {"error": "Invalid OTP"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not otp.is_valid():
            return Response(
                {"error": "OTP has expired"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Mark OTP as verified
        otp.is_verified = True
        otp.save()
        
        # Get or create user
        user, created = User.objects.get_or_create(
            phone_number=phone_number,
            defaults={'name': name, 'is_verified': True}
        )
        
        # If existing user, update verification status
        if not created and not user.is_verified:
            user.is_verified = True
            user.save()
        
        # Update name if provided
        if name and not user.name:
            user.name = name
            user.save()
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            "message": "Login successful" if not created else "Account created successfully",
            "user": UserSerializer(user).data,
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token)
            }
        })
        
    except Exception as e:
        return Response(
            {"error": f"Verification failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """
    Logout user
    This is optional - JWT tokens are stateless
    You can implement token blacklisting if needed
    """
    return Response({
        "message": "Logged out successfully"
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_profile(request):
    """Get current user profile"""
    return Response({
        "user": UserSerializer(request.user).data
    })


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """
    Update user profile
    
    Request body:
    {
        "name": "John Doe",
        "email": "john@example.com"
    }
    """
    user = request.user
    
    name = request.data.get('name')
    email = request.data.get('email')
    
    if name:
        user.name = name
    if email:
        user.email = email
    
    user.save()
    
    return Response({
        "message": "Profile updated successfully",
        "user": UserSerializer(user).data
    })