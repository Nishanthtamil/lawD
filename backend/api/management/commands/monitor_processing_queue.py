"""
Management command to monitor processing queue and generate reports.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count, Avg, Q
from datetime import timedelta
import json

from api.models import ProcessingTask, PublicDocument, UserDocument


class Command(BaseCommand):
    help = 'Monitor processing queue and generate system health reports'

    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            type=str,
            default='table',
            choices=['table', 'json'],
            help='Output format (table or json)'
        )
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Time window in hours for analysis (default: 24)'
        )
        parser.add_argument(
            '--show-stuck',
            action='store_true',
            help='Show details of stuck tasks'
        )
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Clean up orphaned and stuck tasks'
        )

    def handle(self, *args, **options):
        """Main command handler"""
        self.stdout.write(
            self.style.SUCCESS('Processing Queue Monitor')
        )
        self.stdout.write('=' * 50)
        
        # Calculate time window
        now = timezone.now()
        time_window = now - timedelta(hours=options['hours'])
        
        # Gather statistics
        stats = self.gather_statistics(time_window)
        
        # Output results
        if options['format'] == 'json':
            self.output_json(stats)
        else:
            self.output_table(stats, options['hours'])
        
        # Show stuck tasks if requested
        if options['show_stuck']:
            self.show_stuck_tasks()
        
        # Cleanup if requested
        if options['cleanup']:
            self.cleanup_tasks()

    def gather_statistics(self, time_window):
        """Gather processing queue statistics"""
        # Task counts by status
        recent_tasks = ProcessingTask.objects.filter(created_at__gte=time_window)
        
        task_counts = {
            'total': recent_tasks.count(),
            'queued': recent_tasks.filter(status='queued').count(),
            'processing': recent_tasks.filter(status='processing').count(),
            'completed': recent_tasks.filter(status='completed').count(),
            'failed': recent_tasks.filter(status='failed').count(),
            'cancelled': recent_tasks.filter(status='cancelled').count(),
        }
        
        # Task counts by type
        task_types = recent_tasks.values('task_type').annotate(
            count=Count('id')
        ).order_by('task_type')
        
        # Average processing times
        completed_tasks = recent_tasks.filter(
            status='completed',
            processing_time_seconds__isnull=False
        )
        
        avg_times = completed_tasks.aggregate(
            overall=Avg('processing_time_seconds'),
            public_doc=Avg('processing_time_seconds', filter=Q(task_type='public_document')),
            personal_doc=Avg('processing_time_seconds', filter=Q(task_type='personal_document'))
        )
        
        # Success rates
        success_rate = 0
        if task_counts['total'] > 0:
            success_rate = (task_counts['completed'] / task_counts['total']) * 100
        
        # Stuck tasks (processing for more than 1 hour)
        stuck_threshold = timezone.now() - timedelta(hours=1)
        stuck_tasks = ProcessingTask.objects.filter(
            status='processing',
            started_at__lt=stuck_threshold
        )
        
        # Orphaned tasks (queued for more than 24 hours)
        orphaned_threshold = timezone.now() - timedelta(hours=24)
        orphaned_tasks = ProcessingTask.objects.filter(
            status='queued',
            created_at__lt=orphaned_threshold
        )
        
        # Document processing stats
        public_docs_pending = PublicDocument.objects.filter(
            processing_status='pending'
        ).count()
        
        user_docs_pending = UserDocument.objects.filter(
            status='pending'
        ).count()
        
        return {
            'task_counts': task_counts,
            'task_types': list(task_types),
            'avg_times': avg_times,
            'success_rate': success_rate,
            'stuck_tasks': stuck_tasks.count(),
            'orphaned_tasks': orphaned_tasks.count(),
            'pending_documents': {
                'public': public_docs_pending,
                'personal': user_docs_pending
            }
        }

    def output_table(self, stats, hours):
        """Output statistics in table format"""
        self.stdout.write(f"\nStatistics for last {hours} hours:")
        self.stdout.write("-" * 40)
        
        # Task status summary
        self.stdout.write("\nTask Status Summary:")
        for status, count in stats['task_counts'].items():
            if status == 'total':
                self.stdout.write(f"  {status.capitalize()}: {count}")
            else:
                percentage = (count / max(stats['task_counts']['total'], 1)) * 100
                self.stdout.write(f"  {status.capitalize()}: {count} ({percentage:.1f}%)")
        
        # Task types
        self.stdout.write("\nTask Types:")
        for task_type in stats['task_types']:
            self.stdout.write(f"  {task_type['task_type']}: {task_type['count']}")
        
        # Performance metrics
        self.stdout.write("\nPerformance Metrics:")
        self.stdout.write(f"  Success Rate: {stats['success_rate']:.1f}%")
        
        if stats['avg_times']['overall']:
            self.stdout.write(f"  Average Processing Time: {stats['avg_times']['overall']:.1f}s")
        
        if stats['avg_times']['public_doc']:
            self.stdout.write(f"  Public Documents: {stats['avg_times']['public_doc']:.1f}s")
        
        if stats['avg_times']['personal_doc']:
            self.stdout.write(f"  Personal Documents: {stats['avg_times']['personal_doc']:.1f}s")
        
        # System health
        self.stdout.write("\nSystem Health:")
        self.stdout.write(f"  Stuck Tasks: {stats['stuck_tasks']}")
        self.stdout.write(f"  Orphaned Tasks: {stats['orphaned_tasks']}")
        self.stdout.write(f"  Pending Public Documents: {stats['pending_documents']['public']}")
        self.stdout.write(f"  Pending Personal Documents: {stats['pending_documents']['personal']}")
        
        # Alerts
        alerts = []
        if stats['stuck_tasks'] > 0:
            alerts.append(f"⚠️  {stats['stuck_tasks']} tasks are stuck in processing")
        
        if stats['orphaned_tasks'] > 0:
            alerts.append(f"⚠️  {stats['orphaned_tasks']} tasks are orphaned")
        
        if stats['success_rate'] < 90:
            alerts.append(f"⚠️  Low success rate: {stats['success_rate']:.1f}%")
        
        if stats['task_counts']['failed'] > stats['task_counts']['completed'] * 0.1:
            alerts.append(f"⚠️  High failure rate: {stats['task_counts']['failed']} failed tasks")
        
        if alerts:
            self.stdout.write("\n" + self.style.WARNING("System Alerts:"))
            for alert in alerts:
                self.stdout.write(f"  {alert}")
        else:
            self.stdout.write("\n" + self.style.SUCCESS("✅ System is healthy"))

    def output_json(self, stats):
        """Output statistics in JSON format"""
        # Convert any non-serializable objects
        json_stats = {
            'timestamp': timezone.now().isoformat(),
            'task_counts': stats['task_counts'],
            'task_types': stats['task_types'],
            'avg_times': {
                k: float(v) if v else None 
                for k, v in stats['avg_times'].items()
            },
            'success_rate': float(stats['success_rate']),
            'stuck_tasks': stats['stuck_tasks'],
            'orphaned_tasks': stats['orphaned_tasks'],
            'pending_documents': stats['pending_documents']
        }
        
        self.stdout.write(json.dumps(json_stats, indent=2))

    def show_stuck_tasks(self):
        """Show details of stuck tasks"""
        stuck_threshold = timezone.now() - timedelta(hours=1)
        stuck_tasks = ProcessingTask.objects.filter(
            status='processing',
            started_at__lt=stuck_threshold
        ).select_related('user', 'public_document', 'user_document')
        
        if not stuck_tasks.exists():
            self.stdout.write(self.style.SUCCESS("\n✅ No stuck tasks found"))
            return
        
        self.stdout.write(self.style.WARNING(f"\n⚠️  Found {stuck_tasks.count()} stuck tasks:"))
        self.stdout.write("-" * 60)
        
        for task in stuck_tasks:
            elapsed = timezone.now() - task.started_at
            hours = elapsed.total_seconds() / 3600
            
            doc_info = "Unknown"
            if task.public_document:
                doc_info = f"Public: {task.public_document.title[:30]}"
            elif task.user_document:
                doc_info = f"Personal: {task.user_document.file_name[:30]}"
            
            self.stdout.write(
                f"  Task {task.id}: {task.task_type} | "
                f"User: {task.user.phone_number} | "
                f"Running: {hours:.1f}h | "
                f"Doc: {doc_info}"
            )

    def cleanup_tasks(self):
        """Clean up orphaned and optionally stuck tasks"""
        now = timezone.now()
        
        # Clean up orphaned tasks (queued for more than 24 hours)
        orphaned_threshold = now - timedelta(hours=24)
        orphaned_tasks = ProcessingTask.objects.filter(
            status='queued',
            created_at__lt=orphaned_threshold
        )
        
        orphaned_count = orphaned_tasks.count()
        if orphaned_count > 0:
            orphaned_tasks.update(
                status='cancelled',
                error_message='Task cancelled due to timeout',
                completed_at=now
            )
            self.stdout.write(
                self.style.SUCCESS(f"✅ Cancelled {orphaned_count} orphaned tasks")
            )
        
        # Ask about stuck tasks
        stuck_threshold = now - timedelta(hours=2)  # More conservative for cleanup
        stuck_tasks = ProcessingTask.objects.filter(
            status='processing',
            started_at__lt=stuck_threshold
        )
        
        stuck_count = stuck_tasks.count()
        if stuck_count > 0:
            self.stdout.write(
                self.style.WARNING(f"\n⚠️  Found {stuck_count} tasks stuck for >2 hours")
            )
            
            response = input("Cancel these stuck tasks? (y/N): ")
            if response.lower() == 'y':
                stuck_tasks.update(
                    status='failed',
                    error_message='Task cancelled due to timeout (stuck >2 hours)',
                    completed_at=now
                )
                self.stdout.write(
                    self.style.SUCCESS(f"✅ Cancelled {stuck_count} stuck tasks")
                )
            else:
                self.stdout.write("Stuck tasks left unchanged")
        
        if orphaned_count == 0 and stuck_count == 0:
            self.stdout.write(self.style.SUCCESS("✅ No tasks need cleanup"))