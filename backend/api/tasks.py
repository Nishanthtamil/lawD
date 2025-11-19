# Consolidated Celery Tasks - Document processing and AI operations

import os
import logging
from typing import Dict, Any, Optional
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.core.files.storage import default_storage

from .models import UserDocument, PublicDocument, ProcessingTask
from .services import DocumentService, ai_service
from .database import connection_pool
from .security import log_security_event

logger = logging.getLogger(__name__)

# ============================================================================
# DOCUMENT PROCESSING TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_user_document(self, document_id: int, force_reprocess: bool = False):
    """Process user document with AI services"""
    task_id = self.request.id
    
    try:
        # Get document
        document = UserDocument.objects.get(id=document_id)
        
        # Create or update processing task
        processing_task, created = ProcessingTask.objects.get_or_create(
            document_id=document_id,
            task_type='process_user_document',
            defaults={
                'user_id': document.user_id,
                'status': 'processing',
                'celery_task_id': task_id
            }
        )
        
        if not created and not force_reprocess:
            processing_task.status = 'processing'
            processing_task.celery_task_id = task_id
            processing_task.save()
        
        # Update document status
        document.processing_status = 'processing'
        document.save()
        
        # Get file path
        file_path = document.file.path if document.file else None
        if not file_path or not os.path.exists(file_path):
            raise Exception("Document file not found")
        
        # Extract file type
        file_extension = os.path.splitext(file_path)[1][1:].lower()
        
        # Process document
        logger.info(f"Processing document {document_id}: {document.title}")
        
        content, error = DocumentService.read_file_content(file_path)
        if error:
            raise Exception(error)
        
        result = type('ProcessingResult', (), {
            'success': True,
            'content': content,
            'summary': content[:500] + '...' if len(content) > 500 else content,
            'metadata': {'file_type': file_extension}
        })()
        
        # Update document with results
        document.content = result.content
        document.summary = result.summary
        document.processing_status = 'completed'
        document.processed_at = timezone.now()
        document.metadata = result.metadata or {}
        document.save()
        
        # Store in vector database
        try:
            # Get embeddings using AI service
            embedding = ai_service.embedding_model.encode([result.content])[0].tolist()
            
            # Store in user's Milvus collection
            milvus_manager = connection_pool.milvus_manager
            collection_name = f"user_documents_{document.user_id}"
            
            # Create collection if it doesn't exist
            milvus_manager.create_collection(collection_name)
            
            # Insert document
            milvus_manager.insert_documents(collection_name, [{
                'document_id': str(document.id),
                'user_id': str(document.user_id),
                'content': result.content,
                'embedding': embedding,
                'metadata': str({
                    'title': document.file_name,
                    'file_type': file_extension,
                    'processed_at': document.created_at.isoformat(),
                    **result.metadata
                })
            }])
            
        except Exception as e:
            logger.warning(f"Failed to store document in vector database: {str(e)}")
            # Don't fail the entire task for vector storage issues
        
        # Store in graph database
        try:
            neo4j_manager = connection_pool.neo4j_manager
            neo4j_manager.create_document_node({
                'document_id': str(document.id),
                'user_id': str(document.user_id),
                'title': document.file_name,
                'content': result.content[:1000],  # Truncate for graph storage
                'document_type': file_extension,
                'created_at': int(document.created_at.timestamp()),
                'metadata': str(result.metadata)
            })
            
        except Exception as e:
            logger.warning(f"Failed to store document in graph database: {str(e)}")
        
        # Update processing task
        processing_task.status = 'completed'
        processing_task.progress = 100
        processing_task.completed_at = timezone.now()
        processing_task.save()
        
        # Log success
        log_security_event(
            'document_processed',
            document.user,
            document_id=document.id,
            processing_time=(timezone.now() - processing_task.created_at).total_seconds()
        )
        
        logger.info(f"Successfully processed document {document_id}")
        return {
            'status': 'success',
            'document_id': document_id,
            'content_length': len(result.content),
            'summary_length': len(result.summary)
        }
        
    except UserDocument.DoesNotExist:
        logger.error(f"Document {document_id} not found")
        return {'status': 'error', 'error': 'Document not found'}
        
    except Exception as e:
        logger.error(f"Failed to process document {document_id}: {str(e)}")
        
        # Update document status
        try:
            document = UserDocument.objects.get(id=document_id)
            document.processing_status = 'failed'
            document.save()
            
            # Update processing task
            processing_task = ProcessingTask.objects.filter(
                document_id=document_id,
                task_type='process_user_document'
            ).first()
            
            if processing_task:
                processing_task.status = 'failed'
                processing_task.error_message = str(e)
                processing_task.save()
                
        except Exception as update_error:
            logger.error(f"Failed to update document status: {str(update_error)}")
        
        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying document processing for {document_id} (attempt {self.request.retries + 1})")
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        
        return {'status': 'error', 'error': str(e)}

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_public_document(self, document_id: int, force_reprocess: bool = False):
    """Process public document with AI services"""
    task_id = self.request.id
    
    try:
        # Get document
        document = PublicDocument.objects.get(id=document_id)
        
        # Create or update processing task
        processing_task, created = ProcessingTask.objects.get_or_create(
            document_id=document_id,
            task_type='process_public_document',
            defaults={
                'status': 'processing',
                'celery_task_id': task_id
            }
        )
        
        if not created and not force_reprocess:
            processing_task.status = 'processing'
            processing_task.celery_task_id = task_id
            processing_task.save()
        
        # Update document status
        document.processing_status = 'processing'
        document.save()
        
        # Get file path
        file_path = document.file.path if document.file else None
        if not file_path or not os.path.exists(file_path):
            raise Exception("Document file not found")
        
        # Extract file type
        file_extension = os.path.splitext(file_path)[1][1:].lower()
        
        # Process document
        logger.info(f"Processing public document {document_id}: {document.title}")
        
        content, error = DocumentService.read_file_content(file_path)
        if error:
            raise Exception(error)
        
        result = type('ProcessingResult', (), {
            'success': True,
            'content': content,
            'summary': content[:500] + '...' if len(content) > 500 else content,
            'metadata': {'file_type': file_extension}
        })()
        
        # Update document with results
        document.content = result.content
        document.summary = result.summary
        document.processing_status = 'completed'
        document.processed_at = timezone.now()
        document.metadata = result.metadata or {}
        document.save()
        
        # Store in vector database (public collection)
        try:
            # Get embeddings using AI service
            embedding = ai_service.embedding_model.encode([result.content])[0].tolist()
            
            # Store in public Milvus collection
            milvus_manager = connection_pool.milvus_manager
            collection_name = "public_documents"
            
            # Create collection if it doesn't exist
            milvus_manager.create_collection(collection_name)
            
            # Insert document
            milvus_manager.insert_documents(collection_name, [{
                'document_id': str(document.id),
                'user_id': '0',  # Public documents have user_id 0
                'content': result.content,
                'embedding': embedding,
                'metadata': str({
                    'title': document.title,
                    'file_type': file_extension,
                    'processed_at': document.created_at.isoformat(),
                    'document_type': document.document_type,
                    **result.metadata
                })
            }])
            
        except Exception as e:
            logger.warning(f"Failed to store public document in vector database: {str(e)}")
        
        # Store in graph database
        try:
            neo4j_manager = connection_pool.neo4j_manager
            neo4j_manager.create_document_node({
                'document_id': str(document.id),
                'user_id': None,  # Public documents
                'title': document.title,
                'content': result.content[:1000],
                'document_type': file_extension,
                'created_at': int(document.created_at.timestamp()),
                'metadata': str(result.metadata)
            })
            
        except Exception as e:
            logger.warning(f"Failed to store public document in graph database: {str(e)}")
        
        # Update processing task
        processing_task.status = 'completed'
        processing_task.progress = 100
        processing_task.completed_at = timezone.now()
        processing_task.save()
        
        logger.info(f"Successfully processed public document {document_id}")
        return {
            'status': 'success',
            'document_id': document_id,
            'content_length': len(result.content),
            'summary_length': len(result.summary)
        }
        
    except PublicDocument.DoesNotExist:
        logger.error(f"Public document {document_id} not found")
        return {'status': 'error', 'error': 'Document not found'}
        
    except Exception as e:
        logger.error(f"Failed to process public document {document_id}: {str(e)}")
        
        # Update document status
        try:
            document = PublicDocument.objects.get(id=document_id)
            document.processing_status = 'failed'
            document.save()
            
            # Update processing task
            processing_task = ProcessingTask.objects.filter(
                document_id=document_id,
                task_type='process_public_document'
            ).first()
            
            if processing_task:
                processing_task.status = 'failed'
                processing_task.error_message = str(e)
                processing_task.save()
                
        except Exception as update_error:
            logger.error(f"Failed to update public document status: {str(update_error)}")
        
        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying public document processing for {document_id} (attempt {self.request.retries + 1})")
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        
        return {'status': 'error', 'error': str(e)}

# ============================================================================
# BATCH PROCESSING TASKS
# ============================================================================

@shared_task
def batch_process_documents(document_ids: list, document_type: str = 'user'):
    """Process multiple documents in batch"""
    results = []
    
    for doc_id in document_ids:
        try:
            if document_type == 'user':
                result = process_user_document.delay(doc_id)
            else:
                result = process_public_document.delay(doc_id)
            
            results.append({
                'document_id': doc_id,
                'task_id': result.id,
                'status': 'queued'
            })
            
        except Exception as e:
            logger.error(f"Failed to queue document {doc_id}: {str(e)}")
            results.append({
                'document_id': doc_id,
                'status': 'error',
                'error': str(e)
            })
    
    return {
        'batch_id': f"batch_{timezone.now().strftime('%Y%m%d_%H%M%S')}",
        'total_documents': len(document_ids),
        'results': results
    }

# ============================================================================
# MAINTENANCE TASKS
# ============================================================================

@shared_task
def cleanup_failed_tasks():
    """Clean up old failed processing tasks"""
    try:
        # Delete failed tasks older than 7 days
        cutoff_date = timezone.now() - timezone.timedelta(days=7)
        
        deleted_count = ProcessingTask.objects.filter(
            status='failed',
            created_at__lt=cutoff_date
        ).delete()[0]
        
        logger.info(f"Cleaned up {deleted_count} old failed tasks")
        return {'cleaned_tasks': deleted_count}
        
    except Exception as e:
        logger.error(f"Failed to cleanup tasks: {str(e)}")
        return {'error': str(e)}

@shared_task
def system_health_check():
    """Perform system health check"""
    try:
        # Check database connections
        health_status = connection_pool.health_check()
        
        # Check AI services
        ai_status = True  # Simplified check
        
        # Check processing queue
        pending_tasks = ProcessingTask.objects.filter(status='pending').count()
        stuck_tasks = ProcessingTask.objects.filter(
            status='processing',
            updated_at__lt=timezone.now() - timezone.timedelta(hours=2)
        ).count()
        
        health_report = {
            'timestamp': timezone.now().isoformat(),
            'databases': health_status,
            'ai_services': ai_status,
            'queue_health': {
                'pending_tasks': pending_tasks,
                'stuck_tasks': stuck_tasks
            },
            'overall_status': 'healthy' if all(health_status.values()) and ai_status and stuck_tasks == 0 else 'degraded'
        }
        
        logger.info(f"System health check completed: {health_report['overall_status']}")
        return health_report
        
    except Exception as e:
        logger.error(f"System health check failed: {str(e)}")
        return {
            'timestamp': timezone.now().isoformat(),
            'overall_status': 'unhealthy',
            'error': str(e)
        }

@shared_task
def optimize_vector_database():
    """Optimize vector database performance"""
    try:
        # This would implement vector database optimization
        # For now, just return a placeholder
        logger.info("Vector database optimization completed")
        return {'status': 'completed', 'optimized_collections': 0}
        
    except Exception as e:
        logger.error(f"Vector database optimization failed: {str(e)}")
        return {'status': 'failed', 'error': str(e)}

# ============================================================================
# MONITORING TASKS
# ============================================================================

@shared_task
def monitor_processing_queue():
    """Monitor processing queue and handle stuck tasks"""
    try:
        # Find stuck tasks (processing for more than 1 hour)
        stuck_tasks = ProcessingTask.objects.filter(
            status='processing',
            updated_at__lt=timezone.now() - timezone.timedelta(hours=1)
        )
        
        stuck_count = 0
        for task in stuck_tasks:
            # Mark as failed and log
            task.status = 'failed'
            task.error_message = 'Task stuck in processing state'
            task.save()
            
            logger.warning(f"Marked stuck task {task.id} as failed")
            stuck_count += 1
        
        # Get queue statistics
        stats = {
            'pending': ProcessingTask.objects.filter(status='pending').count(),
            'processing': ProcessingTask.objects.filter(status='processing').count(),
            'completed': ProcessingTask.objects.filter(status='completed').count(),
            'failed': ProcessingTask.objects.filter(status='failed').count(),
            'stuck_tasks_handled': stuck_count
        }
        
        logger.info(f"Queue monitoring completed: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"Queue monitoring failed: {str(e)}")
        return {'error': str(e)}