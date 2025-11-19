import logging
from typing import List, Dict, Any
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

class HybridRetriever:
    """
    Simplified hybrid retrieval system for document indexing and search
    """
    
    def __init__(self):
        self.cache_timeout = 3600  # 1 hour
    
    def index_document(self, document_id: int, content: str, title: str) -> bool:
        """
        Index document content for search
        """
        try:
            # Create document index entry
            doc_data = {
                'id': document_id,
                'title': title,
                'content': content[:5000],  # Limit content size
                'indexed_at': str(timezone.now())
            }
            
            # Cache the document for search
            cache_key = f"indexed_doc_{document_id}"
            cache.set(cache_key, doc_data, timeout=86400)  # 24 hours
            
            # Add to search index (simplified - in production use proper search engine)
            search_index_key = "document_search_index"
            current_index = cache.get(search_index_key, [])
            
            # Remove existing entry if present
            current_index = [doc for doc in current_index if doc['id'] != document_id]
            
            # Add new entry
            current_index.append({
                'id': document_id,
                'title': title,
                'content_preview': content[:200]
            })
            
            # Keep only last 100 documents in index
            if len(current_index) > 100:
                current_index = current_index[-100:]
            
            cache.set(search_index_key, current_index, timeout=86400)
            
            logger.info(f"Indexed document {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to index document {document_id}: {str(e)}")
            return False
    
    def search_documents(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search indexed documents
        """
        try:
            search_index_key = "document_search_index"
            document_index = cache.get(search_index_key, [])
            
            if not document_index:
                return []
            
            # Simple text search (in production use proper search algorithms)
            query_lower = query.lower()
            results = []
            
            for doc in document_index:
                title_match = query_lower in doc['title'].lower()
                content_match = query_lower in doc['content_preview'].lower()
                
                if title_match or content_match:
                    score = 2 if title_match else 1
                    results.append({
                        'document_id': doc['id'],
                        'title': doc['title'],
                        'preview': doc['content_preview'],
                        'score': score
                    })
            
            # Sort by score and limit results
            results.sort(key=lambda x: x['score'], reverse=True)
            return results[:limit]
            
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {str(e)}")
            return []
    
    def get_document_content(self, document_id: int) -> Dict[str, Any]:
        """
        Retrieve full document content from cache
        """
        try:
            cache_key = f"indexed_doc_{document_id}"
            doc_data = cache.get(cache_key)
            
            if doc_data:
                return doc_data
            
            # If not in cache, try to load from database
            from .models import UserDocument
            try:
                document = UserDocument.objects.get(id=document_id)
                if document.processing_status == 'completed':
                    return {
                        'id': document_id,
                        'title': document.title,
                        'content': document.summary or "No content available",
                        'indexed_at': str(document.processed_at or document.uploaded_at)
                    }
            except UserDocument.DoesNotExist:
                pass
            
            return {}
            
        except Exception as e:
            logger.error(f"Failed to get document content for {document_id}: {str(e)}")
            return {}
    
    def remove_document(self, document_id: int) -> bool:
        """
        Remove document from search index
        """
        try:
            # Remove from cache
            cache_key = f"indexed_doc_{document_id}"
            cache.delete(cache_key)
            
            # Remove from search index
            search_index_key = "document_search_index"
            current_index = cache.get(search_index_key, [])
            updated_index = [doc for doc in current_index if doc['id'] != document_id]
            cache.set(search_index_key, updated_index, timeout=86400)
            
            logger.info(f"Removed document {document_id} from index")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove document {document_id}: {str(e)}")
            return False