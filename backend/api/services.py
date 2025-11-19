# Consolidated Services - All business logic and AI services

import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import tempfile
import hashlib

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from sentence_transformers import SentenceTransformer, CrossEncoder
from pymilvus import connections, Collection, utility
import neo4j
import groq
import PyPDF2
import docx
from PIL import Image
import pytesseract
from twilio.rest import Client
import random
import string

from .models import User, OTP, ChatSession, ChatMessage, UserDocument, PublicDocument
from .database import DatabaseManager

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
# AUTHENTICATION SERVICE
# ============================================================================

class AuthService:
    """Consolidated authentication service"""
    
    @staticmethod
    def send_otp(phone_number: str, action: str = 'login') -> Dict[str, Any]:
        """Send OTP to phone number"""
        try:
            # Generate OTP
            otp_code = ''.join(random.choices(string.digits, k=6))
            
            # Set expiration (5 minutes)
            expires_at = timezone.now() + timezone.timedelta(minutes=5)
            
            # Save OTP
            OTP.objects.filter(phone_number=phone_number, is_verified=False).delete()
            otp_obj = OTP.objects.create(
                phone_number=phone_number,
                otp=otp_code,
                expires_at=expires_at
            )
            
            # Send via Twilio
            if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                message = client.messages.create(
                    body=f"Your Legal Assistant verification code is: {otp_code}",
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=phone_number
                )
                logger.info(f"OTP sent to {phone_number}: {message.sid}")
            else:
                # Development mode - log OTP
                logger.info(f"Development OTP for {phone_number}: {otp_code}")
            
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Failed to send OTP: {str(e)}")
            return {'success': False, 'error': 'Failed to send OTP'}
    
    @staticmethod
    def verify_otp(phone_number: str, otp_code: str) -> Dict[str, Any]:
        """Verify OTP and authenticate user"""
        try:
            # Find valid OTP
            otp_obj = OTP.objects.filter(
                phone_number=phone_number,
                otp=otp_code,
                is_verified=False
            ).first()
            
            if not otp_obj or not otp_obj.is_valid():
                return {'success': False, 'error': 'Invalid or expired OTP'}
            
            # Mark OTP as verified
            otp_obj.is_verified = True
            otp_obj.save()
            
            # Get or create user
            user, created = User.objects.get_or_create(
                phone_number=phone_number,
                defaults={'is_verified': True}
            )
            
            if not created:
                user.is_verified = True
                user.last_login = timezone.now()
                user.save()
            
            # Generate tokens
            refresh = RefreshToken.for_user(user)
            
            return {
                'success': True,
                'user': user,
                'access_token': str(refresh.access_token),
                'refresh_token': str(refresh)
            }
            
        except Exception as e:
            logger.error(f"OTP verification failed: {str(e)}")
            return {'success': False, 'error': 'Verification failed'}


# ============================================================================
# AI SERVICE
# ============================================================================

class AIService:
    """Consolidated AI and query processing service"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self._embedding_model = None
        self._cross_encoder = None
        self._llm = None
    
    @property
    def embedding_model(self):
        """Lazy load embedding model"""
        if self._embedding_model is None:
            self._embedding_model = SentenceTransformer('all-mpnet-base-v2')
        return self._embedding_model
    
    @property
    def cross_encoder(self):
        """Lazy load cross encoder"""
        if self._cross_encoder is None:
            self._cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        return self._cross_encoder
    
    @property
    def llm(self):
        """Lazy load LLM"""
        if self._llm is None:
            self._llm = groq.Groq(api_key=settings.GROQ_API_KEY)
        return self._llm
    
    def process_hybrid_query(self, query: str, user: User, include_public: bool = True, top_k: int = 10) -> Dict[str, Any]:
        """Process hybrid query combining vector and graph search"""
        try:
            # Generate query embedding
            query_embedding = self.embedding_model.encode([query])[0].tolist()
            
            # Vector search in Milvus
            vector_results = self.db_manager.search_vectors(
                query_embedding=query_embedding,
                user=user,
                include_public=include_public,
                top_k=top_k * 2  # Get more for re-ranking
            )
            
            # Graph search in Neo4j
            graph_results = self.db_manager.search_graph(
                query=query,
                user=user,
                include_public=include_public,
                top_k=top_k
            )
            
            # Combine and re-rank results
            combined_results = self._combine_and_rerank(
                query, vector_results, graph_results, top_k
            )
            
            # Generate response using LLM
            response = self._generate_response(query, combined_results)
            
            return {
                'response': response,
                'sources': combined_results[:5],  # Top 5 sources
                'total_results': len(combined_results),
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Hybrid query processing failed: {str(e)}")
            return {
                'error': 'Query processing failed',
                'status': 'error'
            }
    
    def process_chat_query(self, message: str, user: User, session_id: str = None) -> Dict[str, Any]:
        """Process conversational query with context"""
        try:
            # Get conversation history
            conversation_history = []
            if session_id:
                session = ChatSession.objects.filter(id=session_id, user=user).first()
                if session:
                    recent_messages = session.messages.order_by('-created_at')[:10]
                    conversation_history = [
                        {'role': msg.role, 'content': msg.content}
                        for msg in reversed(recent_messages)
                    ]
            
            # Process query with context
            result = self.process_hybrid_query(message, user)
            
            if result.get('status') == 'success':
                # Save message to session
                if session_id:
                    session = ChatSession.objects.get(id=session_id, user=user)
                    
                    # Save user message
                    ChatMessage.objects.create(
                        session=session,
                        role='user',
                        content=message
                    )
                    
                    # Save assistant response
                    ChatMessage.objects.create(
                        session=session,
                        role='assistant',
                        content=result['response']
                    )
                    
                    # Update session timestamp
                    session.updated_at = timezone.now()
                    session.save()
            
            return result
            
        except Exception as e:
            logger.error(f"Chat query processing failed: {str(e)}")
            return {
                'error': 'Chat processing failed',
                'status': 'error'
            }
    
    def _combine_and_rerank(self, query: str, vector_results: List, graph_results: List, top_k: int) -> List[QueryResult]:
        """Combine vector and graph results and re-rank using cross-encoder"""
        try:
            # Combine results
            all_results = []
            
            # Add vector results
            for result in vector_results:
                all_results.append(QueryResult(
                    content=result.get('content', ''),
                    score=result.get('score', 0.0),
                    source='vector',
                    metadata=result.get('metadata', {}),
                    document_id=result.get('document_id')
                ))
            
            # Add graph results
            for result in graph_results:
                all_results.append(QueryResult(
                    content=result.get('content', ''),
                    score=result.get('score', 0.0),
                    source='graph',
                    metadata=result.get('metadata', {}),
                    document_id=result.get('document_id')
                ))
            
            # Remove duplicates based on content similarity
            unique_results = self._deduplicate_results(all_results)
            
            # Re-rank using cross-encoder
            if len(unique_results) > 1:
                query_content_pairs = [(query, result.content) for result in unique_results]
                cross_scores = self.cross_encoder.predict(query_content_pairs)
                
                # Update scores
                for i, score in enumerate(cross_scores):
                    unique_results[i].score = float(score)
                
                # Sort by cross-encoder score
                unique_results.sort(key=lambda x: x.score, reverse=True)
            
            return unique_results[:top_k]
            
        except Exception as e:
            logger.error(f"Result combination failed: {str(e)}")
            return []
    
    def _deduplicate_results(self, results: List[QueryResult]) -> List[QueryResult]:
        """Remove duplicate results based on content similarity"""
        if not results:
            return []
        
        unique_results = [results[0]]
        
        for result in results[1:]:
            is_duplicate = False
            for unique_result in unique_results:
                # Simple similarity check - can be improved
                if self._calculate_similarity(result.content, unique_result.content) > 0.8:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_results.append(result)
        
        return unique_results
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity"""
        # Simple Jaccard similarity
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 and not words2:
            return 1.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0
    
    def _generate_response(self, query: str, results: List[QueryResult]) -> str:
        """Generate LLM response based on query and results"""
        try:
            # Prepare context from results
            context = "\n\n".join([
                f"Source {i+1}: {result.content[:500]}..."
                for i, result in enumerate(results[:5])
            ])
            
            # Create prompt
            prompt = f"""Based on the following legal documents and constitutional provisions, provide a comprehensive answer to the user's question.

Context:
{context}

Question: {query}

Instructions:
1. Provide a clear, accurate answer based on the provided context
2. Cite specific articles or sections when relevant
3. If the context doesn't contain sufficient information, state this clearly
4. Use simple language while maintaining legal accuracy

Answer:"""
            
            # Generate response
            response = self.llm.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"LLM response generation failed: {str(e)}")
            return "I apologize, but I'm unable to generate a response at the moment. Please try again later."
    
    @staticmethod
    def health_check() -> Dict[str, Any]:
        """Check AI service health"""
        try:
            # Test Groq API
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            test_response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            
            return {
                'status': 'healthy',
                'groq_api': 'connected',
                'embedding_model': 'loaded',
                'timestamp': timezone.now().isoformat()
            }
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            }


# ============================================================================
# DOCUMENT SERVICE
# ============================================================================

class DocumentService:
    """Consolidated document processing service"""
    
    @staticmethod
    def read_file_content(file_path: str) -> Tuple[str, Optional[str]]:
        """Read content from various file types"""
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.txt':
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read(), None
                    
            elif file_ext == '.pdf':
                text = ""
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    for page in pdf_reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                return text, None
                
            elif file_ext in ['.docx', '.doc']:
                doc = docx.Document(file_path)
                text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
                return text, None
                
            else:
                return "", f"Unsupported file type: {file_ext}"
                
        except Exception as e:
            logger.error(f"File reading failed: {str(e)}")
            return "", f"Failed to read file: {str(e)}"
    
    @staticmethod
    def summarize_document(document: UserDocument, summary_type: str = 'comprehensive') -> Dict[str, Any]:
        """Summarize document using AI"""
        try:
            # Read document content
            content, error = DocumentService.read_file_content(document.file_path.path)
            if error:
                return {'success': False, 'error': error}
            
            # Truncate if too long
            max_chars = 15000
            if len(content) > max_chars:
                content = content[:max_chars] + "\n\n[Document truncated due to length...]"
            
            # Generate summary using AI service
            ai_service = AIService()
            
            # Create summary prompt based on type
            prompts = {
                'brief': f"Provide a brief 2-3 paragraph summary of this legal document:\n\n{content}",
                'comprehensive': f"Provide a comprehensive analysis including overview, key points, and legal implications:\n\n{content}",
                'legal_issues': f"Identify and analyze all legal issues in this document:\n\n{content}",
                'clause_by_clause': f"Provide a clause-by-clause analysis of this document:\n\n{content}"
            }
            
            prompt = prompts.get(summary_type, prompts['comprehensive'])
            
            # Generate summary
            response = ai_service.llm.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000
            )
            
            summary = response.choices[0].message.content
            
            # Update document
            document.summary = summary
            document.summary_type = summary_type
            document.status = 'completed'
            document.save()
            
            return {
                'success': True,
                'summary': summary,
                'summary_type': summary_type
            }
            
        except Exception as e:
            logger.error(f"Document summarization failed: {str(e)}")
            return {
                'success': False,
                'error': f"Summarization failed: {str(e)}"
            }


# Create singleton instances
ai_service = AIService()