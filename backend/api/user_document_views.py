"""
Enhanced user document upload and processing API views.
Provides endpoints for user document management with partition integration.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import json
import os
import uuid
from datetime import timedelta

from .models import UserDocument, ProcessingTask, UserPartition, User
from .serializers import UserDocumentSerializer
from .tasks import process_personal_document
from .security_validators import (
    validate_file_upload, 
    sanitize_filename,
    comprehensive_security_validator,
    rate_limit_validator
)
from .milvus_manager import PartitionManager


class UserDocumentSerializer:
    """Enhanced serializer for UserDocument model with processing info"""
    
    @staticmethod
    def serialize(document, include_processing_info=False):
        """Serialize a UserDocument instance"""
        data = {
            'id': str(document.id),
            'file_name': document.file_name,
            'file_type': document.file_type,
            'file_size': document.file_size,
            'summary_type': document.summary_type,
            'summary': document.summary,
            'status': document.status,
            'file_info': {
                'name': os.path.basename(document.file_path.name) if document.file_path else None,
                'size': document.file_size,
                'url': document.file_path.url if document.file_path else None
            },
            'timestamps': {
                'created_at': document.created_at.isoformat(),
                'updated_at': document.updated_at.isoformat()
            }
        }
        
        if include_processing_info:
            # Get latest processing task
            latest_task = ProcessingTask.objects.filter(
                user_document=document
            ).order_by('-created_at').first()
            
            if latest_task:
                data['processing_info'] = {
                    'task_id': latest_task.task_id,
                    'status': latest_task.status,
                    'progress_percentage': latest_task.progress_percentage,
                    'error_message': latest_task.error_message,
                    'processing_time_seconds': latest_task.processing_time_seconds,
                    'metrics': {
                        'embeddings_created': latest_task.embeddings_created
                    },
                    'started_at': latest_task.started_at.isoformat() if latest_task.started_at else None,
                    'completed_at': latest_task.completed_at.isoformat() if latest_task.completed_at else None
                }
            
        return data


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_user_document(request):
    """
    Upload a personal document for processing.
    Enhanced version with partition management and validation.
    """
    try:
        # Validate user request
        user_valid, user_error = comprehensive_security_validator.validate_user_request(request.user)
        if not user_valid:
            return Response({
                'error': user_error
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Check rate limits
        rate_valid, rate_error = rate_limit_validator.validate_document_upload_rate(str(request.user.id))
        if not rate_valid:
            return Response({
                'error': rate_error
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Validate required fields
        if 'file' not in request.FILES:
            return Response({
                'error': 'No file provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        file = request.FILES['file']
        summary_type = request.data.get('summary_type', 'comprehensive').strip()
        
        # Validate file
        validation_result = validate_file_upload(file)
        if not validation_result['valid']:
            return Response({
                'error': validation_result['error']
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate summary type
        valid_summary_types = ['brief', 'comprehensive', 'legal_issues', 'clause_by_clause']
        if summary_type and summary_type not in valid_summary_types:
            return Response({
                'error': f'Invalid summary type. Must be one of: {", ".join(valid_summary_types)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Sanitize filename
        sanitized_filename = sanitize_filename(file.name)
        
        # Create UserDocument record
        document = UserDocument.objects.create(
            user=request.user,
            file_name=sanitized_filename,
            file_path=file,
            file_size=file.size,
            file_type=os.path.splitext(sanitized_filename)[1].replace('.', ''),
            summary_type=summary_type or 'comprehensive',
            status='pending'
        )
        
        # Queue processing task
        task_result = process_personal_document.delay(
            str(document.id),
            str(request.user.id)
        )
        
        # Create ProcessingTask record
        processing_task = ProcessingTask.objects.create(
            task_id=task_result.id,
            task_type='personal_document',
            user_document=document,
            user=request.user,
            status='queued'
        )
        
        return Response({
            'status': 'success',
            'message': 'Document uploaded successfully and queued for processing',
            'document': UserDocumentSerializer.serialize(document, include_processing_info=True),
            'task_id': task_result.id
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        return Response({
            'error': f'Error uploading document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_user_documents(request):
    """
    List all documents for the current user with filtering and pagination.
    Enhanced version with processing status and partition info.
    """
    try:
        # Validate user request
        user_valid, user_error = comprehensive_security_validator.validate_user_request(request.user)
        if not user_valid:
            return Response({
                'error': user_error
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get query parameters
        page = int(request.GET.get('page', 1))
        page_size = min(int(request.GET.get('page_size', 20)), 50)  # Max 50 per page
        
        # Filtering parameters
        status_filter = request.GET.get('status')
        file_type = request.GET.get('file_type')
        search = request.GET.get('search', '').strip()
        
        # Build queryset
        queryset = UserDocument.objects.filter(user=request.user)
        
        # Apply filters
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if file_type:
            queryset = queryset.filter(file_type=file_type)
        
        if search:
            queryset = queryset.filter(
                Q(file_name__icontains=search) |
                Q(summary__icontains=search)
            )
        
        # Order by creation date (newest first)
        queryset = queryset.order_by('-created_at')
        
        # Paginate
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)
        
        # Serialize documents
        documents = [
            UserDocumentSerializer.serialize(doc, include_processing_info=True) 
            for doc in page_obj.object_list
        ]
        
        # Get user partition info
        partition_info = None
        try:
            user_partition = UserPartition.objects.get(user=request.user)
            partition_info = {
                'partition_name': user_partition.partition_name,
                'document_count': user_partition.document_count,
                'total_embeddings': user_partition.total_embeddings,
                'last_accessed': user_partition.last_accessed.isoformat()
            }
        except UserPartition.DoesNotExist:
            pass
        
        # Get summary statistics
        total_stats = UserDocument.objects.filter(user=request.user).aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(status='pending')),
            processing=Count('id', filter=Q(status='processing')),
            completed=Count('id', filter=Q(status='completed')),
            failed=Count('id', filter=Q(status='failed'))
        )
        
        return Response({
            'documents': documents,
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_documents': paginator.count,
                'page_size': page_size,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous()
            },
            'partition_info': partition_info,
            'statistics': total_stats,
            'filters': {
                'statuses': ['pending', 'processing', 'completed', 'failed'],
                'file_types': ['pdf', 'docx', 'doc', 'txt']
            }
        })
        
    except Exception as e:
        return Response({
            'error': f'Error listing documents: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_document(request, document_id):
    """
    Get detailed information about a specific user document.
    Enhanced version with processing history and partition info.
    """
    try:
        # Validate document request
        doc_valid, doc_error, document = comprehensive_security_validator.validate_document_request(
            request.user, document_id
        )
        if not doc_valid:
            return Response({
                'error': doc_error
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get processing task history
        processing_tasks = ProcessingTask.objects.filter(
            user_document=document
        ).order_by('-created_at')
        
        # Serialize document with full details
        document_data = UserDocumentSerializer.serialize(document, include_processing_info=True)
        
        # Add processing history
        document_data['processing_history'] = []
        for task in processing_tasks:
            task_data = {
                'task_id': task.task_id,
                'status': task.status,
                'progress_percentage': task.progress_percentage,
                'error_message': task.error_message,
                'processing_time_seconds': task.processing_time_seconds,
                'metrics': {
                    'embeddings_created': task.embeddings_created
                },
                'timestamps': {
                    'created_at': task.created_at.isoformat(),
                    'started_at': task.started_at.isoformat() if task.started_at else None,
                    'completed_at': task.completed_at.isoformat() if task.completed_at else None
                }
            }
            document_data['processing_history'].append(task_data)
        
        return Response(document_data)
        
    except Exception as e:
        return Response({
            'error': f'Error retrieving document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_user_document(request, document_id):
    """
    Update user document metadata (filename, summary_type).
    """
    try:
        # Validate document request
        doc_valid, doc_error, document = comprehensive_security_validator.validate_document_request(
            request.user, document_id
        )
        if not doc_valid:
            return Response({
                'error': doc_error
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if document is being processed
        if document.status == 'processing':
            return Response({
                'error': 'Cannot update document while it is being processed'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update allowed fields
        if 'file_name' in request.data:
            new_filename = request.data['file_name'].strip()
            if new_filename:
                document.file_name = sanitize_filename(new_filename)
        
        if 'summary_type' in request.data:
            summary_type = request.data['summary_type'].strip()
            valid_summary_types = ['brief', 'comprehensive', 'legal_issues', 'clause_by_clause']
            if summary_type in valid_summary_types:
                document.summary_type = summary_type
            else:
                return Response({
                    'error': f'Invalid summary type. Must be one of: {", ".join(valid_summary_types)}'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        document.save()
        
        return Response({
            'status': 'success',
            'message': 'Document updated successfully',
            'document': UserDocumentSerializer.serialize(document, include_processing_info=True)
        })
        
    except Exception as e:
        return Response({
            'error': f'Error updating document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_user_document(request, document_id):
    """
    Delete a user document and its associated data.
    Enhanced version with partition cleanup.
    """
    try:
        # Validate document request
        doc_valid, doc_error, document = comprehensive_security_validator.validate_document_request(
            request.user, document_id
        )
        if not doc_valid:
            return Response({
                'error': doc_error
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if document is currently being processed
        active_tasks = ProcessingTask.objects.filter(
            user_document=document,
            status__in=['queued', 'processing']
        )
        
        if active_tasks.exists():
            return Response({
                'error': 'Cannot delete document with active processing tasks. Please wait for completion.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Store document info for response
        document_info = {
            'id': str(document.id),
            'file_name': document.file_name,
            'file_type': document.file_type
        }
        
        # Delete file from storage
        if document.file_path:
            try:
                default_storage.delete(document.file_path.name)
            except Exception as e:
                # Log but don't fail the deletion
                print(f"Warning: Could not delete file {document.file_path.name}: {e}")
        
        # TODO: Remove document embeddings from user partition
        # This would be implemented when Milvus integration is complete
        
        # Delete document (will cascade to processing tasks)
        document.delete()
        
        # Update user partition document count
        try:
            user_partition = UserPartition.objects.get(user=request.user)
            user_partition.document_count = max(0, user_partition.document_count - 1)
            user_partition.save()
        except UserPartition.DoesNotExist:
            pass
        
        return Response({
            'status': 'success',
            'message': 'Document deleted successfully',
            'deleted_document': document_info
        })
        
    except Exception as e:
        return Response({
            'error': f'Error deleting document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reprocess_user_document(request, document_id):
    """
    Reprocess a user document.
    Queues the document for processing again.
    """
    try:
        # Validate document request
        doc_valid, doc_error, document = comprehensive_security_validator.validate_document_request(
            request.user, document_id
        )
        if not doc_valid:
            return Response({
                'error': doc_error
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if document is currently being processed
        active_tasks = ProcessingTask.objects.filter(
            user_document=document,
            status__in=['queued', 'processing']
        )
        
        if active_tasks.exists():
            return Response({
                'error': 'Document is already being processed'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check rate limits
        rate_valid, rate_error = rate_limit_validator.validate_document_upload_rate(str(request.user.id))
        if not rate_valid:
            return Response({
                'error': f'Rate limit exceeded for reprocessing: {rate_error}'
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Reset document status
        document.status = 'pending'
        document.summary = ''
        document.save()
        
        # Queue new processing task
        task_result = process_personal_document.delay(
            str(document.id),
            str(request.user.id)
        )
        
        # Create ProcessingTask record
        processing_task = ProcessingTask.objects.create(
            task_id=task_result.id,
            task_type='personal_document',
            user_document=document,
            user=request.user,
            status='queued'
        )
        
        return Response({
            'status': 'success',
            'message': 'Document queued for reprocessing',
            'document': UserDocumentSerializer.serialize(document, include_processing_info=True),
            'task_id': task_result.id
        })
        
    except Exception as e:
        return Response({
            'error': f'Error reprocessing document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_user_document(request, document_id):
    """
    Download original document file.
    Enhanced version with access validation.
    """
    try:
        # Validate document request
        doc_valid, doc_error, document = comprehensive_security_validator.validate_document_request(
            request.user, document_id
        )
        if not doc_valid:
            return Response({
                'error': doc_error
            }, status=status.HTTP_404_NOT_FOUND)
        
        if not document.file_path:
            return Response({
                'error': 'File not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Validate file exists
        if not document.file_path.storage.exists(document.file_path.name):
            return Response({
                'error': 'File not found in storage'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Return file URL for download
        return Response({
            'file_url': request.build_absolute_uri(document.file_path.url),
            'file_name': document.file_name,
            'file_size': document.file_size,
            'file_type': document.file_type
        })
        
    except Exception as e:
        return Response({
            'error': f'Error downloading document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_partition_info(request):
    """
    Get user's partition information and statistics.
    """
    try:
        # Validate user request
        user_valid, user_error = comprehensive_security_validator.validate_user_request(request.user)
        if not user_valid:
            return Response({
                'error': user_error
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get or create user partition
        user_partition, created = UserPartition.objects.get_or_create(
            user=request.user,
            defaults={
                'partition_name': f"user_{request.user.id.hex}",
                'document_count': 0,
                'total_embeddings': 0
            }
        )
        
        # Get document statistics
        doc_stats = UserDocument.objects.filter(user=request.user).aggregate(
            total_documents=Count('id'),
            completed_documents=Count('id', filter=Q(status='completed')),
            processing_documents=Count('id', filter=Q(status__in=['pending', 'processing'])),
            failed_documents=Count('id', filter=Q(status='failed'))
        )
        
        # Get recent processing activity
        recent_tasks = ProcessingTask.objects.filter(
            user=request.user,
            task_type='personal_document'
        ).order_by('-created_at')[:5]
        
        recent_activity = []
        for task in recent_tasks:
            activity = {
                'task_id': task.task_id,
                'status': task.status,
                'document_name': task.user_document.file_name if task.user_document else 'Unknown',
                'created_at': task.created_at.isoformat(),
                'completed_at': task.completed_at.isoformat() if task.completed_at else None
            }
            recent_activity.append(activity)
        
        partition_data = {
            'partition_info': {
                'partition_name': user_partition.partition_name,
                'document_count': user_partition.document_count,
                'total_embeddings': user_partition.total_embeddings,
                'created_at': user_partition.created_at.isoformat(),
                'last_accessed': user_partition.last_accessed.isoformat()
            },
            'document_statistics': doc_stats,
            'recent_activity': recent_activity,
            'storage_info': {
                'max_documents': 1000,  # Example limit
                'max_storage_mb': 500,  # Example limit
                'current_storage_mb': sum([
                    doc.file_size for doc in UserDocument.objects.filter(user=request.user)
                ]) / (1024 * 1024)
            }
        }
        
        return Response(partition_data)
        
    except Exception as e:
        return Response({
            'error': f'Error retrieving partition info: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_user_partition(request):
    """
    Manually create or initialize user partition.
    Usually called automatically, but available for manual initialization.
    """
    try:
        # Validate user request
        user_valid, user_error = comprehensive_security_validator.validate_user_request(request.user)
        if not user_valid:
            return Response({
                'error': user_error
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Check if partition already exists
        existing_partition = UserPartition.objects.filter(user=request.user).first()
        if existing_partition:
            return Response({
                'status': 'success',
                'message': 'Partition already exists',
                'partition': {
                    'partition_name': existing_partition.partition_name,
                    'document_count': existing_partition.document_count,
                    'total_embeddings': existing_partition.total_embeddings,
                    'created_at': existing_partition.created_at.isoformat()
                }
            })
        
        # Create new partition
        partition_name = f"user_{request.user.id.hex}"
        
        # Create partition in Milvus (when integration is complete)
        # partition_manager = PartitionManager()
        # partition_created = partition_manager.create_user_partition(str(request.user.id))
        
        # Create database record
        user_partition = UserPartition.objects.create(
            user=request.user,
            partition_name=partition_name,
            document_count=0,
            total_embeddings=0
        )
        
        return Response({
            'status': 'success',
            'message': 'Partition created successfully',
            'partition': {
                'partition_name': user_partition.partition_name,
                'document_count': user_partition.document_count,
                'total_embeddings': user_partition.total_embeddings,
                'created_at': user_partition.created_at.isoformat()
            }
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        return Response({
            'error': f'Error creating partition: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)