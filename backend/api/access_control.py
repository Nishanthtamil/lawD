"""
Access control middleware and security checks for strict data segregation.
Implements partition validation, user ID filtering, and cross-user data access prevention.
"""

import logging
import uuid
from typing import Dict, List, Optional, Any, Tuple
from functools import wraps

from django.http import JsonResponse
from django.core.exceptions import ValidationError, PermissionDenied
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.request import Request

from .models import User, UserDocument, UserPartition
from .milvus_manager import PartitionManager

logger = logging.getLogger(__name__)

User = get_user_model()


class DataSegregationMiddleware:
    """
    Middleware to enforce strict data segregation for all user queries.
    Validates partition access and prevents cross-user data leakage.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.partition_manager = PartitionManager()
        
        # Paths that require partition validation
        self.protected_paths = [
            '/api/documents/',
            '/api/chat/',
            '/api/query/',
            '/api/personal/',
        ]
        
        # Admin-only paths
        self.admin_paths = [
            '/api/admin/',
            '/api/public-documents/',
            '/api/system/',
        ]
    
    def __call__(self, request):
        """Process request through data segregation checks"""
        
        # Skip validation for non-protected paths
        if not self._is_protected_path(request.path):
            return self.get_response(request)
        
        # Validate user authentication
        if not request.user.is_authenticated:
            return JsonResponse(
                {'error': 'Authentication required for data access'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Validate admin access for admin paths
        if self._is_admin_path(request.path) and not request.user.is_staff:
            return JsonResponse(
                {'error': 'Admin privileges required'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Add user context to request for downstream validation
        request.user_context = {
            'user_id': str(request.user.id),
            'is_admin': request.user.is_staff,
            'partition_name': self.partition_manager.get_user_partition_name(str(request.user.id))
        }
        
        response = self.get_response(request)
        return response
    
    def _is_protected_path(self, path: str) -> bool:
        """Check if path requires data segregation validation"""
        return any(path.startswith(protected) for protected in self.protected_paths)
    
    def _is_admin_path(self, path: str) -> bool:
        """Check if path requires admin privileges"""
        return any(path.startswith(admin) for admin in self.admin_paths)


class PartitionAccessValidator:
    """
    Validates partition access for Milvus queries and operations.
    Ensures users can only access their own data partitions.
    """
    
    def __init__(self):
        self.partition_manager = PartitionManager()
    
    def validate_partition_access(self, user_id: str, partition_name: str) -> bool:
        """
        Validate that a user can access a specific partition.
        
        Args:
            user_id: UUID string of the requesting user
            partition_name: Name of the partition to access
            
        Returns:
            bool: True if access is allowed, False otherwise
        """
        try:
            return self.partition_manager.validate_partition_access(user_id, partition_name)
        except Exception as e:
            logger.error(f"Error validating partition access: {e}")
            return False
    
    def get_user_partition_filter(self, user_id: str) -> str:
        """
        Get the partition name for user data filtering.
        
        Args:
            user_id: UUID string of the user
            
        Returns:
            str: Partition name for filtering queries
        """
        return self.partition_manager.get_user_partition_name(user_id)
    
    def validate_document_ownership(self, user_id: str, document_id: str) -> bool:
        """
        Validate that a user owns a specific document.
        
        Args:
            user_id: UUID string of the user
            document_id: UUID string of the document
            
        Returns:
            bool: True if user owns the document, False otherwise
        """
        try:
            UserDocument.objects.get(id=document_id, user_id=user_id)
            return True
        except UserDocument.DoesNotExist:
            logger.warning(f"Document ownership validation failed: user {user_id} does not own document {document_id}")
            return False
        except Exception as e:
            logger.error(f"Error validating document ownership: {e}")
            return False
    
    def get_user_document_filter(self, user_id: str) -> Dict[str, str]:
        """
        Get filter parameters for user document queries.
        
        Args:
            user_id: UUID string of the user
            
        Returns:
            Dict: Filter parameters for database queries
        """
        return {'user_id': user_id}


class SecurityAuditLogger:
    """
    Logs security-related events for audit and monitoring.
    Tracks access attempts, violations, and data operations.
    """
    
    def __init__(self):
        self.audit_logger = logging.getLogger('security_audit')
    
    def log_partition_access(self, user_id: str, partition_name: str, action: str, success: bool):
        """Log partition access attempts"""
        self.audit_logger.info(
            f"PARTITION_ACCESS: user={user_id}, partition={partition_name}, "
            f"action={action}, success={success}"
        )
    
    def log_document_access(self, user_id: str, document_id: str, action: str, success: bool):
        """Log document access attempts"""
        self.audit_logger.info(
            f"DOCUMENT_ACCESS: user={user_id}, document={document_id}, "
            f"action={action}, success={success}"
        )
    
    def log_security_violation(self, user_id: str, violation_type: str, details: Dict[str, Any]):
        """Log security violations"""
        self.audit_logger.warning(
            f"SECURITY_VIOLATION: user={user_id}, type={violation_type}, "
            f"details={details}"
        )
    
    def log_admin_action(self, admin_id: str, action: str, target: str, success: bool):
        """Log admin actions"""
        self.audit_logger.info(
            f"ADMIN_ACTION: admin={admin_id}, action={action}, "
            f"target={target}, success={success}"
        )
    
    def log_query_execution(self, user_id: str, query_type: str, partition_used: str):
        """Log query executions for monitoring"""
        self.audit_logger.info(
            f"QUERY_EXECUTION: user={user_id}, type={query_type}, "
            f"partition={partition_used}"
        )


class DataSegregationEnforcer:
    """
    Enforces data segregation rules across all data operations.
    Provides decorators and utility functions for access control.
    """
    
    def __init__(self):
        self.validator = PartitionAccessValidator()
        self.audit_logger = SecurityAuditLogger()
    
    def require_document_ownership(self, view_func):
        """
        Decorator to require document ownership for view functions.
        
        Usage:
            @require_document_ownership
            def my_view(request, document_id):
                # View logic here
        """
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Extract document_id from URL parameters or request data
            document_id = kwargs.get('document_id') or request.data.get('document_id')
            
            if not document_id:
                return JsonResponse(
                    {'error': 'Document ID required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            user_id = str(request.user.id)
            
            # Validate ownership
            if not self.validator.validate_document_ownership(user_id, document_id):
                self.audit_logger.log_security_violation(
                    user_id, 
                    'unauthorized_document_access',
                    {'document_id': document_id, 'action': 'access_attempt'}
                )
                return JsonResponse(
                    {'error': 'Access denied: Document not found or not owned by user'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Log successful access
            self.audit_logger.log_document_access(
                user_id, document_id, 'view_access', True
            )
            
            return view_func(request, *args, **kwargs)
        
        return wrapper
    
    def require_partition_access(self, view_func):
        """
        Decorator to require valid partition access for view functions.
        
        Usage:
            @require_partition_access
            def my_view(request):
                # View logic here
        """
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user_id = str(request.user.id)
            partition_name = self.validator.get_user_partition_filter(user_id)
            
            # Validate partition access
            if not self.validator.validate_partition_access(user_id, partition_name):
                self.audit_logger.log_security_violation(
                    user_id,
                    'invalid_partition_access',
                    {'partition_name': partition_name, 'action': 'access_attempt'}
                )
                return JsonResponse(
                    {'error': 'Access denied: Invalid partition access'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Add partition context to request
            request.partition_context = {
                'partition_name': partition_name,
                'user_id': user_id
            }
            
            # Log successful access
            self.audit_logger.log_partition_access(
                user_id, partition_name, 'view_access', True
            )
            
            return view_func(request, *args, **kwargs)
        
        return wrapper
    
    def require_admin_privileges(self, view_func):
        """
        Decorator to require admin privileges for view functions.
        
        Usage:
            @require_admin_privileges
            def admin_view(request):
                # Admin-only logic here
        """
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_staff:
                self.audit_logger.log_security_violation(
                    str(request.user.id),
                    'unauthorized_admin_access',
                    {'action': 'admin_view_attempt', 'view': view_func.__name__}
                )
                return JsonResponse(
                    {'error': 'Admin privileges required'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Log admin action
            self.audit_logger.log_admin_action(
                str(request.user.id), 'view_access', view_func.__name__, True
            )
            
            return view_func(request, *args, **kwargs)
        
        return wrapper


class UserDataFilter:
    """
    Provides filtering utilities to ensure user data segregation in queries.
    """
    
    def __init__(self):
        self.validator = PartitionAccessValidator()
    
    def filter_user_documents(self, user_id: str, queryset=None):
        """
        Filter documents to only include those owned by the user.
        
        Args:
            user_id: UUID string of the user
            queryset: Optional queryset to filter (defaults to all UserDocuments)
            
        Returns:
            Filtered queryset containing only user's documents
        """
        if queryset is None:
            queryset = UserDocument.objects.all()
        
        return queryset.filter(user_id=user_id)
    
    def get_milvus_partition_filter(self, user_id: str) -> str:
        """
        Get Milvus partition name for user data filtering.
        
        Args:
            user_id: UUID string of the user
            
        Returns:
            str: Partition name for Milvus queries
        """
        return self.validator.get_user_partition_filter(user_id)
    
    def validate_query_parameters(self, user_id: str, query_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and sanitize query parameters to prevent data leakage.
        
        Args:
            user_id: UUID string of the requesting user
            query_params: Dictionary of query parameters
            
        Returns:
            Dict: Sanitized query parameters with user filtering applied
        """
        sanitized_params = query_params.copy()
        
        # Ensure user_id filter is always applied
        sanitized_params['user_id'] = user_id
        
        # Remove any attempts to access other users' data
        forbidden_params = ['admin_override', 'all_users', 'system_access']
        for param in forbidden_params:
            if param in sanitized_params:
                logger.warning(f"Removed forbidden parameter '{param}' from query for user {user_id}")
                del sanitized_params[param]
        
        return sanitized_params


class CrossUserAccessPrevention:
    """
    Implements specific checks to prevent cross-user data access.
    """
    
    def __init__(self):
        self.audit_logger = SecurityAuditLogger()
    
    def validate_user_context(self, request_user_id: str, target_user_id: str) -> bool:
        """
        Validate that a user can access data for the target user.
        Only allows access to own data unless user is admin.
        
        Args:
            request_user_id: ID of the user making the request
            target_user_id: ID of the user whose data is being accessed
            
        Returns:
            bool: True if access is allowed, False otherwise
        """
        try:
            # Users can always access their own data
            if request_user_id == target_user_id:
                return True
            
            # Check if requesting user is admin
            requesting_user = User.objects.get(id=request_user_id)
            if requesting_user.is_staff:
                self.audit_logger.log_admin_action(
                    request_user_id, 'cross_user_access', target_user_id, True
                )
                return True
            
            # Deny access for non-admin users
            self.audit_logger.log_security_violation(
                request_user_id,
                'cross_user_access_attempt',
                {'target_user_id': target_user_id}
            )
            return False
            
        except User.DoesNotExist:
            logger.error(f"User validation failed: user {request_user_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error validating user context: {e}")
            return False
    
    def sanitize_response_data(self, user_id: str, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize response data to remove any information that doesn't belong to the user.
        
        Args:
            user_id: UUID string of the requesting user
            response_data: Response data to sanitize
            
        Returns:
            Dict: Sanitized response data
        """
        # This is a placeholder for response sanitization logic
        # In practice, this would remove any data that doesn't belong to the user
        
        sanitized_data = response_data.copy()
        
        # Remove system-level information for non-admin users
        try:
            user = User.objects.get(id=user_id)
            if not user.is_staff:
                system_fields = ['system_stats', 'all_users_data', 'admin_info']
                for field in system_fields:
                    if field in sanitized_data:
                        del sanitized_data[field]
        except User.DoesNotExist:
            pass
        
        return sanitized_data


# Global instances for use across the application
data_segregation_enforcer = DataSegregationEnforcer()
user_data_filter = UserDataFilter()
cross_user_prevention = CrossUserAccessPrevention()
security_audit_logger = SecurityAuditLogger()

# Decorator shortcuts
require_document_ownership = data_segregation_enforcer.require_document_ownership
require_partition_access = data_segregation_enforcer.require_partition_access
require_admin_privileges = data_segregation_enforcer.require_admin_privileges