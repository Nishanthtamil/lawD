# AI Services - Consolidated hybrid retrieval, document processing, and LLM integration

import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
from functools import lru_cache

from django.conf import settings
from django.core.cache import cache
from sentence_transformers import SentenceTransformer, CrossEncoder
from pymilvus import connections, Collection, utility
import neo4j
import groq
import PyPDF2
import docx
from PIL import Image
import pytesseract

from .models import UserDocument, PublicDocument
from .milvus_manager import MilvusManager
from .neo4j_manager import Neo4jManager

logger = logging.getLogger(__name__)

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class QueryResult:
    """Structured query result"""
    content: str
    score: float
    source: str
    metadata: Dict[str, Any]
    document_id: Optional[int] = None

@dataclass
class ProcessingResult:
    """Document processing result"""
    success: bool
    content: str = ""
    summary: str = ""
    error: str = ""
    metadata: Dict[str, Any] = None

# ============================================================================
# CORE AI SERVICES
# ============================================================================

class AIServiceManager:
    """Centralized AI service management"""
    
    def __init__(self):
        self.embedding_model = None
        self.cross_encoder = None
        self.groq_client = None
        self.milvus_manager = None
        self.neo4j_manager = None
        self._initialized = False
    
    def initialize(self):
        """Initialize all AI services"""
        if self._initialized:
            return
        
        try:
            # Initialize embedding model
            self.embedding_model = SentenceTransformer('all-mpnet-base-v2')
            
            # Initialize cross-encoder for re-ranking
            self.cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            
            # Initialize Groq client
            self.groq_client = groq.Groq(api_key=settings.GROQ_API_KEY)
            
            # Initialize database managers
            self.milvus_manager = MilvusManager()
            self.neo4j_manager = Neo4jManager()
            
            self._initialized = True
            logger.info("AI services initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize AI services: {str(e)}")
            raise

    @lru_cache(maxsize=1000)
    def get_embeddings(self, text: str) -> List[float]:
        """Get embeddings for text with caching"""
        if not self._initialized:
            self.initialize()
        
        cache_key = f"embedding:{hash(text)}"
        cached_embedding = cache.get(cache_key)
        
        if cached_embedding:
            return cached_embedding
        
        embedding = self.embedding_model.encode(text).tolist()
        cache.set(cache_key, embedding, timeout=3600)  # Cache for 1 hour
        return embedding

# Global AI service manager instance
ai_service_manager = AIServiceManager()

# ============================================================================
# DOCUMENT PROCESSING
# ============================================================================

class DocumentProcessor:
    """Unified document processing for all file types"""
    
    @staticmethod
    def extract_text_from_pdf(file_path: str) -> str:
        """Extract text from PDF file"""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text.strip()
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {str(e)}")
            return ""
    
    @staticmethod
    def extract_text_from_docx(file_path: str) -> str:
        """Extract text from DOCX file"""
        try:
            doc = docx.Document(file_path)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting text from DOCX: {str(e)}")
            return ""
    
    @staticmethod
    def extract_text_from_image(file_path: str) -> str:
        """Extract text from image using OCR"""
        try:
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting text from image: {str(e)}")
            return ""
    
    @classmethod
    def process_document(cls, file_path: str, file_type: str) -> ProcessingResult:
        """Process document and extract content"""
        try:
            content = ""
            
            if file_type.lower() == 'pdf':
                content = cls.extract_text_from_pdf(file_path)
            elif file_type.lower() in ['docx', 'doc']:
                content = cls.extract_text_from_docx(file_path)
            elif file_type.lower() in ['jpg', 'jpeg', 'png', 'tiff']:
                content = cls.extract_text_from_image(file_path)
            else:
                return ProcessingResult(
                    success=False,
                    error=f"Unsupported file type: {file_type}"
                )
            
            if not content:
                return ProcessingResult(
                    success=False,
                    error="No text content extracted from document"
                )
            
            # Generate summary
            summary = cls.generate_summary(content)
            
            return ProcessingResult(
                success=True,
                content=content,
                summary=summary,
                metadata={
                    'word_count': len(content.split()),
                    'char_count': len(content),
                    'file_type': file_type
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            return ProcessingResult(
                success=False,
                error=str(e)
            )
    
    @staticmethod
    def generate_summary(content: str, max_length: int = 500) -> str:
        """Generate document summary using Groq"""
        try:
            ai_service_manager.initialize()
            
            # Truncate content if too long
            if len(content) > 4000:
                content = content[:4000] + "..."
            
            response = ai_service_manager.groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a legal document summarizer. Provide a concise, accurate summary of the given document, highlighting key legal points, provisions, and implications."
                    },
                    {
                        "role": "user",
                        "content": f"Please summarize this legal document:\n\n{content}"
                    }
                ],
                model="llama3-8b-8192",
                max_tokens=max_length,
                temperature=0.3
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Error generating summary: {str(e)}")
            return "Summary generation failed"

# ============================================================================
# HYBRID RETRIEVAL SYSTEM
# ============================================================================

class HybridRetriever:
    """Advanced hybrid retrieval combining vector and graph search"""
    
    def __init__(self):
        self.ai_manager = ai_service_manager
    
    def search(self, query: str, user_id: Optional[int] = None, 
               top_k: int = 10, include_public: bool = True) -> List[QueryResult]:
        """Perform hybrid search across vector and graph databases"""
        try:
            self.ai_manager.initialize()
            
            # Get query embedding
            query_embedding = self.ai_manager.get_embeddings(query)
            
            # Parallel search execution
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = []
                
                # Vector search in Milvus
                futures.append(
                    executor.submit(self._vector_search, query_embedding, user_id, top_k, include_public)
                )
                
                # Graph search in Neo4j
                futures.append(
                    executor.submit(self._graph_search, query, user_id, top_k, include_public)
                )
                
                # Keyword search (if needed)
                futures.append(
                    executor.submit(self._keyword_search, query, user_id, top_k, include_public)
                )
                
                # Collect results
                all_results = []
                for future in as_completed(futures):
                    try:
                        results = future.result()
                        all_results.extend(results)
                    except Exception as e:
                        logger.error(f"Search component failed: {str(e)}")
            
            # Re-rank and deduplicate results
            final_results = self._rerank_results(query, all_results, top_k)
            
            return final_results
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {str(e)}")
            return []
    
    def _vector_search(self, query_embedding: List[float], user_id: Optional[int], 
                      top_k: int, include_public: bool) -> List[QueryResult]:
        """Perform vector similarity search in Milvus"""
        try:
            results = []
            
            # Search in user partition if user_id provided
            if user_id:
                user_results = self.ai_manager.milvus_manager.search_user_documents(
                    user_id, query_embedding, top_k
                )
                results.extend([
                    QueryResult(
                        content=result['content'],
                        score=result['score'],
                        source='user_document',
                        metadata=result['metadata'],
                        document_id=result.get('document_id')
                    ) for result in user_results
                ])
            
            # Search in public documents if allowed
            if include_public:
                public_results = self.ai_manager.milvus_manager.search_public_documents(
                    query_embedding, top_k
                )
                results.extend([
                    QueryResult(
                        content=result['content'],
                        score=result['score'],
                        source='public_document',
                        metadata=result['metadata'],
                        document_id=result.get('document_id')
                    ) for result in public_results
                ])
            
            return results
            
        except Exception as e:
            logger.error(f"Vector search failed: {str(e)}")
            return []
    
    def _graph_search(self, query: str, user_id: Optional[int], 
                     top_k: int, include_public: bool) -> List[QueryResult]:
        """Perform graph-based search in Neo4j"""
        try:
            results = self.ai_manager.neo4j_manager.search_documents(
                query, user_id, top_k, include_public
            )
            
            return [
                QueryResult(
                    content=result['content'],
                    score=result['score'],
                    source='graph_search',
                    metadata=result['metadata'],
                    document_id=result.get('document_id')
                ) for result in results
            ]
            
        except Exception as e:
            logger.error(f"Graph search failed: {str(e)}")
            return []
    
    def _keyword_search(self, query: str, user_id: Optional[int], 
                       top_k: int, include_public: bool) -> List[QueryResult]:
        """Perform keyword-based search"""
        try:
            # Simple keyword matching for now
            # This could be enhanced with Elasticsearch or similar
            results = []
            
            # Search user documents
            if user_id:
                user_docs = UserDocument.objects.filter(
                    user_id=user_id,
                    processing_status='completed',
                    content__icontains=query
                )[:top_k//2]
                
                for doc in user_docs:
                    results.append(QueryResult(
                        content=doc.content[:500] + "..." if len(doc.content) > 500 else doc.content,
                        score=0.5,  # Fixed score for keyword matches
                        source='keyword_search',
                        metadata={'title': doc.title, 'type': 'user_document'},
                        document_id=doc.id
                    ))
            
            # Search public documents
            if include_public:
                public_docs = PublicDocument.objects.filter(
                    content__icontains=query
                )[:top_k//2]
                
                for doc in public_docs:
                    results.append(QueryResult(
                        content=doc.content[:500] + "..." if len(doc.content) > 500 else doc.content,
                        score=0.5,
                        source='keyword_search',
                        metadata={'title': doc.title, 'type': 'public_document'},
                        document_id=doc.id
                    ))
            
            return results
            
        except Exception as e:
            logger.error(f"Keyword search failed: {str(e)}")
            return []
    
    def _rerank_results(self, query: str, results: List[QueryResult], top_k: int) -> List[QueryResult]:
        """Re-rank and deduplicate search results"""
        try:
            if not results:
                return []
            
            # Remove duplicates based on content similarity
            unique_results = []
            seen_content = set()
            
            for result in results:
                content_hash = hash(result.content[:100])  # Use first 100 chars for dedup
                if content_hash not in seen_content:
                    seen_content.add(content_hash)
                    unique_results.append(result)
            
            # Re-rank using cross-encoder if available
            if len(unique_results) > 1 and self.ai_manager.cross_encoder:
                try:
                    pairs = [(query, result.content) for result in unique_results]
                    scores = self.ai_manager.cross_encoder.predict(pairs)
                    
                    # Update scores and sort
                    for i, score in enumerate(scores):
                        unique_results[i].score = float(score)
                    
                    unique_results.sort(key=lambda x: x.score, reverse=True)
                    
                except Exception as e:
                    logger.warning(f"Cross-encoder re-ranking failed: {str(e)}")
                    # Fall back to original scores
                    unique_results.sort(key=lambda x: x.score, reverse=True)
            else:
                # Sort by original scores
                unique_results.sort(key=lambda x: x.score, reverse=True)
            
            return unique_results[:top_k]
            
        except Exception as e:
            logger.error(f"Result re-ranking failed: {str(e)}")
            return results[:top_k]

# ============================================================================
# LLM SYNTHESIZER
# ============================================================================

class LLMSynthesizer:
    """Generate responses using retrieved context and LLM"""
    
    def __init__(self):
        self.ai_manager = ai_service_manager
    
    def generate_response(self, query: str, context_results: List[QueryResult], 
                         conversation_history: Optional[List[Dict]] = None) -> str:
        """Generate contextual response using Groq LLM"""
        try:
            self.ai_manager.initialize()
            
            # Prepare context
            context = self._prepare_context(context_results)
            
            # Prepare conversation history
            messages = []
            if conversation_history:
                messages.extend(conversation_history[-5:])  # Last 5 messages for context
            
            # System prompt
            system_prompt = """You are a knowledgeable legal AI assistant specializing in Indian law and constitutional matters. 
            Use the provided context to answer questions accurately and comprehensively. 
            If the context doesn't contain sufficient information, clearly state this limitation.
            Always cite your sources when referencing specific documents or provisions."""
            
            messages.insert(0, {"role": "system", "content": system_prompt})
            
            # Add current query with context
            user_message = f"Question: {query}\n\nContext:\n{context}"
            messages.append({"role": "user", "content": user_message})
            
            # Generate response
            response = self.ai_manager.groq_client.chat.completions.create(
                messages=messages,
                model="llama3-8b-8192",
                max_tokens=1000,
                temperature=0.3
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"LLM response generation failed: {str(e)}")
            return "I apologize, but I'm unable to generate a response at the moment. Please try again later."
    
    def _prepare_context(self, results: List[QueryResult]) -> str:
        """Prepare context from search results"""
        if not results:
            return "No relevant context found."
        
        context_parts = []
        for i, result in enumerate(results[:5], 1):  # Use top 5 results
            source_info = f"Source {i} ({result.source})"
            if result.metadata.get('title'):
                source_info += f" - {result.metadata['title']}"
            
            context_parts.append(f"{source_info}:\n{result.content}\n")
        
        return "\n".join(context_parts)

# ============================================================================
# MAIN QUERY PROCESSOR
# ============================================================================

class QueryProcessor:
    """Main query processing pipeline"""
    
    def __init__(self):
        self.retriever = HybridRetriever()
        self.synthesizer = LLMSynthesizer()
    
    def process_query(self, query: str, user_id: Optional[int] = None, 
                     conversation_history: Optional[List[Dict]] = None,
                     include_public: bool = True, top_k: int = 10) -> Dict[str, Any]:
        """Process complete query pipeline"""
        try:
            # Retrieve relevant documents
            search_results = self.retriever.search(
                query=query,
                user_id=user_id,
                top_k=top_k,
                include_public=include_public
            )
            
            # Generate response
            response = self.synthesizer.generate_response(
                query=query,
                context_results=search_results,
                conversation_history=conversation_history
            )
            
            return {
                'response': response,
                'sources': [
                    {
                        'content': result.content[:200] + "..." if len(result.content) > 200 else result.content,
                        'score': result.score,
                        'source': result.source,
                        'metadata': result.metadata,
                        'document_id': result.document_id
                    } for result in search_results[:3]  # Return top 3 sources
                ],
                'query': query,
                'timestamp': timezone.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Query processing failed: {str(e)}")
            return {
                'response': "I apologize, but I encountered an error while processing your query. Please try again.",
                'sources': [],
                'query': query,
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            }

# Global query processor instance
query_processor = QueryProcessor()