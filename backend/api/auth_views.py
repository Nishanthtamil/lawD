import random
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django_ratelimit.decorators import ratelimit
from .models import User, OTP
from .serializers import UserSerializer


def send_otp_sms(phone_number, otp=None):
    """
    Send OTP via Twilio Verify API
    This is more reliable than sending SMS directly
    """
    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException
        import os
        
        # Twilio credentials from environment
        TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
        TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
        TWILIO_VERIFY_SERVICE_SID = os.environ.get('TWILIO_VERIFY_SERVICE_SID')
        
        print(f"🔍 Twilio Config Check:")
        print(f"   Account SID: {'✅ Set' if TWILIO_ACCOUNT_SID else '❌ Missing'}")
        print(f"   Auth Token: {'✅ Set' if TWILIO_AUTH_TOKEN else '❌ Missing'}")
        print(f"   Verify SID: {'✅ Set' if TWILIO_VERIFY_SERVICE_SID else '❌ Missing'}")
        
        # For development: if Twilio credentials not set, just print OTP
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SERVICE_SID]):
            # Generate OTP for dev mode
            dev_otp = otp or str(random.randint(100000, 999999))
            print(f"\n{'='*50}")
            print(f"📱 DEV MODE - OTP for {phone_number}: {dev_otp}")
            print(f"⚠️  To use Twilio Verify, set TWILIO_VERIFY_SERVICE_SID")
            print(f"{'='*50}\n")
            return True
        
        # Validate phone number format for Twilio
        if not phone_number.startswith('+'):
            print(f"❌ Invalid phone format for Twilio: {phone_number}")
            return False
        
        # Send via Twilio Verify Service
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        print(f"📤 Sending OTP to {phone_number} via Twilio Verify...")
        
        verification = client.verify \
            .v2 \
            .services(TWILIO_VERIFY_SERVICE_SID) \
            .verifications \
            .create(to=phone_number, channel='sms')
        
        print(f"✅ OTP sent successfully via Twilio Verify!")
        print(f"   Status: {verification.status}")
        print(f"   SID: {verification.sid}")
        print(f"   To: {verification.to}")
        return True
        
    except ImportError as e:
        # Twilio not installed - fallback to print
        dev_otp = otp or str(random.randint(100000, 999999))
        print(f"\n{'='*50}")
        print(f"⚠️  Twilio not installed: {str(e)}")
        print(f"📱 DEV MODE - OTP for {phone_number}: {dev_otp}")
        print(f"{'='*50}\n")
        return True
        
    except TwilioRestException as e:
        print(f"❌ Twilio API Error: {e.msg}")
        print(f"   Error Code: {e.code}")
        print(f"   Status: {e.status}")
        
        # Handle specific Twilio trial account limitations
        if e.code == 21608:  # Unverified number in trial account
            print(f"\n{'='*60}")
            print(f"🔒 TWILIO TRIAL ACCOUNT LIMITATION")
            print(f"📱 Phone number {phone_number} needs to be verified")
            print(f"🌐 Visit: https://console.twilio.com/us1/develop/phone-numbers/manage/verified")
            print(f"➕ Add {phone_number} to your verified numbers")
            print(f"{'='*60}")
            
        # Fallback to printing OTP
        dev_otp = otp or str(random.randint(100000, 999999))
        print(f"\n{'='*50}")
        print(f"📱 FALLBACK - OTP for {phone_number}: {dev_otp}")
        print(f"   Reason: Twilio API Error - {e.msg}")
        print(f"{'='*50}\n")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error sending OTP: {str(e)}")
        # Fallback to printing OTP
        dev_otp = otp or str(random.randint(100000, 999999))
        print(f"\n{'='*50}")
        print(f"📱 FALLBACK - OTP for {phone_number}: {dev_otp}")
        print(f"   Reason: {str(e)}")
        print(f"{'='*50}\n")
        return False


def verify_otp_with_twilio(phone_number, otp_code):
    """
    Verify OTP using Twilio Verify API
    Returns (success: bool, error_message: str)
    """
    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException
        import os
        
        TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
        TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
        TWILIO_VERIFY_SERVICE_SID = os.environ.get('TWILIO_VERIFY_SERVICE_SID')
        
        # If Twilio not configured, fall back to database verification
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SERVICE_SID]):
            print("🔄 Twilio not configured, using database verification")
            return None, None  # Use database verification
        
        print(f"🔍 Verifying OTP {otp_code} for {phone_number} via Twilio...")
        
        # Verify with Twilio
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        verification_check = client.verify \
            .v2 \
            .services(TWILIO_VERIFY_SERVICE_SID) \
            .verification_checks \
            .create(to=phone_number, code=otp_code)
        
        print(f"📋 Twilio Verification Result:")
        print(f"   Status: {verification_check.status}")
        print(f"   SID: {verification_check.sid}")
        
        if verification_check.status == 'approved':
            print(f"✅ OTP verified successfully via Twilio Verify")
            return True, None
        else:
            error_msg = f"Invalid OTP. Status: {verification_check.status}"
            print(f"❌ {error_msg}")
            return False, error_msg
            
    except TwilioRestException as e:
        error_msg = str(e.msg)
        print(f"❌ Twilio Verify API Error: {error_msg}")
        print(f"   Error Code: {e.code}")
        print(f"   Status: {e.status}")
        
        # If verification record not found (common when send failed), fall back to database
        if e.code == 20404:  # Not found - verification record doesn't exist
            print("🔄 Verification record not found, falling back to database verification")
            return None, None
        
        # If error is about invalid code, return specific error
        if e.code in [60200, 60202]:  # Common invalid/expired OTP codes
            return False, "Invalid or expired OTP"
        
        # For other errors, fall back to database verification
        print("🔄 Falling back to database verification due to Twilio error")
        return None, None
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Unexpected Twilio Verify error: {error_msg}")
        
        # If error is about invalid code, return specific error
        if 'not found' in error_msg.lower() or 'invalid' in error_msg.lower():
            return False, "Invalid or expired OTP"
        
        # For other errors, fall back to database verification
        print("🔄 Falling back to database verification due to unexpected error")
        return None, None


@api_view(['POST'])
@permission_classes([AllowAny])
@ratelimit(key='ip', rate='5/m', method='POST')
def send_otp(request):
    """
    Send OTP to phone number using Twilio Verify
    
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
        # Generate 6-digit OTP (for database fallback)
        otp_code = str(random.randint(100000, 999999))
        
        # Set expiry time (5 minutes from now)
        expires_at = timezone.now() + timedelta(minutes=5)
        
        # Invalidate previous OTPs for this number
        OTP.objects.filter(phone_number=phone_number, is_verified=False).update(is_verified=True)
        
        # Create new OTP in database (as fallback)
        otp = OTP.objects.create(
            phone_number=phone_number,
            otp=otp_code,
            expires_at=expires_at
        )
        
        # Send OTP via Twilio Verify (or print if not configured)
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
@ratelimit(key='ip', rate='10/m', method='POST')
def verify_otp(request):
    """
    Verify OTP and login/register user using Twilio Verify
    
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
        # First, try to verify with Twilio Verify API
        twilio_success, twilio_error = verify_otp_with_twilio(phone_number, otp_code)
        
        # If Twilio verification succeeded
        if twilio_success is True:
            # Mark any database OTP as verified (for consistency)
            OTP.objects.filter(
                phone_number=phone_number,
                is_verified=False
            ).update(is_verified=True)
            
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
        
        # If Twilio verification explicitly failed
        elif twilio_success is False:
            return Response(
                {"error": twilio_error or "Invalid OTP"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # If Twilio not configured or error, fall back to database verification
        else:
            # Find valid OTP in database
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
        import traceback
        print(traceback.format_exc())
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