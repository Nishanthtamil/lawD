"""
API views for task monitoring and management system.
Provides real-time status updates and progress reporting for processing tasks.
"""

from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Avg, Q
from django.core.cache import cache
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from datetime import timedelta
import json

from .models import ProcessingTask, PublicDocument, UserDocument, UserPartition
from .tasks import monitor_processing_queue


@staff_member_required
@require_http_methods(["GET"])
def task_monitoring_dashboard(request):
    """
    API endpoint for admin task monitoring dashboard.
    Returns comprehensive system statistics and health metrics.
    """
    try:
        # Check cache first
        cache_key = 'task_monitoring_dashboard'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            return JsonResponse(cached_data)
        
        # Calculate time windows
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        last_1h = now - timedelta(hours=1)
        
        # Task statistics for last 24 hours
        recent_tasks = ProcessingTask.objects.filter(created_at__gte=last_24h)
        
        task_stats = {
            'total_24h': recent_tasks.count(),
            'queued': recent_tasks.filter(status='queued').count(),
            'processing': recent_tasks.filter(status='processing').count(),
            'completed': recent_tasks.filter(status='completed').count(),
            'failed': recent_tasks.filter(status='failed').count(),
            'cancelled': recent_tasks.filter(status='cancelled').count(),
        }
        
        # Task breakdown by type
        task_types = recent_tasks.values('task_type').annotate(
            count=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            failed=Count('id', filter=Q(status='failed'))
        ).order_by('task_type')
        
        # Performance metrics
        completed_tasks = ProcessingTask.objects.filter(
            status='completed',
            processing_time_seconds__isnull=False,
            completed_at__gte=last_7d
        )
        
        avg_times = completed_tasks.aggregate(
            overall=Avg('processing_time_seconds'),
            public_doc=Avg('processing_time_seconds', filter=Q(task_type='public_document')),
            personal_doc=Avg('processing_time_seconds', filter=Q(task_type='personal_document'))
        )
        
        # System health indicators
        stuck_threshold = now - timedelta(hours=1)
        stuck_tasks = ProcessingTask.objects.filter(
            status='processing',
            started_at__lt=stuck_threshold
        )
        
        orphaned_threshold = now - timedelta(hours=24)
        orphaned_tasks = ProcessingTask.objects.filter(
            status='queued',
            created_at__lt=orphaned_threshold
        )
        
        # Document queue status
        pending_docs = {
            'public_documents': PublicDocument.objects.filter(processing_status='pending').count(),
            'personal_documents': UserDocument.objects.filter(status='pending').count()
        }
        
        # Recent activity (last hour)
        recent_activity = ProcessingTask.objects.filter(
            created_at__gte=last_1h
        ).values('task_type', 'status').annotate(count=Count('id'))
        
        # Success rate calculation
        success_rate = 0
        if task_stats['total_24h'] > 0:
            success_rate = (task_stats['completed'] / task_stats['total_24h']) * 100
        
        # Generate alerts
        alerts = []
        
        if stuck_tasks.count() > 0:
            alerts.append({
                'level': 'error',
                'message': f"{stuck_tasks.count()} tasks stuck in processing (>1 hour)",
                'count': stuck_tasks.count()
            })
        
        if orphaned_tasks.count() > 0:
            alerts.append({
                'level': 'warning',
                'message': f"{orphaned_tasks.count()} orphaned tasks in queue (>24 hours)",
                'count': orphaned_tasks.count()
            })
        
        if success_rate < 90 and task_stats['total_24h'] > 10:
            alerts.append({
                'level': 'warning',
                'message': f"Low success rate: {success_rate:.1f}%",
                'value': success_rate
            })
        
        if task_stats['failed'] > task_stats['completed'] * 0.15:
            alerts.append({
                'level': 'error',
                'message': f"High failure rate: {task_stats['failed']} failed vs {task_stats['completed']} completed",
                'failed_count': task_stats['failed'],
                'completed_count': task_stats['completed']
            })
        
        # Compile response data
        dashboard_data = {
            'timestamp': now.isoformat(),
            'task_statistics': task_stats,
            'task_types': list(task_types),
            'performance_metrics': {
                'success_rate': round(success_rate, 1),
                'avg_processing_times': {
                    'overall': round(avg_times['overall'] or 0, 1),
                    'public_document': round(avg_times['public_doc'] or 0, 1),
                    'personal_document': round(avg_times['personal_doc'] or 0, 1)
                }
            },
            'system_health': {
                'stuck_tasks': stuck_tasks.count(),
                'orphaned_tasks': orphaned_tasks.count(),
                'pending_documents': pending_docs
            },
            'recent_activity': list(recent_activity),
            'alerts': alerts
        }
        
        # Cache for 2 minutes
        cache.set(cache_key, dashboard_data, timeout=120)
        
        return JsonResponse(dashboard_data)
        
    except Exception as e:
        return JsonResponse({
            'error': f'Error fetching dashboard data: {str(e)}'
        }, status=500)


@require_http_methods(["GET"])
def task_status(request, task_id):
    """
    Get real-time status of a specific processing task.
    Available to task owner or admin users.
    """
    try:
        # Get task
        task = ProcessingTask.objects.select_related(
            'user', 'public_document', 'user_document'
        ).get(task_id=task_id)
        
        # Check permissions
        if not (request.user.is_staff or request.user == task.user):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Calculate current processing time if still running
        processing_time = task.processing_time_seconds
        if task.status == 'processing' and task.started_at:
            elapsed = timezone.now() - task.started_at
            processing_time = int(elapsed.total_seconds())
        
        # Get document info
        document_info = None
        if task.public_document:
            document_info = {
                'type': 'public',
                'id': str(task.public_document.id),
                'title': task.public_document.title,
                'document_type': task.public_document.document_type
            }
        elif task.user_document:
            document_info = {
                'type': 'personal',
                'id': str(task.user_document.id),
                'filename': task.user_document.file_name,
                'file_type': task.user_document.file_type
            }
        
        task_data = {
            'task_id': task.task_id,
            'task_type': task.task_type,
            'status': task.status,
            'progress_percentage': task.progress_percentage,
            'processing_time_seconds': processing_time,
            'error_message': task.error_message,
            'document': document_info,
            'metrics': {
                'entities_extracted': task.entities_extracted,
                'embeddings_created': task.embeddings_created
            },
            'timestamps': {
                'created_at': task.created_at.isoformat(),
                'started_at': task.started_at.isoformat() if task.started_at else None,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None
            }
        }
        
        return JsonResponse(task_data)
        
    except ProcessingTask.DoesNotExist:
        return JsonResponse({'error': 'Task not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def user_task_status(request):
    """
    Get processing tasks for the current user.
    Shows status of user's document processing tasks.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        # Get user's recent tasks
        user_tasks = ProcessingTask.objects.filter(
            user=request.user
        ).select_related('user_document').order_by('-created_at')[:20]
        
        tasks_data = []
        for task in user_tasks:
            # Calculate processing time
            processing_time = task.processing_time_seconds
            if task.status == 'processing' and task.started_at:
                elapsed = timezone.now() - task.started_at
                processing_time = int(elapsed.total_seconds())
            
            task_info = {
                'task_id': task.task_id,
                'task_type': task.task_type,
                'status': task.status,
                'progress_percentage': task.progress_percentage,
                'processing_time_seconds': processing_time,
                'error_message': task.error_message if task.status == 'failed' else None,
                'created_at': task.created_at.isoformat(),
                'completed_at': task.completed_at.isoformat() if task.completed_at else None
            }
            
            # Add document info for personal documents
            if task.user_document:
                task_info['document'] = {
                    'id': str(task.user_document.id),
                    'filename': task.user_document.file_name,
                    'file_type': task.user_document.file_type
                }
            
            tasks_data.append(task_info)
        
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
        
        return JsonResponse({
            'tasks': tasks_data,
            'partition_info': partition_info,
            'summary': {
                'total_tasks': len(tasks_data),
                'active_tasks': len([t for t in tasks_data if t['status'] in ['queued', 'processing']]),
                'completed_tasks': len([t for t in tasks_data if t['status'] == 'completed']),
                'failed_tasks': len([t for t in tasks_data if t['status'] == 'failed'])
            }
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@require_http_methods(["POST"])
@csrf_exempt
def trigger_queue_monitoring(request):
    """
    Manually trigger queue monitoring task.
    Admin-only endpoint for immediate system health check.
    """
    try:
        # Trigger the monitoring task
        result = monitor_processing_queue.delay()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Queue monitoring task triggered',
            'task_id': result.id
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error triggering monitoring: {str(e)}'
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
@csrf_exempt
def retry_failed_task(request, task_id):
    """
    Retry a specific failed task.
    Admin-only endpoint for manual task recovery.
    """
    try:
        task = ProcessingTask.objects.get(id=task_id, status='failed')
        
        # Import tasks here to avoid circular imports
        from .tasks import process_public_document, process_personal_document
        
        # Retry based on task type
        if task.task_type == 'public_document' and task.public_document:
            new_task = process_public_document.delay(
                str(task.public_document.id),
                str(task.user.id)
            )
            message = f'Retried public document processing task'
        elif task.task_type == 'personal_document' and task.user_document:
            new_task = process_personal_document.delay(
                str(task.user_document.id),
                str(task.user.id)
            )
            message = f'Retried personal document processing task'
        else:
            return JsonResponse({
                'status': 'error',
                'message': 'Cannot retry task: missing document or unsupported task type'
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'message': message,
            'new_task_id': new_task.id,
            'original_task_id': task_id
        })
        
    except ProcessingTask.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Task not found or not in failed state'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error retrying task: {str(e)}'
        }, status=500)


@staff_member_required
@require_http_methods(["GET"])
def system_health_check(request):
    """
    Quick system health check endpoint.
    Returns basic system status indicators.
    """
    try:
        now = timezone.now()
        last_5min = now - timedelta(minutes=5)
        last_1h = now - timedelta(hours=1)
        
        # Quick health indicators
        health_data = {
            'timestamp': now.isoformat(),
            'status': 'healthy',  # Will be updated based on checks
            'checks': {
                'recent_activity': ProcessingTask.objects.filter(
                    created_at__gte=last_5min
                ).count() > 0,
                'stuck_tasks': ProcessingTask.objects.filter(
                    status='processing',
                    started_at__lt=last_1h
                ).count(),
                'failed_tasks_1h': ProcessingTask.objects.filter(
                    status='failed',
                    created_at__gte=last_1h
                ).count(),
                'queue_length': ProcessingTask.objects.filter(
                    status='queued'
                ).count()
            }
        }
        
        # Determine overall health status
        if health_data['checks']['stuck_tasks'] > 5:
            health_data['status'] = 'critical'
        elif (health_data['checks']['stuck_tasks'] > 0 or 
              health_data['checks']['failed_tasks_1h'] > 10 or
              health_data['checks']['queue_length'] > 50):
            health_data['status'] = 'warning'
        
        return JsonResponse(health_data)
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Health check failed: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=500)