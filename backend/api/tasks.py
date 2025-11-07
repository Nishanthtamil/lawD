import os
import logging
from datetime import datetime, timedelta
from celery import shared_task
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from .models import UserDocument, ChatSession, ChatMessage
from .document_processing import DocumentProcessor
from .hybrid_retrieval import HybridRetriever

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_document_async(self, document_id):
    """
    Asynchronously process uploaded documents for summarization and indexing
    """
    try:
        document = UserDocument.objects.get(id=document_id)
        document.processing_status = 'processing'
        document.save()
        
        # Initialize document processor
        processor = DocumentProcessor()
        
        # Extract text from document
        text_content = processor.extract_text(document.file.path)
        
        # Generate summary
        summary = processor.generate_summary(text_content)
        
        # Update document with results
        document.summary = summary
        document.processing_status = 'completed'
        document.processed_at = timezone.now()
        document.save()
        
        # Cache the summary for quick access
        cache_key = f"document_summary_{document_id}"
        cache.set(cache_key, summary, timeout=86400)  # Cache for 24 hours
        
        # Index document for search (if using vector database)
        try:
            retriever = HybridRetriever()
            retriever.index_document(document_id, text_content, document.title)
        except Exception as e:
            logger.warning(f"Failed to index document {document_id}: {str(e)}")
        
        logger.info(f"Successfully processed document {document_id}")
        return {"status": "success", "document_id": document_id}
        
    except UserDocument.DoesNotExist:
        logger.error(f"Document {document_id} not found")
        return {"status": "error", "message": "Document not found"}
    
    except Exception as exc:
        logger.error(f"Error processing document {document_id}: {str(exc)}")
        
        # Update document status to failed
        try:
            document = UserDocument.objects.get(id=document_id)
            document.processing_status = 'failed'
            document.save()
        except:
            pass
        
        # Retry the task
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        return {"status": "error", "message": str(exc)}

@shared_task
def cache_chat_session(session_id, messages_data):
    """
    Cache chat session data for quick retrieval
    """
    try:
        cache_key = f"chat_session_{session_id}"
        cache.set(cache_key, messages_data, timeout=3600)  # Cache for 1 hour
        logger.info(f"Cached chat session {session_id}")
        return {"status": "success", "session_id": session_id}
    except Exception as e:
        logger.error(f"Failed to cache chat session {session_id}: {str(e)}")
        return {"status": "error", "message": str(e)}

@shared_task
def generate_response_async(session_id, user_message, user_id):
    """
    Generate AI response asynchronously
    """
    try:
        from .hybrid_with_groq import process_query_with_groq
        
        # Generate response using hybrid retrieval
        response = process_query_with_groq(user_message)
        
        # Save the AI response to database
        session = ChatSession.objects.get(id=session_id)
        ChatMessage.objects.create(
            session=session,
            message=response,
            is_user=False
        )
        
        # Update cache with new message
        cache_key = f"chat_session_{session_id}"
        messages = ChatMessage.objects.filter(session=session).order_by('created_at')
        messages_data = [
            {
                'id': msg.id,
                'message': msg.message,
                'is_user': msg.is_user,
                'created_at': msg.created_at.isoformat()
            }
            for msg in messages
        ]
        cache.set(cache_key, messages_data, timeout=3600)
        
        logger.info(f"Generated response for session {session_id}")
        return {"status": "success", "response": response}
        
    except Exception as e:
        logger.error(f"Failed to generate response for session {session_id}: {str(e)}")
        return {"status": "error", "message": str(e)}

@shared_task
def cleanup_expired_sessions():
    """
    Clean up expired chat sessions and their cached data
    """
    try:
        # Delete sessions older than 30 days
        cutoff_date = timezone.now() - timedelta(days=30)
        expired_sessions = ChatSession.objects.filter(created_at__lt=cutoff_date)
        
        count = 0
        for session in expired_sessions:
            # Remove from cache
            cache_key = f"chat_session_{session.id}"
            cache.delete(cache_key)
            
            # Delete from database
            session.delete()
            count += 1
        
        logger.info(f"Cleaned up {count} expired chat sessions")
        return {"status": "success", "cleaned_sessions": count}
        
    except Exception as e:
        logger.error(f"Failed to cleanup expired sessions: {str(e)}")
        return {"status": "error", "message": str(e)}

@shared_task
def cleanup_old_documents():
    """
    Clean up old processed documents and their cached summaries
    """
    try:
        # Delete documents older than 90 days
        cutoff_date = timezone.now() - timedelta(days=90)
        old_documents = UserDocument.objects.filter(uploaded_at__lt=cutoff_date)
        
        count = 0
        for document in old_documents:
            # Remove cached summary
            cache_key = f"document_summary_{document.id}"
            cache.delete(cache_key)
            
            # Delete file from storage
            if document.file and os.path.exists(document.file.path):
                os.remove(document.file.path)
            
            # Delete from database
            document.delete()
            count += 1
        
        logger.info(f"Cleaned up {count} old documents")
        return {"status": "success", "cleaned_documents": count}
        
    except Exception as e:
        logger.error(f"Failed to cleanup old documents: {str(e)}")
        return {"status": "error", "message": str(e)}

@shared_task
def warm_cache_for_user(user_id):
    """
    Pre-warm cache with user's recent data
    """
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        user = User.objects.get(id=user_id)
        
        # Cache recent chat sessions
        recent_sessions = ChatSession.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timedelta(days=7)
        )[:5]
        
        for session in recent_sessions:
            messages = ChatMessage.objects.filter(session=session).order_by('created_at')
            messages_data = [
                {
                    'id': msg.id,
                    'message': msg.message,
                    'is_user': msg.is_user,
                    'created_at': msg.created_at.isoformat()
                }
                for msg in messages
            ]
            cache_key = f"chat_session_{session.id}"
            cache.set(cache_key, messages_data, timeout=3600)
        
        # Cache recent document summaries
        recent_documents = UserDocument.objects.filter(
            user=user,
            processing_status='completed',
            uploaded_at__gte=timezone.now() - timedelta(days=7)
        )[:10]
        
        for document in recent_documents:
            if document.summary:
                cache_key = f"document_summary_{document.id}"
                cache.set(cache_key, document.summary, timeout=86400)
        
        logger.info(f"Warmed cache for user {user_id}")
        return {"status": "success", "user_id": user_id}
        
    except Exception as e:
        logger.error(f"Failed to warm cache for user {user_id}: {str(e)}")
        return {"status": "error", "message": str(e)}