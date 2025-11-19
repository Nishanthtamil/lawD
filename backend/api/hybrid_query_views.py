"""
Hybrid Query Processing API Views.
Provides endpoints for segregated hybrid RAG query processing with intent detection.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import json
import re
from datetime import timedelta
from typing import Dict, List, Any, Tuple

from .models import User, UserPartition, ChatSession, ChatMessage
from .segregated_retriever import SegregatedRetriever
from .llm_synthesizer import LLMSynthesizer
from .security_validators import (
    comprehensive_security_validator,
    query_parameter_validator,
    rate_limit_validator
)


class QueryClassifier:
    """
    Classifies user queries to determine intent and processing strategy.
    """
    
    def __init__(self):
        self.personal_indicators = [
            'my document', 'my case', 'my file', 'my contract', 'my agreement',
            'uploaded document', 'personal document', 'in my files',
            'according to my', 'based on my', 'my legal matter'
        ]
        
        self.constitutional_indicators = [
            'article', 'constitution', 'fundamental right', 'directive principle',
            'amendment', 'constitutional provision', 'part iii', 'part iv',
            'supreme court', 'high court', 'parliament', 'president', 'governor'
        ]
        
        self.case_law_indicators = [
            'case law', 'precedent', 'judgment', 'ruling', 'court decision',
            'vs', 'v.', 'appeal', 'petition', 'writ', 'suo moto'
        ]
        
        self.general_legal_indicators = [
            'legal advice', 'what is', 'explain', 'define', 'meaning of',
            'how to', 'procedure', 'process', 'steps', 'requirements'
        ]
    
    def classify_query(self, query: str, user_has_documents: bool = False) -> Dict[str, Any]:
        """
        Classify query intent and determine processing strategy.
        
        Args:
            query: User's query text
            user_has_documents: Whether user has uploaded documents
            
        Returns:
            Dictionary with classification results and processing recommendations
        """
        try:
            query_lower = query.lower()
            
            # Initialize classification scores
            scores = {
                'personal': 0,
                'constitutional': 0,
                'case_law': 0,
                'general_legal': 0
            }
            
            # Check for personal document indicators
            for indicator in self.personal_indicators:
                if indicator in query_lower:
                    scores['personal'] += 2
            
            # Boost personal score if user has documents and uses possessive language
            if user_has_documents:
                possessive_patterns = [r'\bmy\b', r'\bour\b', r'\bthis case\b', r'\bthis matter\b']
                for pattern in possessive_patterns:
                    if re.search(pattern, query_lower):
                        scores['personal'] += 1
            
            # Check for constitutional indicators
            for indicator in self.constitutional_indicators:
                if indicator in query_lower:
                    scores['constitutional'] += 1
            
            # Check for case law indicators
            for indicator in self.case_law_indicators:
                if indicator in query_lower:
                    scores['case_law'] += 1
            
            # Check for general legal indicators
            for indicator in self.general_legal_indicators:
                if indicator in query_lower:
                    scores['general_legal'] += 1
            
            # Determine primary intent
            max_score = max(scores.values())
            primary_intent = 'hybrid'  # Default to hybrid
            
            if max_score > 0:
                primary_intent = max(scores, key=scores.get)
            
            # Determine processing strategy
            processing_strategy = self._determine_processing_strategy(
                primary_intent, scores, user_has_documents
            )
            
            return {
                'query': query,
                'primary_intent': primary_intent,
                'intent_scores': scores,
                'processing_strategy': processing_strategy,
                'confidence': max_score / (sum(scores.values()) + 1),  # Normalize confidence
                'user_has_documents': user_has_documents
            }
            
        except Exception as e:
            # Fallback to hybrid processing
            return {
                'query': query,
                'primary_intent': 'hybrid',
                'intent_scores': {'personal': 0, 'constitutional': 0, 'case_law': 0, 'general_legal': 0},
                'processing_strategy': 'hybrid_search',
                'confidence': 0.0,
                'error': str(e)
            }
    
    def _determine_processing_strategy(self, primary_intent: str, scores: Dict[str, int], 
                                     user_has_documents: bool) -> str:
        """Determine the optimal processing strategy based on classification"""
        
        # If user has no documents, skip personal search
        if not user_has_documents:
            if primary_intent == 'personal':
                return 'public_only'
            elif primary_intent in ['constitutional', 'case_law']:
                return 'public_focused'
            else:
                return 'public_only'
        
        # User has documents - determine strategy
        if primary_intent == 'personal' and scores['personal'] >= 2:
            return 'personal_focused'
        elif primary_intent in ['constitutional', 'case_law'] and scores[primary_intent] >= 2:
            return 'public_focused'
        elif sum(scores.values()) >= 3:
            return 'hybrid_search'
        else:
            return 'balanced_search'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def process_hybrid_query(request):
    """
    Process a hybrid query using segregated retrieval and LLM synthesis.
    Main endpoint for the segregated hybrid RAG pipeline.
    """
    try:
        # Validate user request
        user_valid, user_error = comprehensive_security_validator.validate_user_request(request.user)
        if not user_valid:
            return Response({
                'error': user_error
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Check rate limits
        rate_valid, rate_error = rate_limit_validator.validate_query_rate(str(request.user.id))
        if not rate_valid:
            return Response({
                'error': rate_error
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Get and validate query parameters
        query = request.data.get('query', '').strip()
        if not query:
            return Response({
                'error': 'Query is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get optional parameters
        session_id = request.data.get('session_id')
        personal_top_k = min(int(request.data.get('personal_top_k', 5)), 20)
        public_semantic_top_k = min(int(request.data.get('public_semantic_top_k', 10)), 30)
        public_graph_limit = min(int(request.data.get('public_graph_limit', 10)), 20)
        include_debug_info = request.data.get('include_debug_info', False)
        
        # Validate query parameters
        query_params = {
            'query': query,
            'top_k': personal_top_k,
            'user_id': str(request.user.id)
        }
        
        params_valid, params_error, sanitized_params = query_parameter_validator.validate_search_parameters(
            str(request.user.id), query_params
        )
        if not params_valid:
            return Response({
                'error': params_error
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user has documents for classification
        user_has_documents = UserPartition.objects.filter(
            user=request.user, 
            document_count__gt=0
        ).exists()
        
        # Classify query intent
        classifier = QueryClassifier()
        classification = classifier.classify_query(query, user_has_documents)
        
        # Initialize retriever and process query
        retriever = SegregatedRetriever()
        
        # Adjust search parameters based on classification
        search_params = _adjust_search_parameters(
            classification['processing_strategy'],
            personal_top_k,
            public_semantic_top_k,
            public_graph_limit
        )
        
        # Execute hybrid search and synthesis
        response_data = retriever.hybrid_search_and_synthesize(
            user_id=str(request.user.id),
            query=query,
            personal_top_k=search_params['personal_top_k'],
            public_semantic_top_k=search_params['public_semantic_top_k'],
            public_graph_limit=search_params['public_graph_limit']
        )
        
        # Add classification metadata
        response_data['query_classification'] = classification
        
        # Save to chat session if provided
        if session_id:
            _save_to_chat_session(request.user, session_id, query, response_data)
        
        # Add debug information if requested
        if include_debug_info:
            response_data['debug_info'] = {
                'search_parameters': search_params,
                'user_has_documents': user_has_documents,
                'processing_time': timezone.now().isoformat()
            }
        
        return Response(response_data)
        
    except Exception as e:
        return Response({
            'error': f'Error processing query: {str(e)}',
            'query': request.data.get('query', ''),
            'generated_at': timezone.now().isoformat()
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def classify_query_intent(request):
    """
    Classify query intent without processing the full query.
    Useful for UI optimization and query routing.
    """
    try:
        # Validate user request
        user_valid, user_error = comprehensive_security_validator.validate_user_request(request.user)
        if not user_valid:
            return Response({
                'error': user_error
            }, status=status.HTTP_403_FORBIDDEN)
        
        query = request.data.get('query', '').strip()
        if not query:
            return Response({
                'error': 'Query is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user has documents
        user_has_documents = UserPartition.objects.filter(
            user=request.user, 
            document_count__gt=0
        ).exists()
        
        # Classify query
        classifier = QueryClassifier()
        classification = classifier.classify_query(query, user_has_documents)
        
        # Add recommendations
        classification['recommendations'] = _get_processing_recommendations(classification)
        
        return Response(classification)
        
    except Exception as e:
        return Response({
            'error': f'Error classifying query: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def query_capabilities(request):
    """
    Get information about user's query capabilities and available sources.
    """
    try:
        # Validate user request
        user_valid, user_error = comprehensive_security_validator.validate_user_request(request.user)
        if not user_valid:
            return Response({
                'error': user_error
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get user partition info
        partition_info = None
        try:
            user_partition = UserPartition.objects.get(user=request.user)
            partition_info = {
                'exists': True,
                'document_count': user_partition.document_count,
                'total_embeddings': user_partition.total_embeddings,
                'last_accessed': user_partition.last_accessed.isoformat()
            }
        except UserPartition.DoesNotExist:
            partition_info = {
                'exists': False,
                'document_count': 0,
                'total_embeddings': 0
            }
        
        # Get retrieval statistics
        retriever = SegregatedRetriever()
        retrieval_stats = retriever.get_retrieval_stats(str(request.user.id))
        
        capabilities = {
            'user_id': str(request.user.id),
            'personal_documents': partition_info,
            'public_knowledge': {
                'constitutional_law': True,
                'case_law': True,
                'legal_precedents': True,
                'amendments': True
            },
            'query_types_supported': [
                'personal_document_analysis',
                'constitutional_queries',
                'case_law_research',
                'hybrid_legal_analysis',
                'general_legal_questions'
            ],
            'processing_strategies': [
                'personal_focused',
                'public_focused', 
                'hybrid_search',
                'balanced_search'
            ],
            'retrieval_statistics': retrieval_stats,
            'rate_limits': {
                'queries_per_minute': 30,
                'documents_per_hour': 10
            }
        }
        
        return Response(capabilities)
        
    except Exception as e:
        return Response({
            'error': f'Error retrieving capabilities: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _adjust_search_parameters(processing_strategy: str, personal_top_k: int, 
                            public_semantic_top_k: int, public_graph_limit: int) -> Dict[str, int]:
    """Adjust search parameters based on processing strategy"""
    
    if processing_strategy == 'personal_focused':
        return {
            'personal_top_k': min(personal_top_k * 2, 20),
            'public_semantic_top_k': max(public_semantic_top_k // 2, 3),
            'public_graph_limit': max(public_graph_limit // 2, 3)
        }
    elif processing_strategy == 'public_focused':
        return {
            'personal_top_k': max(personal_top_k // 2, 2),
            'public_semantic_top_k': min(public_semantic_top_k * 2, 30),
            'public_graph_limit': min(public_graph_limit * 2, 20)
        }
    elif processing_strategy == 'public_only':
        return {
            'personal_top_k': 0,
            'public_semantic_top_k': min(public_semantic_top_k * 2, 30),
            'public_graph_limit': min(public_graph_limit * 2, 20)
        }
    else:  # hybrid_search or balanced_search
        return {
            'personal_top_k': personal_top_k,
            'public_semantic_top_k': public_semantic_top_k,
            'public_graph_limit': public_graph_limit
        }


def _get_processing_recommendations(classification: Dict[str, Any]) -> Dict[str, Any]:
    """Get processing recommendations based on classification"""
    
    strategy = classification['processing_strategy']
    primary_intent = classification['primary_intent']
    
    recommendations = {
        'strategy': strategy,
        'expected_sources': [],
        'optimization_tips': []
    }
    
    if strategy == 'personal_focused':
        recommendations['expected_sources'] = ['personal_documents', 'limited_public_context']
        recommendations['optimization_tips'] = [
            'Ensure your personal documents are relevant to the query',
            'Consider uploading additional related documents for better context'
        ]
    elif strategy == 'public_focused':
        recommendations['expected_sources'] = ['constitutional_law', 'case_law', 'legal_precedents']
        recommendations['optimization_tips'] = [
            'Use specific legal terminology for better results',
            'Reference specific articles or case names if known'
        ]
    elif strategy == 'public_only':
        recommendations['expected_sources'] = ['constitutional_law', 'case_law', 'legal_precedents']
        recommendations['optimization_tips'] = [
            'Upload personal documents to get personalized analysis',
            'Use specific constitutional or legal terms'
        ]
    else:  # hybrid or balanced
        recommendations['expected_sources'] = ['personal_documents', 'constitutional_law', 'case_law']
        recommendations['optimization_tips'] = [
            'Query combines personal and public legal knowledge',
            'Results will show connections between your documents and legal framework'
        ]
    
    return recommendations


def _save_to_chat_session(user: User, session_id: str, query: str, response_data: Dict[str, Any]):
    """Save query and response to chat session"""
    try:
        # Get or create chat session
        chat_session, created = ChatSession.objects.get_or_create(
            id=session_id,
            user=user,
            defaults={'title': query[:50] + '...' if len(query) > 50 else query}
        )
        
        # Save user message
        user_message = ChatMessage.objects.create(
            session=chat_session,
            role='user',
            content=query
        )
        
        # Save assistant response
        assistant_content = response_data.get('response', 'No response generated')
        assistant_message = ChatMessage.objects.create(
            session=chat_session,
            role='assistant',
            content=assistant_content
        )
        
        # Update session timestamp
        chat_session.save()  # This will update the updated_at field
        
    except Exception as e:
        # Don't fail the main request if chat saving fails
        print(f"Warning: Could not save to chat session {session_id}: {e}")


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def batch_query_processing(request):
    """
    Process multiple queries in batch for efficiency.
    Useful for analyzing multiple related questions.
    """
    try:
        # Validate user request
        user_valid, user_error = comprehensive_security_validator.validate_user_request(request.user)
        if not user_valid:
            return Response({
                'error': user_error
            }, status=status.HTTP_403_FORBIDDEN)
        
        queries = request.data.get('queries', [])
        if not queries or not isinstance(queries, list):
            return Response({
                'error': 'Queries list is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if len(queries) > 5:  # Limit batch size
            return Response({
                'error': 'Maximum 5 queries per batch'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check rate limits (stricter for batch)
        rate_valid, rate_error = rate_limit_validator.validate_query_rate(str(request.user.id))
        if not rate_valid:
            return Response({
                'error': f'Rate limit exceeded for batch processing: {rate_error}'
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Process each query
        results = []
        retriever = SegregatedRetriever()
        
        for i, query_text in enumerate(queries):
            if not query_text or not isinstance(query_text, str):
                results.append({
                    'query_index': i,
                    'query': query_text,
                    'error': 'Invalid query format'
                })
                continue
            
            try:
                # Process individual query
                response_data = retriever.hybrid_search_and_synthesize(
                    user_id=str(request.user.id),
                    query=query_text.strip(),
                    personal_top_k=3,  # Reduced for batch processing
                    public_semantic_top_k=5,
                    public_graph_limit=5
                )
                
                response_data['query_index'] = i
                results.append(response_data)
                
            except Exception as e:
                results.append({
                    'query_index': i,
                    'query': query_text,
                    'error': str(e),
                    'generated_at': timezone.now().isoformat()
                })
        
        return Response({
            'batch_id': f"batch_{timezone.now().timestamp()}",
            'total_queries': len(queries),
            'successful_queries': len([r for r in results if 'error' not in r]),
            'failed_queries': len([r for r in results if 'error' in r]),
            'results': results,
            'processed_at': timezone.now().isoformat()
        })
        
    except Exception as e:
        return Response({
            'error': f'Error processing batch queries: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)