from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db.models import Count, Avg, Q
from django.utils import timezone
from datetime import timedelta
import json

from .models import (
    User, OTP, ChatSession, ChatMessage, UserDocument,
    PublicDocument, ProcessingTask, UserPartition
)

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['phone_number', 'name', 'is_verified', 'date_joined']
    search_fields = ['phone_number', 'name']
    list_filter = ['is_verified', 'is_active']

@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ['phone_number', 'otp', 'created_at', 'is_verified']
    list_filter = ['is_verified']

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'title', 'created_at']
    search_fields = ['user__phone_number', 'title']

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['session', 'role', 'created_at']
    list_filter = ['role']

@admin.register(UserDocument)
class UserDocumentAdmin(admin.ModelAdmin):
    list_display = ['user', 'file_name', 'status', 'created_at']
    list_filter = ['status', 'file_type']


@admin.register(PublicDocument)
class PublicDocumentAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'document_type', 'legal_domain', 'processing_status', 
        'uploaded_by', 'created_at'
    ]
    list_filter = [
        'document_type', 'legal_domain', 'processing_status', 
        'jurisdiction', 'created_at'
    ]
    search_fields = ['title', 'uploaded_by__phone_number']
    readonly_fields = ['entities_extracted', 'relationships_count', 'embeddings_count']
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'document_type', 'file_path', 'uploaded_by')
        }),
        ('Metadata', {
            'fields': ('legal_domain', 'jurisdiction', 'effective_date')
        }),
        ('Processing Status', {
            'fields': (
                'processing_status', 'entities_extracted', 
                'relationships_count', 'embeddings_count', 'processed_at'
            )
        }),
    )


@admin.register(ProcessingTask)
class ProcessingTaskAdmin(admin.ModelAdmin):
    list_display = [
        'task_type', 'status_badge', 'user', 'progress_bar', 
        'document_link', 'processing_time_display', 'created_at'
    ]
    list_filter = [
        'task_type', 'status', 'created_at', 
        ('started_at', admin.DateFieldListFilter),
        ('completed_at', admin.DateFieldListFilter)
    ]
    search_fields = ['task_id', 'user__phone_number', 'public_document__title', 'user_document__file_name']
    readonly_fields = [
        'task_id', 'processing_time_seconds', 'entities_extracted', 
        'embeddings_created', 'created_at', 'started_at', 'completed_at',
        'processing_time_display', 'task_metrics'
    ]
    
    actions = ['retry_failed_tasks', 'cancel_queued_tasks']
    
    fieldsets = (
        ('Task Information', {
            'fields': ('task_id', 'task_type', 'user')
        }),
        ('Related Documents', {
            'fields': ('public_document', 'user_document')
        }),
        ('Status & Progress', {
            'fields': ('status', 'progress_percentage', 'error_message')
        }),
        ('Metrics', {
            'fields': (
                'processing_time_display', 'entities_extracted', 
                'embeddings_created', 'task_metrics'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'started_at', 'completed_at')
        }),
    )
    
    def status_badge(self, obj):
        """Display status with color-coded badge"""
        colors = {
            'queued': '#ffc107',      # yellow
            'processing': '#007bff',   # blue
            'completed': '#28a745',    # green
            'failed': '#dc3545',       # red
            'cancelled': '#6c757d'     # gray
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = 'Status'
    
    def progress_bar(self, obj):
        """Display progress as a visual bar"""
        if obj.status in ['completed']:
            progress = 100
            color = '#28a745'
        elif obj.status == 'failed':
            progress = 0
            color = '#dc3545'
        else:
            progress = obj.progress_percentage
            color = '#007bff'
        
        return format_html(
            '<div style="width: 100px; background-color: #e9ecef; border-radius: 3px;">'
            '<div style="width: {}%; height: 20px; background-color: {}; '
            'border-radius: 3px; text-align: center; line-height: 20px; '
            'color: white; font-size: 11px; font-weight: bold;">{}</div></div>',
            progress, color, f'{progress}%'
        )
    progress_bar.short_description = 'Progress'
    
    def document_link(self, obj):
        """Display link to related document"""
        if obj.public_document:
            url = reverse('admin:api_publicdocument_change', args=[obj.public_document.id])
            return format_html('<a href="{}">{}</a>', url, obj.public_document.title[:50])
        elif obj.user_document:
            url = reverse('admin:api_userdocument_change', args=[obj.user_document.id])
            return format_html('<a href="{}">{}</a>', url, obj.user_document.file_name[:50])
        return '-'
    document_link.short_description = 'Document'
    
    def processing_time_display(self, obj):
        """Display processing time in human-readable format"""
        if obj.processing_time_seconds:
            minutes, seconds = divmod(obj.processing_time_seconds, 60)
            if minutes > 0:
                return f"{minutes}m {seconds}s"
            return f"{seconds}s"
        elif obj.status == 'processing' and obj.started_at:
            elapsed = timezone.now() - obj.started_at
            total_seconds = int(elapsed.total_seconds())
            minutes, seconds = divmod(total_seconds, 60)
            if minutes > 0:
                return f"{minutes}m {seconds}s (ongoing)"
            return f"{seconds}s (ongoing)"
        return '-'
    processing_time_display.short_description = 'Processing Time'
    
    def task_metrics(self, obj):
        """Display task metrics in a formatted way"""
        metrics = []
        if obj.entities_extracted > 0:
            metrics.append(f"Entities: {obj.entities_extracted}")
        if obj.embeddings_created > 0:
            metrics.append(f"Embeddings: {obj.embeddings_created}")
        
        if metrics:
            return format_html('<br>'.join(metrics))
        return '-'
    task_metrics.short_description = 'Metrics'
    
    def retry_failed_tasks(self, request, queryset):
        """Admin action to retry failed tasks"""
        from .tasks import process_public_document, process_personal_document
        
        failed_tasks = queryset.filter(status='failed')
        retried_count = 0
        
        for task in failed_tasks:
            try:
                if task.task_type == 'public_document' and task.public_document:
                    process_public_document.delay(
                        str(task.public_document.id),
                        str(task.user.id)
                    )
                    retried_count += 1
                elif task.task_type == 'personal_document' and task.user_document:
                    process_personal_document.delay(
                        str(task.user_document.id),
                        str(task.user.id)
                    )
                    retried_count += 1
            except Exception as e:
                self.message_user(request, f"Error retrying task {task.id}: {str(e)}", level='ERROR')
        
        self.message_user(request, f"Retried {retried_count} failed tasks")
    retry_failed_tasks.short_description = "Retry selected failed tasks"
    
    def cancel_queued_tasks(self, request, queryset):
        """Admin action to cancel queued tasks"""
        queued_tasks = queryset.filter(status='queued')
        cancelled_count = queued_tasks.update(
            status='cancelled',
            error_message='Cancelled by admin',
            completed_at=timezone.now()
        )
        self.message_user(request, f"Cancelled {cancelled_count} queued tasks")
    cancel_queued_tasks.short_description = "Cancel selected queued tasks"
    
    def changelist_view(self, request, extra_context=None):
        """Add custom context for task monitoring dashboard"""
        extra_context = extra_context or {}
        
        # Calculate task statistics
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        
        # Recent task counts
        recent_tasks = ProcessingTask.objects.filter(created_at__gte=last_24h)
        task_stats = {
            'total_24h': recent_tasks.count(),
            'queued': recent_tasks.filter(status='queued').count(),
            'processing': recent_tasks.filter(status='processing').count(),
            'completed': recent_tasks.filter(status='completed').count(),
            'failed': recent_tasks.filter(status='failed').count(),
        }
        
        # Average processing times
        completed_tasks = ProcessingTask.objects.filter(
            status='completed',
            processing_time_seconds__isnull=False,
            completed_at__gte=last_7d
        )
        
        avg_times = completed_tasks.aggregate(
            public_avg=Avg('processing_time_seconds', filter=Q(task_type='public_document')),
            personal_avg=Avg('processing_time_seconds', filter=Q(task_type='personal_document'))
        )
        
        # Stuck tasks (processing for more than 1 hour)
        stuck_threshold = now - timedelta(hours=1)
        stuck_tasks = ProcessingTask.objects.filter(
            status='processing',
            started_at__lt=stuck_threshold
        ).count()
        
        extra_context.update({
            'task_stats': task_stats,
            'avg_processing_times': {
                'public_document': round(avg_times['public_avg'] or 0, 1),
                'personal_document': round(avg_times['personal_avg'] or 0, 1)
            },
            'stuck_tasks_count': stuck_tasks,
            'success_rate': round(
                (task_stats['completed'] / max(task_stats['total_24h'], 1)) * 100, 1
            )
        })
        
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(UserPartition)
class UserPartitionAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'partition_name', 'document_count', 
        'total_embeddings', 'last_accessed'
    ]
    search_fields = ['user__phone_number', 'partition_name']
    readonly_fields = ['partition_name', 'created_at']
    list_filter = ['created_at', 'last_accessed']