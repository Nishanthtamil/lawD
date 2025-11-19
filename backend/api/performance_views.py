"""
API views for performance monitoring and cache management.
Provides endpoints for system health, performance metrics, and cache control.
"""

import logging
from datetime import timedelta
from typing import Dict, Any

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views import View
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status

from .performance_monitor import performance_monitor
from .cache_manager import cache_manager
from .connection_pooling import connection_pool_manager
from .cache_invalidation import CacheInvalidationManager, invalidate_cache_for_user_action, invalidate_cache_for_admin_action

logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def system_health(request):
    """
    Get system health status.
    Available to all authenticated users.
    """
    try:
        # Get basic health information
        health_data = {
            'status': 'healthy',
            'timestamp': performance_monitor._collect_system_metrics().timestamp.isoformat(),
            'cache_health': cache_manager.health_check(),
            'connection_pools': connection_pool_manager.health_check(),
        }
        
        # Check if any component is unhealthy
        overall_status = 'healthy'
        
        if health_data['cache_health'].get('status') != 'healthy':
            overall_status = 'degraded'
        
        for pool_name, pool_health in health_data['connection_pools'].items():
            if isinstance(pool_health, dict) and pool_health.get('status') == 'unhealthy':
                overall_status = 'degraded'
                break
        
        health_data['status'] = overall_status
        
        return Response(health_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return Response(
            {
                'status': 'error',
                'error': str(e),
                'timestamp': performance_monitor._collect_system_metrics().timestamp.isoformat()
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_performance_stats(request):
    """
    Get performance statistics for the current user.
    """
    try:
        user_id = str(request.user.id)
        
        # Get time window from query params
        hours = int(request.GET.get('hours', 24))
        time_window = timedelta(hours=hours)
        
        stats = performance_monitor.get_user_stats(user_id, time_window)
        
        return Response(stats, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Failed to get user performance stats: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def system_performance_stats(request):
    """
    Get comprehensive system performance statistics.
    Admin only.
    """
    try:
        # Get time window from query params
        hours = int(request.GET.get('hours', 1))
        time_window = timedelta(hours=hours)
        
        stats = performance_monitor.get_stats(time_window)
        
        # Add additional admin-specific information
        stats['slow_queries'] = performance_monitor.get_slow_queries(10)
        stats['error_summary'] = performance_monitor.get_error_summary(time_window)
        stats['cache_stats'] = cache_manager.get_cache_stats()
        stats['connection_pool_stats'] = connection_pool_manager.get_pool_stats()
        
        return Response(stats, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Failed to get system performance stats: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def slow_queries(request):
    """
    Get list of slowest queries.
    Admin only.
    """
    try:
        limit = int(request.GET.get('limit', 20))
        slow_queries = performance_monitor.get_slow_queries(limit)
        
        return Response(
            {'slow_queries': slow_queries},
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Failed to get slow queries: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def error_summary(request):
    """
    Get error summary and analysis.
    Admin only.
    """
    try:
        hours = int(request.GET.get('hours', 24))
        time_window = timedelta(hours=hours)
        
        error_summary = performance_monitor.get_error_summary(time_window)
        
        return Response(error_summary, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Failed to get error summary: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def invalidate_user_cache(request):
    """
    Invalidate cache for the current user.
    """
    try:
        user_id = str(request.user.id)
        action = request.data.get('action', 'manual_invalidation')
        
        results = invalidate_cache_for_user_action(user_id, action)
        
        return Response(
            {
                'message': 'User cache invalidated successfully',
                'results': results
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Failed to invalidate user cache: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def invalidate_system_cache(request):
    """
    Invalidate system-wide cache.
    Admin only.
    """
    try:
        action = request.data.get('action', 'system_maintenance')
        target_id = request.data.get('target_id')
        
        results = invalidate_cache_for_admin_action(action, target_id)
        
        return Response(
            {
                'message': 'System cache invalidated successfully',
                'results': results
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Failed to invalidate system cache: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def cache_statistics(request):
    """
    Get detailed cache statistics.
    Admin only.
    """
    try:
        stats = {
            'cache_health': cache_manager.health_check(),
            'cache_stats': cache_manager.get_cache_stats(),
            'redis_info': {},
        }
        
        # Get Redis-specific information if available
        try:
            if cache_manager.redis_client:
                redis_info = cache_manager.redis_client.info()
                stats['redis_info'] = {
                    'connected_clients': redis_info.get('connected_clients', 0),
                    'used_memory_human': redis_info.get('used_memory_human', 'unknown'),
                    'keyspace_hits': redis_info.get('keyspace_hits', 0),
                    'keyspace_misses': redis_info.get('keyspace_misses', 0),
                    'total_commands_processed': redis_info.get('total_commands_processed', 0),
                    'uptime_in_seconds': redis_info.get('uptime_in_seconds', 0),
                }
        except Exception as e:
            logger.warning(f"Failed to get Redis info: {e}")
            stats['redis_info'] = {'error': str(e)}
        
        return Response(stats, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Failed to get cache statistics: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def connection_pool_status(request):
    """
    Get connection pool status and statistics.
    Admin only.
    """
    try:
        status_data = {
            'health': connection_pool_manager.health_check(),
            'stats': connection_pool_manager.get_pool_stats(),
        }
        
        return Response(status_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Failed to get connection pool status: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def reset_performance_stats(request):
    """
    Reset performance statistics.
    Admin only - use with caution.
    """
    try:
        performance_monitor.reset_stats()
        
        return Response(
            {'message': 'Performance statistics reset successfully'},
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Failed to reset performance stats: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def query_performance_history(request):
    """
    Get query performance history for the current user.
    """
    try:
        user_id = str(request.user.id)
        
        # Get cached recent metrics
        cache_key = f"recent_query_metrics_{user_id}"
        recent_metrics = cache_manager.get(cache_key, [])
        
        # Limit to last 20 queries
        recent_metrics = recent_metrics[-20:]
        
        return Response(
            {
                'user_id': user_id,
                'recent_queries': recent_metrics,
                'total_count': len(recent_metrics)
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Failed to get query performance history: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class PerformanceDashboardView(View):
    """
    HTML view for performance dashboard.
    Admin only.
    """
    
    @method_decorator(staff_member_required)
    def get(self, request):
        """Render performance dashboard."""
        try:
            # Get basic stats for dashboard
            stats = performance_monitor.get_stats(timedelta(hours=1))
            
            context = {
                'stats': stats,
                'cache_health': cache_manager.health_check(),
                'connection_health': connection_pool_manager.health_check(),
            }
            
            # For now, return JSON (in production, render HTML template)
            return JsonResponse(context)
            
        except Exception as e:
            logger.error(f"Dashboard view failed: {e}")
            return JsonResponse(
                {'error': str(e)},
                status=500
            )


# Utility view for testing performance monitoring
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_performance_monitoring(request):
    """
    Test endpoint for performance monitoring.
    Creates sample metrics for testing.
    """
    try:
        user_id = str(request.user.id)
        
        # Record a test query metric
        query_id = performance_monitor.record_query_metrics(
            query_type='test',
            execution_time=0.5,
            result_count=10,
            user_id=user_id,
            cache_hit=False
        )
        
        return Response(
            {
                'message': 'Test metric recorded successfully',
                'query_id': query_id
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Test performance monitoring failed: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )