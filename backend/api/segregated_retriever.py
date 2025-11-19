"""
Segregated Hybrid Retrieval System for Legal AI Assistant.
Implements multi-source queries with strict data segregation between personal and public knowledge.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import uuid

from django.conf import settings
from django.core.cache import cache
from sentence_transformers import SentenceTransformer, CrossEncoder
from pymilvus import Collection, connections
import numpy as np

from .milvus_manager import PartitionManager, MilvusConnectionManager
from .neo4j_manager import get_neo4j_manager
from .models import User, UserPartition
from .cache_manager import cache_manager, cache_result
from .performance_monitor import performance_monitor, monitor_performance

logger = logging.getLogger(__name__)


class SegregatedRetriever:
    """
    Manages segregated retrieval across public and personal knowledge planes.
    Ensures strict data segregation while providing intelligent hybrid search.
    """
    
    def __init__(self):
        self.partition_manager = PartitionManager()
        self.neo4j_manager = get_neo4j_manager()
        self.embedding_model = None
        self.cross_encoder = None
        self.public_collection_name = "public_legal_knowledge"
        self.personal_collection_name = "personal_documents"
        self.cache_timeout = 300  # 5 minutes for query results
        
        # Initialize models
        self._initialize_embedding_model()
        self._initialize_cross_encoder()
        
        # Ensure Milvus connection
        MilvusConnectionManager.get_connection()
    
    def _initialize_embedding_model(self):
        """Initialize the sentence transformer model for embeddings"""
        try:
            model_name = getattr(settings, 'EMBEDDING_MODEL', 'all-mpnet-base-v2')
            self.embedding_model = SentenceTransformer(model_name)
            logger.info(f"Initialized embedding model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize embedding model: {e}")
            raise
    
    def _initialize_cross_encoder(self):
        """Initialize the cross-encoder model for re-ranking"""
        try:
            cross_encoder_model = getattr(settings, 'CROSS_ENCODER_MODEL', 'cross-encoder/ms-marco-MiniLM-L-6-v2')
            self.cross_encoder = CrossEncoder(cross_encoder_model)
            logger.info(f"Initialized cross-encoder model: {cross_encoder_model}")
        except Exception as e:
            logger.warning(f"Failed to initialize cross-encoder model: {e}. Re-ranking will be disabled.")
            self.cross_encoder = None
    
    @monitor_performance('personal_query')
    def query_personal_context(self, user_id: str, query: str, top_k: int = 5, offset: int = 0, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Retrieve personal context from user's partition with strict filtering.
        
        Args:
            user_id: UUID string of the user
            query: Search query text
            top_k: Number of results to return
            offset: Offset for pagination
            filters: Additional filters for the query
            
        Returns:
            List of personal document contexts with metadata
        """
        import time
        start_time = time.time()
        
        try:
            # Validate user partition access
            partition_name = self.partition_manager.get_user_partition_name(user_id)
            
            if not self.partition_manager.validate_partition_access(user_id, partition_name):
                logger.warning(f"Access denied to partition {partition_name} for user {user_id}")
                return []
            
            # Check cache first
            cache_key = f"personal_query_{user_id}_{hash(query)}_{top_k}_{offset}"
            cached_result = cache_manager.get_cached_query_result(query, user_id)
            if cached_result:
                logger.debug(f"Retrieved personal context from cache for user {user_id}")
                return cached_result.get('results', [])
            
            # Generate query embedding
            query_embedding = self._generate_query_embedding(query)
            if query_embedding is None:
                return []
            
            # Search in user's partition with pagination
            results = self._search_personal_partition(user_id, partition_name, query_embedding, top_k, offset, filters)
            
            # Cache results
            result_data = {
                'results': results,
                'total_count': len(results),
                'execution_time': time.time() - start_time,
                'user_id': user_id,
                'query': query
            }
            cache_manager.cache_query_result(query, user_id, result_data)
            
            logger.info(f"Retrieved {len(results)} personal contexts for user {user_id}")
            return results
            
        except Exception as e:
            logger.error(f"Error querying personal context for user {user_id}: {e}")
            return []
    
    @monitor_performance('public_semantic_query')
    def query_public_semantic(self, query: str, top_k: int = 10, offset: int = 0, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Retrieve public legal knowledge using semantic search.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            offset: Offset for pagination
            filters: Additional filters for the query
            
        Returns:
            List of public document contexts with metadata
        """
        try:
            # Check cache first
            cached_result = cache_manager.get_cached_public_knowledge(query)
            if cached_result:
                logger.debug("Retrieved public semantic results from cache")
                return cached_result
            
            # Generate query embedding
            query_embedding = self._generate_query_embedding(query)
            if query_embedding is None:
                return []
            
            # Search public collection with pagination
            results = self._search_public_collection(query_embedding, top_k, offset, filters)
            
            # Cache results (longer timeout for public data)
            cache_manager.cache_public_knowledge(query, results)
            
            logger.info(f"Retrieved {len(results)} public semantic contexts")
            return results
            
        except Exception as e:
            logger.error(f"Error querying public semantic context: {e}")
            return []
    
    def query_public_graph(self, entities: List[str], query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve public legal knowledge using graph relationships.
        
        Args:
            entities: List of legal entities to search for
            query: Original query for context
            limit: Maximum number of results
            
        Returns:
            List of graph-based contexts with relationships
        """
        try:
            # Check cache first
            entities_key = "_".join(sorted(entities))
            cache_key = f"public_graph_{hash(entities_key)}_{hash(query)}_{limit}"
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.debug("Retrieved public graph results from cache")
                return cached_result
            
            results = []
            
            # Extract legal entities from query if not provided
            if not entities:
                entities = self._extract_legal_entities(query)
            
            # Query Neo4j for each entity
            for entity in entities[:5]:  # Limit to 5 entities to prevent excessive queries
                entity_results = self._query_graph_for_entity(entity, limit // len(entities) + 1)
                results.extend(entity_results)
            
            # Remove duplicates and limit results
            seen_ids = set()
            unique_results = []
            for result in results:
                result_id = result.get('id', result.get('entity_id', ''))
                if result_id and result_id not in seen_ids:
                    seen_ids.add(result_id)
                    unique_results.append(result)
                    if len(unique_results) >= limit:
                        break
            
            # Cache results
            cache.set(cache_key, unique_results, timeout=self.cache_timeout * 4)  # 20 minutes
            
            logger.info(f"Retrieved {len(unique_results)} public graph contexts for entities: {entities}")
            return unique_results
            
        except Exception as e:
            logger.error(f"Error querying public graph context: {e}")
            return []
    
    def _generate_query_embedding(self, query: str) -> Optional[List[float]]:
        """Generate embedding for search query"""
        try:
            if not self.embedding_model:
                logger.error("Embedding model not initialized")
                return None
            
            embedding = self.embedding_model.encode(query, convert_to_tensor=False)
            return embedding.tolist()
            
        except Exception as e:
            logger.error(f"Error generating query embedding: {e}")
            return None
    
    def _search_personal_partition(self, user_id: str, partition_name: str, 
                                 query_embedding: List[float], top_k: int, offset: int = 0, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Search user's personal partition in Milvus"""
        try:
            # Get personal collection
            collection = Collection(self.personal_collection_name)
            
            # Ensure collection is loaded
            if not collection.has_index():
                logger.warning(f"Personal collection {self.personal_collection_name} has no index")
                return []
            
            collection.load()
            
            # Search parameters
            search_params = {
                "metric_type": "COSINE",
                "params": {"nprobe": 10}
            }
            
            # Build expression with additional filters
            expr = f"user_id == '{user_id}'"
            if filters:
                for key, value in filters.items():
                    if key != 'user_id':  # Don't override user_id filter
                        expr += f" and {key} == '{value}'"
            
            # Search with partition filter and pagination
            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                offset=offset,
                partition_names=[partition_name],
                expr=expr,
                output_fields=["document_id", "chunk_id", "text_content", "user_id", "created_at"]
            )
            
            # Process results
            contexts = []
            for hits in results:
                for hit in hits:
                    # Verify user ID matches (additional security check)
                    if hit.entity.get('user_id') != user_id:
                        logger.warning(f"Security violation: Found document for different user in partition {partition_name}")
                        continue
                    
                    context = {
                        'source': 'personal',
                        'document_id': hit.entity.get('document_id'),
                        'chunk_id': hit.entity.get('chunk_id'),
                        'text': hit.entity.get('text_content', ''),
                        'score': float(hit.score),
                        'user_id': hit.entity.get('user_id'),
                        'created_at': hit.entity.get('created_at'),
                        'partition_name': partition_name
                    }
                    contexts.append(context)
            
            return contexts
            
        except Exception as e:
            logger.error(f"Error searching personal partition {partition_name}: {e}")
            return []
    
    def _search_public_collection(self, query_embedding: List[float], top_k: int) -> List[Dict[str, Any]]:
        """Search public legal knowledge collection in Milvus"""
        try:
            # Get public collection
            collection = Collection(self.public_collection_name)
            
            # Ensure collection is loaded
            if not collection.has_index():
                logger.warning(f"Public collection {self.public_collection_name} has no index")
                return []
            
            collection.load()
            
            # Search parameters
            search_params = {
                "metric_type": "COSINE",
                "params": {"nprobe": 16}
            }
            
            # Search public collection
            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                output_fields=["document_id", "chunk_id", "text_content", "document_type", "legal_domain", "created_at"]
            )
            
            # Process results
            contexts = []
            for hits in results:
                for hit in hits:
                    context = {
                        'source': 'public',
                        'document_id': hit.entity.get('document_id'),
                        'chunk_id': hit.entity.get('chunk_id'),
                        'text': hit.entity.get('text_content', ''),
                        'score': float(hit.score),
                        'document_type': hit.entity.get('document_type'),
                        'legal_domain': hit.entity.get('legal_domain'),
                        'created_at': hit.entity.get('created_at')
                    }
                    contexts.append(context)
            
            return contexts
            
        except Exception as e:
            logger.error(f"Error searching public collection: {e}")
            return []
    
    def _extract_legal_entities(self, query: str) -> List[str]:
        """Extract potential legal entities from query text"""
        try:
            # Simple entity extraction (in production, use NER model)
            entities = []
            
            # Look for article numbers
            import re
            article_pattern = r'\b[Aa]rticle\s+(\d+)\b'
            articles = re.findall(article_pattern, query)
            entities.extend([f"Article {num}" for num in articles])
            
            # Look for case names (simplified)
            case_pattern = r'\b([A-Z][a-z]+\s+v\.?\s+[A-Z][a-z]+)\b'
            cases = re.findall(case_pattern, query)
            entities.extend(cases)
            
            # Look for common legal terms
            legal_terms = [
                'fundamental rights', 'directive principles', 'emergency provisions',
                'parliament', 'supreme court', 'high court', 'president', 'governor',
                'constitution', 'amendment', 'equality', 'liberty', 'justice'
            ]
            
            query_lower = query.lower()
            for term in legal_terms:
                if term in query_lower:
                    entities.append(term)
            
            return list(set(entities))  # Remove duplicates
            
        except Exception as e:
            logger.error(f"Error extracting legal entities: {e}")
            return []
    
    def _query_graph_for_entity(self, entity: str, limit: int) -> List[Dict[str, Any]]:
        """Query Neo4j graph for specific entity and its relationships"""
        try:
            # Search for entities matching the query
            entity_results = self.neo4j_manager.query_entities(
                filters={'name': entity},
                limit=limit
            )
            
            contexts = []
            
            # Process entity results
            for entity_data in entity_results:
                context = {
                    'source': 'public_graph',
                    'entity_id': entity_data.get('id'),
                    'entity_type': entity_data.get('entity_type', 'unknown'),
                    'name': entity_data.get('name', entity_data.get('title', '')),
                    'content': entity_data.get('content', entity_data.get('summary', '')),
                    'text': self._format_entity_text(entity_data),
                    'score': 1.0,  # Graph results get base score
                    'metadata': entity_data
                }
                contexts.append(context)
                
                # Get related entities through relationships
                if len(contexts) < limit:
                    related_contexts = self._get_related_entities(entity_data.get('id'), limit - len(contexts))
                    contexts.extend(related_contexts)
            
            return contexts[:limit]
            
        except Exception as e:
            logger.error(f"Error querying graph for entity {entity}: {e}")
            return []
    
    def _get_related_entities(self, entity_id: str, limit: int) -> List[Dict[str, Any]]:
        """Get entities related to the given entity through relationships"""
        try:
            relationships = self.neo4j_manager.query_relationships(
                source_id=entity_id,
                limit=limit
            )
            
            contexts = []
            for rel_data in relationships:
                target_entity = rel_data.get('target', {})
                relationship = rel_data.get('relationship', {})
                
                context = {
                    'source': 'public_graph_related',
                    'entity_id': target_entity.get('id'),
                    'entity_type': target_entity.get('entity_type', 'unknown'),
                    'name': target_entity.get('name', target_entity.get('title', '')),
                    'content': target_entity.get('content', target_entity.get('summary', '')),
                    'text': self._format_entity_text(target_entity),
                    'score': 0.8,  # Related entities get slightly lower score
                    'relationship_type': relationship.get('type', 'RELATED'),
                    'relationship_context': relationship.get('context', ''),
                    'metadata': target_entity
                }
                contexts.append(context)
            
            return contexts
            
        except Exception as e:
            logger.error(f"Error getting related entities for {entity_id}: {e}")
            return []
    
    def _format_entity_text(self, entity_data: Dict[str, Any]) -> str:
        """Format entity data into readable text for context"""
        try:
            entity_type = entity_data.get('entity_type', 'Entity')
            name = entity_data.get('name', entity_data.get('title', 'Unknown'))
            content = entity_data.get('content', entity_data.get('summary', ''))
            
            # Format based on entity type
            if entity_type == 'articles':
                number = entity_data.get('number', '')
                part = entity_data.get('part', '')
                chapter = entity_data.get('chapter', '')
                
                text = f"Article {number}"
                if part:
                    text += f" (Part {part})"
                if chapter:
                    text += f" (Chapter {chapter})"
                text += f": {name}"
                if content:
                    text += f"\n{content}"
                    
            elif entity_type == 'cases':
                citation = entity_data.get('citation', '')
                court = entity_data.get('court', '')
                date = entity_data.get('date', '')
                
                text = f"Case: {name}"
                if citation:
                    text += f" ({citation})"
                if court:
                    text += f"\nCourt: {court}"
                if date:
                    text += f"\nDate: {date}"
                if content:
                    text += f"\nSummary: {content}"
                    
            elif entity_type == 'judges':
                court = entity_data.get('court', '')
                tenure = entity_data.get('tenure_start', '')
                
                text = f"Judge: {name}"
                if court:
                    text += f"\nCourt: {court}"
                if tenure:
                    text += f"\nTenure: {tenure}"
                if content:
                    text += f"\nContext: {content}"
                    
            else:
                text = f"{entity_type.title()}: {name}"
                if content:
                    text += f"\n{content}"
            
            return text
            
        except Exception as e:
            logger.error(f"Error formatting entity text: {e}")
            return entity_data.get('name', entity_data.get('title', 'Unknown entity'))
    
    def get_retrieval_stats(self, user_id: str) -> Dict[str, Any]:
        """Get statistics about retrieval performance for a user"""
        try:
            stats = {
                'user_id': user_id,
                'partition_exists': False,
                'personal_documents': 0,
                'public_collection_size': 0,
                'graph_entities': 0,
                'cache_hits': 0
            }
            
            # Check user partition
            try:
                user = User.objects.get(id=user_id)
                user_partition = UserPartition.objects.get(user=user)
                stats['partition_exists'] = True
                stats['personal_documents'] = user_partition.document_count
                stats['total_embeddings'] = user_partition.total_embeddings
            except (User.DoesNotExist, UserPartition.DoesNotExist):
                pass
            
            # Get public collection stats
            try:
                collection = Collection(self.public_collection_name)
                stats['public_collection_size'] = collection.num_entities
            except Exception:
                pass
            
            # Get graph stats
            try:
                graph_stats = self.neo4j_manager.get_database_stats()
                stats['graph_entities'] = graph_stats.get('total_entities', 0)
                stats['graph_relationships'] = graph_stats.get('total_relationships', 0)
            except Exception:
                pass
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting retrieval stats: {e}")
            return {'error': str(e)}
    
    def hybrid_search_and_synthesize(self, user_id: str, query: str, 
                                   personal_top_k: int = 5, 
                                   public_semantic_top_k: int = 10,
                                   public_graph_limit: int = 10) -> Dict[str, Any]:
        """
        Orchestrate the complete hybrid search and synthesis pipeline.
        
        Args:
            user_id: UUID string of the requesting user
            query: Search query text
            personal_top_k: Number of personal context results
            public_semantic_top_k: Number of public semantic results
            public_graph_limit: Number of public graph results
            
        Returns:
            Complete response with synthesized answer and citations
        """
        try:
            from .llm_synthesizer import LLMSynthesizer
            
            # Step 1: Retrieve contexts from all sources
            logger.info(f"Starting hybrid search for user {user_id}: {query}")
            
            # Query personal context with strict user filtering
            personal_contexts = self.query_personal_context(user_id, query, personal_top_k)
            
            # Query public semantic context
            public_semantic_contexts = self.query_public_semantic(query, public_semantic_top_k)
            
            # Extract entities and query graph context
            entities = self._extract_legal_entities(query)
            public_graph_contexts = self.query_public_graph(entities, query, public_graph_limit)
            
            # Step 2: Combine and re-rank contexts
            combined_contexts = self.combine_contexts(
                query, 
                personal_contexts, 
                public_semantic_contexts, 
                public_graph_contexts
            )
            
            # Step 3: Synthesize response using LLM
            synthesizer = LLMSynthesizer()
            final_response = synthesizer.synthesize_response(query, combined_contexts, user_id)
            
            # Add retrieval metadata
            final_response['retrieval_metadata'] = {
                'personal_contexts_found': len(personal_contexts),
                'public_semantic_contexts_found': len(public_semantic_contexts),
                'public_graph_contexts_found': len(public_graph_contexts),
                'total_contexts_processed': combined_contexts.get('total_contexts', 0),
                'contexts_used_in_response': len(combined_contexts.get('contexts', [])),
                'search_completed_at': datetime.now().isoformat()
            }
            
            logger.info(f"Completed hybrid search and synthesis for user {user_id}")
            return final_response
            
        except Exception as e:
            logger.error(f"Error in hybrid search and synthesis: {e}")
            return {
                'query': query,
                'response': f"I apologize, but I encountered an error processing your query. Please try again or contact support if the issue persists.",
                'citations': [],
                'error': str(e),
                'generated_at': datetime.now().isoformat()
            }
    
    def combine_contexts(self, query: str, personal_contexts: List[Dict[str, Any]], 
                        public_semantic_contexts: List[Dict[str, Any]], 
                        public_graph_contexts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Combine and merge contexts from personal and public sources.
        
        Args:
            query: Original search query
            personal_contexts: Results from personal document search
            public_semantic_contexts: Results from public semantic search
            public_graph_contexts: Results from public graph search
            
        Returns:
            Dictionary containing combined and processed contexts
        """
        try:
            # Combine all contexts
            all_contexts = []
            
            # Add personal contexts with source priority
            for ctx in personal_contexts:
                ctx['source_priority'] = 1.0  # Highest priority for personal documents
                ctx['context_type'] = 'personal'
                all_contexts.append(ctx)
            
            # Add public semantic contexts
            for ctx in public_semantic_contexts:
                ctx['source_priority'] = 0.8  # High priority for semantic matches
                ctx['context_type'] = 'public_semantic'
                all_contexts.append(ctx)
            
            # Add public graph contexts
            for ctx in public_graph_contexts:
                ctx['source_priority'] = 0.7  # Medium priority for graph relationships
                ctx['context_type'] = 'public_graph'
                all_contexts.append(ctx)
            
            # Remove duplicates based on content similarity
            deduplicated_contexts = self._deduplicate_contexts(all_contexts)
            
            # Re-rank contexts using cross-encoder
            reranked_contexts = self._rerank_contexts(query, deduplicated_contexts)
            
            # Apply relevance filtering
            filtered_contexts = self._filter_by_relevance(reranked_contexts)
            
            # Organize results by source
            combined_result = {
                'query': query,
                'total_contexts': len(filtered_contexts),
                'personal_count': len([c for c in filtered_contexts if c['context_type'] == 'personal']),
                'public_semantic_count': len([c for c in filtered_contexts if c['context_type'] == 'public_semantic']),
                'public_graph_count': len([c for c in filtered_contexts if c['context_type'] == 'public_graph']),
                'contexts': filtered_contexts,
                'has_personal_context': any(c['context_type'] == 'personal' for c in filtered_contexts),
                'has_public_context': any(c['context_type'].startswith('public') for c in filtered_contexts)
            }
            
            logger.info(f"Combined {len(all_contexts)} contexts into {len(filtered_contexts)} final contexts")
            return combined_result
            
        except Exception as e:
            logger.error(f"Error combining contexts: {e}")
            return {
                'query': query,
                'total_contexts': 0,
                'contexts': [],
                'error': str(e)
            }
    
    def _deduplicate_contexts(self, contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicate contexts based on content similarity.
        
        Args:
            contexts: List of context dictionaries
            
        Returns:
            List of deduplicated contexts
        """
        try:
            if not contexts:
                return []
            
            deduplicated = []
            seen_texts = set()
            
            for context in contexts:
                text = context.get('text', '').strip()
                
                # Skip empty texts
                if not text:
                    continue
                
                # Simple deduplication based on exact text match
                text_hash = hash(text.lower())
                if text_hash in seen_texts:
                    continue
                
                # More sophisticated similarity check for near-duplicates
                is_duplicate = False
                for existing_context in deduplicated:
                    existing_text = existing_context.get('text', '').strip()
                    
                    # Check for substantial overlap (simple approach)
                    if self._texts_are_similar(text, existing_text):
                        # Keep the one with higher priority/score
                        if (context.get('source_priority', 0) > existing_context.get('source_priority', 0) or
                            (context.get('source_priority', 0) == existing_context.get('source_priority', 0) and
                             context.get('score', 0) > existing_context.get('score', 0))):
                            # Replace existing with current
                            deduplicated.remove(existing_context)
                            break
                        else:
                            # Skip current context
                            is_duplicate = True
                            break
                
                if not is_duplicate:
                    seen_texts.add(text_hash)
                    deduplicated.append(context)
            
            logger.debug(f"Deduplicated {len(contexts)} contexts to {len(deduplicated)}")
            return deduplicated
            
        except Exception as e:
            logger.error(f"Error deduplicating contexts: {e}")
            return contexts
    
    def _texts_are_similar(self, text1: str, text2: str, threshold: float = 0.8) -> bool:
        """
        Check if two texts are similar based on word overlap.
        
        Args:
            text1: First text
            text2: Second text
            threshold: Similarity threshold (0-1)
            
        Returns:
            True if texts are similar above threshold
        """
        try:
            # Simple word-based similarity
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())
            
            if not words1 or not words2:
                return False
            
            intersection = words1.intersection(words2)
            union = words1.union(words2)
            
            similarity = len(intersection) / len(union) if union else 0
            return similarity >= threshold
            
        except Exception as e:
            logger.error(f"Error calculating text similarity: {e}")
            return False
    
    def _rerank_contexts(self, query: str, contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Re-rank contexts using cross-encoder for improved relevance.
        
        Args:
            query: Original search query
            contexts: List of contexts to re-rank
            
        Returns:
            List of re-ranked contexts with updated scores
        """
        try:
            if not contexts or not self.cross_encoder:
                # If no cross-encoder, sort by existing scores and source priority
                return sorted(contexts, 
                            key=lambda x: (x.get('source_priority', 0), x.get('score', 0)), 
                            reverse=True)
            
            # Prepare query-context pairs for cross-encoder
            query_context_pairs = []
            for context in contexts:
                text = context.get('text', '')
                if text:
                    query_context_pairs.append([query, text])
            
            if not query_context_pairs:
                return contexts
            
            # Get cross-encoder scores
            cross_encoder_scores = self.cross_encoder.predict(query_context_pairs)
            
            # Update contexts with cross-encoder scores
            for i, context in enumerate(contexts):
                if i < len(cross_encoder_scores):
                    # Combine original score with cross-encoder score
                    original_score = context.get('score', 0)
                    cross_score = float(cross_encoder_scores[i])
                    source_priority = context.get('source_priority', 0)
                    
                    # Weighted combination: 40% original, 40% cross-encoder, 20% source priority
                    combined_score = (0.4 * original_score + 
                                    0.4 * cross_score + 
                                    0.2 * source_priority)
                    
                    context['cross_encoder_score'] = cross_score
                    context['combined_score'] = combined_score
                else:
                    context['cross_encoder_score'] = 0.0
                    context['combined_score'] = context.get('score', 0) * 0.6 + context.get('source_priority', 0) * 0.4
            
            # Sort by combined score
            reranked = sorted(contexts, key=lambda x: x.get('combined_score', 0), reverse=True)
            
            logger.debug(f"Re-ranked {len(contexts)} contexts using cross-encoder")
            return reranked
            
        except Exception as e:
            logger.error(f"Error re-ranking contexts: {e}")
            # Fallback to original scoring
            return sorted(contexts, 
                        key=lambda x: (x.get('source_priority', 0), x.get('score', 0)), 
                        reverse=True)
    
    def _filter_by_relevance(self, contexts: List[Dict[str, Any]], 
                           min_score: float = 0.1, max_contexts: int = 15) -> List[Dict[str, Any]]:
        """
        Filter contexts by relevance score and limit total number.
        
        Args:
            contexts: List of contexts to filter
            min_score: Minimum relevance score threshold
            max_contexts: Maximum number of contexts to return
            
        Returns:
            List of filtered contexts
        """
        try:
            if not contexts:
                return []
            
            # Filter by minimum score
            filtered = []
            for context in contexts:
                score = context.get('combined_score', context.get('score', 0))
                
                # Always include personal contexts (user's own documents)
                if context.get('context_type') == 'personal':
                    filtered.append(context)
                # For public contexts, apply score threshold
                elif score >= min_score:
                    filtered.append(context)
            
            # Limit total number of contexts
            if len(filtered) > max_contexts:
                # Ensure we keep some personal contexts if they exist
                personal_contexts = [c for c in filtered if c.get('context_type') == 'personal']
                public_contexts = [c for c in filtered if c.get('context_type') != 'personal']
                
                # Reserve space for personal contexts
                personal_limit = min(len(personal_contexts), max_contexts // 3)
                public_limit = max_contexts - personal_limit
                
                filtered = personal_contexts[:personal_limit] + public_contexts[:public_limit]
            
            logger.debug(f"Filtered to {len(filtered)} relevant contexts")
            return filtered
            
        except Exception as e:
            logger.error(f"Error filtering contexts by relevance: {e}")
            return contexts[:max_contexts]  # Fallback to simple truncation    

    def get_personal_document_count(self, user_id: str) -> int:
        """
        Get total count of documents in user's personal partition.
        
        Args:
            user_id: User ID
            
        Returns:
            Total document count
        """
        try:
            # Check cache first
            cache_key = f"personal_doc_count_{user_id}"
            cached_count = cache_manager.get(cache_key)
            if cached_count is not None:
                return cached_count
            
            # Get from database
            try:
                user = User.objects.get(id=user_id)
                user_partition = UserPartition.objects.get(user=user)
                count = user_partition.document_count
            except (User.DoesNotExist, UserPartition.DoesNotExist):
                count = 0
            
            # Cache for 10 minutes
            cache_manager.set(cache_key, count, 600)
            return count
            
        except Exception as e:
            logger.error(f"Error getting personal document count for user {user_id}: {e}")
            return 0
    
    def get_public_document_count(self) -> int:
        """
        Get total count of documents in public collection.
        
        Returns:
            Total public document count
        """
        try:
            # Check cache first
            cache_key = "public_doc_count"
            cached_count = cache_manager.get(cache_key)
            if cached_count is not None:
                return cached_count
            
            # Get from Milvus
            try:
                collection = Collection(self.public_collection_name)
                count = collection.num_entities
            except Exception:
                count = 0
            
            # Cache for 30 minutes
            cache_manager.set(cache_key, count, 1800)
            return count
            
        except Exception as e:
            logger.error(f"Error getting public document count: {e}")
            return 0
    
    def _search_public_collection(self, query_embedding: List[float], top_k: int, offset: int = 0, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Search public collection with pagination support.
        
        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            offset: Offset for pagination
            filters: Additional filters
            
        Returns:
            List of search results
        """
        try:
            # Get public collection
            collection = Collection(self.public_collection_name)
            
            # Ensure collection is loaded
            if not collection.has_index():
                logger.warning(f"Public collection {self.public_collection_name} has no index")
                return []
            
            collection.load()
            
            # Search parameters
            search_params = {
                "metric_type": "COSINE",
                "params": {"nprobe": 10}
            }
            
            # Build filter expression
            expr = None
            if filters:
                expr_parts = []
                for key, value in filters.items():
                    expr_parts.append(f"{key} == '{value}'")
                if expr_parts:
                    expr = " and ".join(expr_parts)
            
            # Search with pagination
            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                offset=offset,
                expr=expr,
                output_fields=["document_id", "chunk_id", "text_content", "document_type", "legal_domain", "created_at"]
            )
            
            # Process results
            contexts = []
            for hits in results:
                for hit in hits:
                    context = {
                        'source': 'public_semantic',
                        'document_id': hit.entity.get('document_id'),
                        'chunk_id': hit.entity.get('chunk_id'),
                        'text': hit.entity.get('text_content', ''),
                        'score': float(hit.score),
                        'document_type': hit.entity.get('document_type'),
                        'legal_domain': hit.entity.get('legal_domain'),
                        'created_at': hit.entity.get('created_at')
                    }
                    contexts.append(context)
            
            return contexts
            
        except Exception as e:
            logger.error(f"Error searching public collection: {e}")
            return []