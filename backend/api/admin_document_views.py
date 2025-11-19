"""
Admin document upload and management API views.
Provides endpoints for admin-controlled public document management.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework import status
import json
import os
import uuid
from datetime import timedelta

from .models import PublicDocument, ProcessingTask, User
from .tasks import process_public_document
from .security import validate_file_upload, sanitize_filename


class PublicDocumentSerializer:
    """Serializer for PublicDocument model"""
    
    @staticmethod
    def serialize(document, include_content=False):
        """Serialize a PublicDocument instance"""
        data = {
            'id': str(document.id),
            'title': document.title,
            'document_type': document.document_type,
            'legal_domain': document.legal_domain,
            'jurisdiction': document.jurisdiction,
            'effective_date': document.effective_date.isoformat() if document.effective_date else None,
            'processing_status': document.processing_status,
            'uploaded_by': {
                'id': str(document.uploaded_by.id),
                'phone_number': document.uploaded_by.phone_number,
                'name': document.uploaded_by.name
            },
            'file_info': {
                'name': os.path.basename(document.file_path.name) if document.file_path else None,
                'size': document.file_path.size if document.file_path else None,
                'url': document.file_path.url if document.file_path else None
            },
            'processing_metrics': {
                'entities_extracted': len(document.entities_extracted) if document.entities_extracted else 0,
                'relationships_count': document.relationships_count,
                'embeddings_count': document.embeddings_count
            },
            'timestamps': {
                'created_at': document.created_at.isoformat(),
                'processed_at': document.processed_at.isoformat() if document.processed_at else None
            }
        }
        
        if include_content and document.entities_extracted:
            data['entities_extracted'] = document.entities_extracted
            
        return data


class ProcessingTaskSerializer:
    """Serializer for ProcessingTask model"""
    
    @staticmethod
    def serialize(task):
        """Serialize a ProcessingTask instance"""
        return {
            'id': str(task.id),
            'task_id': task.task_id,
            'task_type': task.task_type,
            'status': task.status,
            'progress_percentage': task.progress_percentage,
            'error_message': task.error_message,
            'processing_time_seconds': task.processing_time_seconds,
            'metrics': {
                'entities_extracted': task.entities_extracted,
                'embeddings_created': task.embeddings_created
            },
            'document_info': {
                'id': str(task.public_document.id) if task.public_document else None,
                'title': task.public_document.title if task.public_document else None,
                'type': task.public_document.document_type if task.public_document else None
            },
            'user': {
                'id': str(task.user.id),
                'phone_number': task.user.phone_number
            },
            'timestamps': {
                'created_at': task.created_at.isoformat(),
                'started_at': task.started_at.isoformat() if task.started_at else None,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None
            }
        }


@api_view(['POST'])
@permission_classes([IsAdminUser])
def upload_public_document(request):
    """
    Upload a new public document for processing.
    Admin-only endpoint that validates file and queues processing task.
    """
    try:
        # Validate required fields
        if 'file' not in request.FILES:
            return Response({
                'error': 'No file provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        file = request.FILES['file']
        title = request.data.get('title', '').strip()
        document_type = request.data.get('document_type', '').strip()
        legal_domain = request.data.get('legal_domain', '').strip()
        jurisdiction = request.data.get('jurisdiction', 'India').strip()
        effective_date = request.data.get('effective_date')
        
        # Validate required fields
        if not title:
            return Response({
                'error': 'Document title is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not document_type:
            return Response({
                'error': 'Document type is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate document type
        valid_types = [choice[0] for choice in PublicDocument.DOCUMENT_TYPE_CHOICES]
        if document_type not in valid_types:
            return Response({
                'error': f'Invalid document type. Must be one of: {", ".join(valid_types)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate legal domain if provided
        if legal_domain:
            valid_domains = [choice[0] for choice in PublicDocument.LEGAL_DOMAIN_CHOICES]
            if legal_domain not in valid_domains:
                return Response({
                    'error': f'Invalid legal domain. Must be one of: {", ".join(valid_domains)}'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate file
        validation_result = validate_file_upload(file)
        if not validation_result['valid']:
            return Response({
                'error': validation_result['error']
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Sanitize filename
        sanitized_filename = sanitize_filename(file.name)
        
        # Parse effective date if provided
        parsed_date = None
        if effective_date:
            try:
                from datetime import datetime
                parsed_date = datetime.strptime(effective_date, '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'error': 'Invalid date format. Use YYYY-MM-DD'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create PublicDocument record
        document = PublicDocument.objects.create(
            title=title,
            document_type=document_type,
            legal_domain=legal_domain or '',
            jurisdiction=jurisdiction,
            effective_date=parsed_date,
            uploaded_by=request.user,
            file_path=file,
            processing_status='pending'
        )
        
        # Queue processing task
        task_result = process_public_document.delay(
            str(document.id),
            str(request.user.id)
        )
        
        # Create ProcessingTask record
        processing_task = ProcessingTask.objects.create(
            task_id=task_result.id,
            task_type='public_document',
            public_document=document,
            user=request.user,
            status='queued'
        )
        
        return Response({
            'status': 'success',
            'message': 'Document uploaded successfully and queued for processing',
            'document': PublicDocumentSerializer.serialize(document),
            'task': ProcessingTaskSerializer.serialize(processing_task)
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        return Response({
            'error': f'Error uploading document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def list_public_documents(request):
    """
    List all public documents with filtering and pagination.
    Admin-only endpoint for document management.
    """
    try:
        # Get query parameters
        page = int(request.GET.get('page', 1))
        page_size = min(int(request.GET.get('page_size', 20)), 100)  # Max 100 per page
        
        # Filtering parameters
        document_type = request.GET.get('document_type')
        legal_domain = request.GET.get('legal_domain')
        processing_status = request.GET.get('processing_status')
        search = request.GET.get('search', '').strip()
        uploaded_by = request.GET.get('uploaded_by')
        
        # Build queryset
        queryset = PublicDocument.objects.select_related('uploaded_by').all()
        
        # Apply filters
        if document_type:
            queryset = queryset.filter(document_type=document_type)
        
        if legal_domain:
            queryset = queryset.filter(legal_domain=legal_domain)
        
        if processing_status:
            queryset = queryset.filter(processing_status=processing_status)
        
        if uploaded_by:
            queryset = queryset.filter(uploaded_by__id=uploaded_by)
        
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(jurisdiction__icontains=search)
            )
        
        # Order by creation date (newest first)
        queryset = queryset.order_by('-created_at')
        
        # Paginate
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)
        
        # Serialize documents
        documents = [
            PublicDocumentSerializer.serialize(doc) 
            for doc in page_obj.object_list
        ]
        
        # Get summary statistics
        total_stats = PublicDocument.objects.aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(processing_status='pending')),
            processing=Count('id', filter=Q(processing_status='processing')),
            completed=Count('id', filter=Q(processing_status='completed')),
            failed=Count('id', filter=Q(processing_status='failed'))
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
            'statistics': total_stats,
            'filters': {
                'document_types': [choice[0] for choice in PublicDocument.DOCUMENT_TYPE_CHOICES],
                'legal_domains': [choice[0] for choice in PublicDocument.LEGAL_DOMAIN_CHOICES],
                'processing_statuses': [choice[0] for choice in PublicDocument.STATUS_CHOICES]
            }
        })
        
    except Exception as e:
        return Response({
            'error': f'Error listing documents: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_public_document(request, document_id):
    """
    Get detailed information about a specific public document.
    Admin-only endpoint with full document details.
    """
    try:
        document = PublicDocument.objects.select_related('uploaded_by').get(id=document_id)
        
        # Get related processing tasks
        processing_tasks = ProcessingTask.objects.filter(
            public_document=document
        ).order_by('-created_at')
        
        # Serialize document with full content
        document_data = PublicDocumentSerializer.serialize(document, include_content=True)
        
        # Add processing task history
        document_data['processing_history'] = [
            ProcessingTaskSerializer.serialize(task) 
            for task in processing_tasks
        ]
        
        return Response(document_data)
        
    except PublicDocument.DoesNotExist:
        return Response({
            'error': 'Document not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Error retrieving document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT'])
@permission_classes([IsAdminUser])
def update_public_document(request, document_id):
    """
    Update public document metadata.
    Admin-only endpoint for document management.
    """
    try:
        document = PublicDocument.objects.get(id=document_id)
        
        # Update allowed fields
        if 'title' in request.data:
            document.title = request.data['title'].strip()
        
        if 'document_type' in request.data:
            document_type = request.data['document_type']
            valid_types = [choice[0] for choice in PublicDocument.DOCUMENT_TYPE_CHOICES]
            if document_type not in valid_types:
                return Response({
                    'error': f'Invalid document type. Must be one of: {", ".join(valid_types)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            document.document_type = document_type
        
        if 'legal_domain' in request.data:
            legal_domain = request.data['legal_domain']
            if legal_domain:
                valid_domains = [choice[0] for choice in PublicDocument.LEGAL_DOMAIN_CHOICES]
                if legal_domain not in valid_domains:
                    return Response({
                        'error': f'Invalid legal domain. Must be one of: {", ".join(valid_domains)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            document.legal_domain = legal_domain
        
        if 'jurisdiction' in request.data:
            document.jurisdiction = request.data['jurisdiction'].strip()
        
        if 'effective_date' in request.data:
            effective_date = request.data['effective_date']
            if effective_date:
                try:
                    from datetime import datetime
                    document.effective_date = datetime.strptime(effective_date, '%Y-%m-%d').date()
                except ValueError:
                    return Response({
                        'error': 'Invalid date format. Use YYYY-MM-DD'
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                document.effective_date = None
        
        document.save()
        
        return Response({
            'status': 'success',
            'message': 'Document updated successfully',
            'document': PublicDocumentSerializer.serialize(document)
        })
        
    except PublicDocument.DoesNotExist:
        return Response({
            'error': 'Document not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Error updating document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_public_document(request, document_id):
    """
    Delete a public document and its associated data.
    Admin-only endpoint with cascade cleanup.
    """
    try:
        document = PublicDocument.objects.get(id=document_id)
        
        # Check if document is currently being processed
        active_tasks = ProcessingTask.objects.filter(
            public_document=document,
            status__in=['queued', 'processing']
        )
        
        if active_tasks.exists():
            return Response({
                'error': 'Cannot delete document with active processing tasks. Please wait for completion or cancel tasks first.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Store document info for response
        document_info = {
            'id': str(document.id),
            'title': document.title,
            'document_type': document.document_type
        }
        
        # Delete file from storage
        if document.file_path:
            try:
                default_storage.delete(document.file_path.name)
            except Exception as e:
                # Log but don't fail the deletion
                print(f"Warning: Could not delete file {document.file_path.name}: {e}")
        
        # Delete document (will cascade to processing tasks)
        document.delete()
        
        return Response({
            'status': 'success',
            'message': 'Document deleted successfully',
            'deleted_document': document_info
        })
        
    except PublicDocument.DoesNotExist:
        return Response({
            'error': 'Document not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Error deleting document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def reprocess_public_document(request, document_id):
    """
    Reprocess a public document.
    Admin-only endpoint to retry document processing.
    """
    try:
        document = PublicDocument.objects.get(id=document_id)
        
        # Check if document is currently being processed
        active_tasks = ProcessingTask.objects.filter(
            public_document=document,
            status__in=['queued', 'processing']
        )
        
        if active_tasks.exists():
            return Response({
                'error': 'Document is already being processed'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Reset document status
        document.processing_status = 'pending'
        document.entities_extracted = {}
        document.relationships_count = 0
        document.embeddings_count = 0
        document.processed_at = None
        document.save()
        
        # Queue new processing task
        task_result = process_public_document.delay(
            str(document.id),
            str(request.user.id)
        )
        
        # Create ProcessingTask record
        processing_task = ProcessingTask.objects.create(
            task_id=task_result.id,
            task_type='public_document',
            public_document=document,
            user=request.user,
            status='queued'
        )
        
        return Response({
            'status': 'success',
            'message': 'Document queued for reprocessing',
            'document': PublicDocumentSerializer.serialize(document),
            'task': ProcessingTaskSerializer.serialize(processing_task)
        })
        
    except PublicDocument.DoesNotExist:
        return Response({
            'error': 'Document not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Error reprocessing document: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_processing_queue(request):
    """
    Get current processing queue status for admin monitoring.
    Shows all active tasks and queue statistics.
    """
    try:
        # Get queue statistics
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        
        queue_stats = ProcessingTask.objects.filter(
            created_at__gte=last_24h
        ).aggregate(
            total=Count('id'),
            queued=Count('id', filter=Q(status='queued')),
            processing=Count('id', filter=Q(status='processing')),
            completed=Count('id', filter=Q(status='completed')),
            failed=Count('id', filter=Q(status='failed'))
        )
        
        # Get active tasks (queued or processing)
        active_tasks = ProcessingTask.objects.filter(
            status__in=['queued', 'processing']
        ).select_related('public_document', 'user_document', 'user').order_by('created_at')
        
        # Get recent completed/failed tasks
        recent_tasks = ProcessingTask.objects.filter(
            status__in=['completed', 'failed'],
            completed_at__gte=last_24h
        ).select_related('public_document', 'user_document', 'user').order_by('-completed_at')[:20]
        
        # Serialize tasks
        active_tasks_data = [ProcessingTaskSerializer.serialize(task) for task in active_tasks]
        recent_tasks_data = [ProcessingTaskSerializer.serialize(task) for task in recent_tasks]
        
        # Get pending documents
        pending_public = PublicDocument.objects.filter(processing_status='pending').count()
        
        return Response({
            'queue_statistics': queue_stats,
            'active_tasks': active_tasks_data,
            'recent_tasks': recent_tasks_data,
            'pending_documents': {
                'public_documents': pending_public
            },
            'timestamp': now.isoformat()
        })
        
    except Exception as e:
        return Response({
            'error': f'Error retrieving queue status: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)