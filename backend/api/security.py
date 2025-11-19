# Security Module - Authentication, validation, and audit logging

import logging
import hashlib
import hmac
import os
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import UploadedFile
import magic

logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security_audit')

User = get_user_model()

# ============================================================================
# FILE VALIDATION
# ============================================================================

def validate_file_upload(uploaded_file: UploadedFile) -> Dict[str, Any]:
    """Comprehensive file upload validation"""
    try:
        # Check file size (10MB limit)
        max_size = 10 * 1024 * 1024  # 10MB
        if uploaded_file.size > max_size:
            return {
                'valid': False,
                'error': f'File size ({uploaded_file.size} bytes) exceeds maximum allowed size ({max_size} bytes)'
            }
        
        # Check file extension
        allowed_extensions = ['.pdf', '.docx', '.doc', '.txt']
        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        
        if file_ext not in allowed_extensions:
            return {
                'valid': False,
                'error': f'File type {file_ext} not allowed. Allowed types: {", ".join(allowed_extensions)}'
            }
        
        # Check MIME type
        try:
            # Read first chunk to determine MIME type
            chunk = uploaded_file.read(1024)
            uploaded_file.seek(0)  # Reset file pointer
            
            mime_type = magic.from_buffer(chunk, mime=True)
            
            allowed_mime_types = {
                '.pdf': ['application/pdf'],
                '.docx': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
                '.doc': ['application/msword'],
                '.txt': ['text/plain']
            }
            
            if mime_type not in allowed_mime_types.get(file_ext, []):
                return {
                    'valid': False,
                    'error': f'File content does not match extension. Expected MIME type for {file_ext}, got {mime_type}'
                }
                
        except Exception as e:
            logger.warning(f"MIME type validation failed: {e}")
            # Continue without MIME validation if magic fails
        
        # Check for malicious content patterns
        malicious_patterns = [
            b'<script',
            b'javascript:',
            b'vbscript:',
            b'onload=',
            b'onerror=',
            b'<?php',
            b'<%',
            b'exec(',
            b'system(',
            b'shell_exec('
        ]
        
        # Read file content for pattern checking
        try:
            uploaded_file.seek(0)
            content = uploaded_file.read()
            uploaded_file.seek(0)  # Reset file pointer
            
            content_lower = content.lower()
            for pattern in malicious_patterns:
                if pattern in content_lower:
                    return {
                        'valid': False,
                        'error': 'File contains potentially malicious content'
                    }
                    
        except Exception as e:
            logger.warning(f"Content scanning failed: {e}")
        
        return {'valid': True}
        
    except Exception as e:
        logger.error(f"File validation error: {e}")
        return {
            'valid': False,
            'error': 'File validation failed'
        }


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and other attacks"""
    import re
    
    # Remove path components
    filename = os.path.basename(filename)
    
    # Remove or replace dangerous characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Ensure filename is not empty
    if not filename:
        filename = 'unnamed_file'
    
    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:250] + ext
    
    return filename


# ============================================================================
# ACCESS CONTROL
# ============================================================================

def check_rate_limit(user_id: str, action: str, limit: int = 10, window: int = 60) -> Dict[str, Any]:
    """Check rate limiting for user actions"""
    try:
        cache_key = f"rate_limit:{user_id}:{action}"
        current_count = cache.get(cache_key, 0)
        
        if current_count >= limit:
            return {
                'allowed': False,
                'error': f'Rate limit exceeded for {action}. Try again later.',
                'retry_after': window
            }
        
        # Increment counter
        cache.set(cache_key, current_count + 1, timeout=window)
        
        return {
            'allowed': True,
            'remaining': limit - current_count - 1
        }
        
    except Exception as e:
        logger.error(f"Rate limiting error: {e}")
        # Allow on error to prevent blocking legitimate users
        return {'allowed': True, 'remaining': limit}


def validate_user_access(user, resource_type: str, resource_id: str = None) -> bool:
    """Validate user access to resources"""
    try:
        if not user or not user.is_authenticated:
            return False
        
        # Admin users have access to everything
        if user.is_staff or user.is_superuser:
            return True
        
        # Resource-specific access control
        if resource_type == 'user_document':
            if resource_id:
                from .models import UserDocument
                try:
                    document = UserDocument.objects.get(id=resource_id)
                    return document.user_id == user.id
                except UserDocument.DoesNotExist:
                    return False
            return True  # User can access their own documents
        
        elif resource_type == 'chat_session':
            if resource_id:
                from .models import ChatSession
                try:
                    session = ChatSession.objects.get(id=resource_id)
                    return session.user_id == user.id
                except ChatSession.DoesNotExist:
                    return False
            return True  # User can access their own sessions
        
        elif resource_type == 'public_document':
            return True  # All authenticated users can access public documents
        
        elif resource_type == 'admin_functions':
            return user.is_staff
        
        return False
        
    except Exception as e:
        logger.error(f"Access validation error: {e}")
        return False


# ============================================================================
# SECURITY LOGGING
# ============================================================================

def log_security_event(event_type: str, user, **kwargs):
    """Log security-related events for audit trail"""
    try:
        event_data = {
            'event_type': event_type,
            'user_id': str(user.id) if user else 'anonymous',
            'phone_number': user.phone_number if user and hasattr(user, 'phone_number') else 'unknown',
            'timestamp': timezone.now().isoformat(),
            'ip_address': kwargs.get('ip_address', 'unknown'),
            **kwargs
        }
        
        # Log to security audit logger
        security_logger.info(f"SECURITY_EVENT: {event_type}", extra=event_data)
        
        # Store in cache for recent events (last 24 hours)
        cache_key = f"security_events:{user.id if user else 'anonymous'}"
        recent_events = cache.get(cache_key, [])
        recent_events.append(event_data)
        
        # Keep only last 100 events
        if len(recent_events) > 100:
            recent_events = recent_events[-100:]
        
        cache.set(cache_key, recent_events, timeout=86400)  # 24 hours
        
    except Exception as e:
        logger.error(f"Security logging error: {e}")


def get_security_events(user, limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent security events for a user"""
    try:
        cache_key = f"security_events:{user.id}"
        events = cache.get(cache_key, [])
        return events[-limit:] if events else []
        
    except Exception as e:
        logger.error(f"Failed to retrieve security events: {e}")
        return []


# ============================================================================
# DATA ENCRYPTION
# ============================================================================

def encrypt_sensitive_data(data: str, key: Optional[str] = None) -> str:
    """Encrypt sensitive data using HMAC"""
    try:
        if not key:
            key = getattr(settings, 'HMAC_SECRET_KEY', settings.SECRET_KEY)
        
        # Create HMAC hash
        signature = hmac.new(
            key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature
        
    except Exception as e:
        logger.error(f"Data encryption error: {e}")
        return ""


def verify_data_integrity(data: str, signature: str, key: Optional[str] = None) -> bool:
    """Verify data integrity using HMAC"""
    try:
        expected_signature = encrypt_sensitive_data(data, key)
        return hmac.compare_digest(signature, expected_signature)
        
    except Exception as e:
        logger.error(f"Data verification error: {e}")
        return False


# ============================================================================
# SESSION SECURITY
# ============================================================================

def validate_session_security(request) -> Dict[str, Any]:
    """Validate session security parameters"""
    try:
        # Check for session hijacking indicators
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        ip_address = get_client_ip(request)
        
        # Store session fingerprint
        session_key = request.session.session_key
        if session_key:
            fingerprint = {
                'user_agent_hash': hashlib.sha256(user_agent.encode()).hexdigest()[:16],
                'ip_address': ip_address,
                'created_at': timezone.now().isoformat()
            }
            
            cache_key = f"session_fingerprint:{session_key}"
            stored_fingerprint = cache.get(cache_key)
            
            if stored_fingerprint:
                # Check for changes that might indicate hijacking
                if (stored_fingerprint['user_agent_hash'] != fingerprint['user_agent_hash'] or
                    stored_fingerprint['ip_address'] != fingerprint['ip_address']):
                    
                    return {
                        'valid': False,
                        'reason': 'Session fingerprint mismatch',
                        'action': 'force_logout'
                    }
            else:
                # Store new fingerprint
                cache.set(cache_key, fingerprint, timeout=86400)  # 24 hours
        
        return {'valid': True}
        
    except Exception as e:
        logger.error(f"Session validation error: {e}")
        return {'valid': True}  # Allow on error


def get_client_ip(request) -> str:
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', 'unknown')
    return ip


# ============================================================================
# SECURITY MIDDLEWARE HELPERS
# ============================================================================

def check_suspicious_activity(user, action: str, **kwargs) -> bool:
    """Check for suspicious user activity patterns"""
    try:
        # Get recent events for this user
        recent_events = get_security_events(user, limit=20)
        
        # Check for rapid successive actions
        now = timezone.now()
        recent_actions = [
            event for event in recent_events
            if event.get('event_type') == action and
            (now - datetime.fromisoformat(event['timestamp'])).total_seconds() < 300  # 5 minutes
        ]
        
        # Flag if more than 10 similar actions in 5 minutes
        if len(recent_actions) > 10:
            log_security_event(
                'suspicious_activity_detected',
                user,
                action=action,
                recent_count=len(recent_actions),
                **kwargs
            )
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Suspicious activity check error: {e}")
        return False


# ============================================================================
# SECURITY CONFIGURATION VALIDATION
# ============================================================================

def validate_security_configuration() -> Dict[str, Any]:
    """Validate security configuration on startup"""
    issues = []
    
    # Check secret key
    if not settings.SECRET_KEY or settings.SECRET_KEY == 'django-insecure-default':
        issues.append("Django SECRET_KEY is not set or using default value")
    
    # Check debug mode in production
    if settings.DEBUG and not settings.ALLOWED_HOSTS == ['*']:
        issues.append("DEBUG mode should be False in production")
    
    # Check HTTPS settings
    if not settings.SECURE_SSL_REDIRECT and not settings.DEBUG:
        issues.append("SECURE_SSL_REDIRECT should be True in production")
    
    # Check database encryption
    if not getattr(settings, 'ENCRYPTION_MASTER_KEY', None):
        issues.append("ENCRYPTION_MASTER_KEY not configured")
    
    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'timestamp': timezone.now().isoformat()
    }