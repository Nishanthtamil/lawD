"""
LLM Synthesis and Response Generation for Segregated Hybrid RAG Pipeline.
Handles prompt templates, Groq API integration, and citation management.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
import json
import re
from datetime import datetime

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class LLMSynthesizer:
    """
    Manages LLM synthesis and response generation using Groq API.
    Combines personal and public contexts with proper citation management.
    """
    
    def __init__(self):
        self.groq_api_key = getattr(settings, 'GROQ_API_KEY', '')
        self.groq_base_url = getattr(settings, 'GROQ_BASE_URL', 'https://api.groq.com/openai/v1')
        self.default_model = getattr(settings, 'GROQ_MODEL', 'llama3-8b-8192')
        self.max_tokens = getattr(settings, 'GROQ_MAX_TOKENS', 2048)
        self.temperature = getattr(settings, 'GROQ_TEMPERATURE', 0.1)
        self.cache_timeout = 1800  # 30 minutes for response caching
        
        if not self.groq_api_key:
            logger.warning("GROQ_API_KEY not configured. LLM synthesis will be disabled.")
    
    def synthesize_response(self, query: str, combined_contexts: Dict[str, Any], 
                          user_id: str = None) -> Dict[str, Any]:
        """
        Generate a comprehensive response by synthesizing personal and public contexts.
        
        Args:
            query: User's original query
            combined_contexts: Combined contexts from SegregatedRetriever
            user_id: ID of the requesting user (for personalization)
            
        Returns:
            Dictionary containing synthesized response with citations
        """
        try:
            if not self.groq_api_key:
                return self._fallback_response(query, combined_contexts)
            
            # Check cache first
            cache_key = f"llm_response_{hash(query)}_{hash(str(combined_contexts))}_{user_id}"
            cached_response = cache.get(cache_key)
            if cached_response:
                logger.debug("Retrieved LLM response from cache")
                return cached_response
            
            # Prepare prompt with contexts
            prompt = self._build_synthesis_prompt(query, combined_contexts, user_id)
            
            # Generate response using Groq API
            llm_response = self._call_groq_api(prompt)
            
            if not llm_response:
                return self._fallback_response(query, combined_contexts)
            
            # Process response and extract citations
            processed_response = self._process_llm_response(llm_response, combined_contexts)
            
            # Add metadata
            response_data = {
                'query': query,
                'response': processed_response['response'],
                'citations': processed_response['citations'],
                'has_personal_context': combined_contexts.get('has_personal_context', False),
                'has_public_context': combined_contexts.get('has_public_context', False),
                'context_summary': {
                    'total_contexts': combined_contexts.get('total_contexts', 0),
                    'personal_count': combined_contexts.get('personal_count', 0),
                    'public_semantic_count': combined_contexts.get('public_semantic_count', 0),
                    'public_graph_count': combined_contexts.get('public_graph_count', 0)
                },
                'generated_at': datetime.now().isoformat(),
                'model_used': self.default_model
            }
            
            # Cache the response
            cache.set(cache_key, response_data, timeout=self.cache_timeout)
            
            logger.info(f"Generated LLM response for query: {query[:50]}...")
            return response_data
            
        except Exception as e:
            logger.error(f"Error synthesizing response: {e}")
            return self._fallback_response(query, combined_contexts, error=str(e))
    
    def _build_synthesis_prompt(self, query: str, combined_contexts: Dict[str, Any], 
                              user_id: str = None) -> str:
        """
        Build a comprehensive prompt for LLM synthesis.
        
        Args:
            query: User's query
            combined_contexts: Combined contexts from retrieval
            user_id: User ID for personalization
            
        Returns:
            Formatted prompt string
        """
        try:
            contexts = combined_contexts.get('contexts', [])
            has_personal = combined_contexts.get('has_personal_context', False)
            has_public = combined_contexts.get('has_public_context', False)
            
            # Select appropriate prompt template
            if has_personal and has_public:
                template = self._get_hybrid_prompt_template()
            elif has_personal:
                template = self._get_personal_only_prompt_template()
            elif has_public:
                template = self._get_public_only_prompt_template()
            else:
                template = self._get_no_context_prompt_template()
            
            # Prepare context sections
            personal_contexts = [c for c in contexts if c.get('context_type') == 'personal']
            public_semantic_contexts = [c for c in contexts if c.get('context_type') == 'public_semantic']
            public_graph_contexts = [c for c in contexts if c.get('context_type') == 'public_graph']
            
            # Format contexts
            personal_context_text = self._format_personal_contexts(personal_contexts)
            public_semantic_text = self._format_public_semantic_contexts(public_semantic_contexts)
            public_graph_text = self._format_public_graph_contexts(public_graph_contexts)
            
            # Build the prompt
            prompt = template.format(
                query=query,
                personal_contexts=personal_context_text,
                public_semantic_contexts=public_semantic_text,
                public_graph_contexts=public_graph_text,
                total_contexts=len(contexts),
                personal_count=len(personal_contexts),
                public_count=len(public_semantic_contexts) + len(public_graph_contexts)
            )
            
            return prompt
            
        except Exception as e:
            logger.error(f"Error building synthesis prompt: {e}")
            return f"Please answer the following question: {query}"
    
    def _get_hybrid_prompt_template(self) -> str:
        """Get prompt template for hybrid (personal + public) contexts"""
        return """You are a Legal AI Assistant specializing in Indian constitutional law and legal analysis. You have access to both the user's personal legal documents and public legal knowledge including constitutional provisions, case law, and legal precedents.

QUERY: {query}

PERSONAL DOCUMENTS (User's specific case files and documents):
{personal_contexts}

PUBLIC LEGAL KNOWLEDGE (Constitutional law, precedents, and legal framework):
Semantic Search Results:
{public_semantic_contexts}

Legal Relationship Knowledge:
{public_graph_contexts}

INSTRUCTIONS:
1. Provide a comprehensive legal analysis that combines insights from the user's personal documents with relevant public legal knowledge
2. Clearly distinguish between information from personal documents vs. public legal sources
3. Use proper legal citation format and reference specific sources
4. If the user's personal documents relate to the constitutional provisions or case law, explain the connections
5. Provide practical legal guidance while noting that this is AI-generated analysis
6. Include appropriate legal disclaimers about the limitations of AI legal advice

CITATION FORMAT:
- Personal documents: [Personal Doc: document_title]
- Constitutional provisions: [Article X] or [Constitutional Provision]
- Case law: [Case Name, Citation]
- Legal precedents: [Legal Authority]

Please provide a detailed response that synthesizes all available information while maintaining clear source attribution."""
    
    def _get_personal_only_prompt_template(self) -> str:
        """Get prompt template for personal contexts only"""
        return """You are a Legal AI Assistant analyzing the user's personal legal documents. You have access to the user's specific case files and legal documents but no additional public legal knowledge for this query.

QUERY: {query}

PERSONAL DOCUMENTS (User's specific case files and documents):
{personal_contexts}

INSTRUCTIONS:
1. Analyze the user's personal documents in relation to their query
2. Provide insights based solely on the information available in their documents
3. Use proper citation format referencing the specific documents
4. Note any limitations due to the scope of available personal documents
5. Suggest areas where additional legal research or consultation might be beneficial
6. Include appropriate disclaimers about AI-generated analysis

CITATION FORMAT:
- Personal documents: [Personal Doc: document_title]

Please provide an analysis based on the user's personal documents while noting any limitations in scope."""
    
    def _get_public_only_prompt_template(self) -> str:
        """Get prompt template for public contexts only"""
        return """You are a Legal AI Assistant specializing in Indian constitutional law and legal analysis. You have access to public legal knowledge including constitutional provisions, case law, and legal precedents.

QUERY: {query}

PUBLIC LEGAL KNOWLEDGE (Constitutional law, precedents, and legal framework):
Semantic Search Results:
{public_semantic_contexts}

Legal Relationship Knowledge:
{public_graph_contexts}

INSTRUCTIONS:
1. Provide a comprehensive legal analysis based on constitutional law and legal precedents
2. Use proper legal citation format and reference specific sources
3. Explain relevant constitutional provisions, case law, and legal principles
4. Provide general legal guidance while noting that this is AI-generated analysis
5. Include appropriate legal disclaimers about the limitations of AI legal advice
6. Suggest when personalized legal consultation might be necessary

CITATION FORMAT:
- Constitutional provisions: [Article X] or [Constitutional Provision]
- Case law: [Case Name, Citation]
- Legal precedents: [Legal Authority]

Please provide a detailed response based on constitutional law and legal precedents."""
    
    def _get_no_context_prompt_template(self) -> str:
        """Get prompt template when no relevant contexts are found"""
        return """You are a Legal AI Assistant specializing in Indian constitutional law. No specific relevant documents or legal precedents were found for this query.

QUERY: {query}

INSTRUCTIONS:
1. Provide general legal guidance based on your knowledge of Indian constitutional law
2. Explain relevant legal principles and constitutional provisions that might apply
3. Note the limitations of providing advice without specific case details or relevant precedents
4. Suggest steps the user might take to get more specific legal guidance
5. Include appropriate disclaimers about AI-generated legal advice
6. Recommend consulting with qualified legal professionals for specific legal matters

Please provide a helpful response while clearly noting the limitations of general legal guidance."""
    
    def _format_personal_contexts(self, contexts: List[Dict[str, Any]]) -> str:
        """Format personal document contexts for the prompt"""
        if not contexts:
            return "No personal documents found relevant to this query."
        
        formatted = []
        for i, context in enumerate(contexts, 1):
            doc_id = context.get('document_id', 'Unknown')
            text = context.get('text', '')
            score = context.get('combined_score', context.get('score', 0))
            
            formatted.append(f"""
Document {i} (ID: {doc_id}, Relevance: {score:.2f}):
{text}
""")
        
        return "\n".join(formatted)
    
    def _format_public_semantic_contexts(self, contexts: List[Dict[str, Any]]) -> str:
        """Format public semantic search contexts for the prompt"""
        if not contexts:
            return "No relevant semantic matches found in public legal knowledge."
        
        formatted = []
        for i, context in enumerate(contexts, 1):
            doc_type = context.get('document_type', 'Legal Document')
            legal_domain = context.get('legal_domain', 'General')
            text = context.get('text', '')
            score = context.get('combined_score', context.get('score', 0))
            
            formatted.append(f"""
{doc_type} {i} (Domain: {legal_domain}, Relevance: {score:.2f}):
{text}
""")
        
        return "\n".join(formatted)
    
    def _format_public_graph_contexts(self, contexts: List[Dict[str, Any]]) -> str:
        """Format public graph relationship contexts for the prompt"""
        if not contexts:
            return "No relevant legal relationships found in knowledge graph."
        
        formatted = []
        for i, context in enumerate(contexts, 1):
            entity_type = context.get('entity_type', 'Legal Entity')
            name = context.get('name', 'Unknown')
            text = context.get('text', '')
            relationship_type = context.get('relationship_type', '')
            
            rel_info = f" (Related via: {relationship_type})" if relationship_type else ""
            
            formatted.append(f"""
{entity_type.title()} {i}: {name}{rel_info}
{text}
""")
        
        return "\n".join(formatted)
    
    def _call_groq_api(self, prompt: str) -> Optional[str]:
        """
        Call Groq API to generate response.
        
        Args:
            prompt: Formatted prompt for the LLM
            
        Returns:
            Generated response text or None if failed
        """
        try:
            headers = {
                'Authorization': f'Bearer {self.groq_api_key}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'model': self.default_model,
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You are a helpful Legal AI Assistant specializing in Indian constitutional law and legal analysis. Provide accurate, well-cited legal information while including appropriate disclaimers.'
                    },
                    {
                        'role': 'user',
                        'content': prompt
                    }
                ],
                'max_tokens': self.max_tokens,
                'temperature': self.temperature,
                'stream': False
            }
            
            response = requests.post(
                f'{self.groq_base_url}/chat/completions',
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                return response_data['choices'][0]['message']['content']
            else:
                logger.error(f"Groq API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error calling Groq API: {e}")
            return None
    
    def _process_llm_response(self, llm_response: str, combined_contexts: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process LLM response to extract citations and format properly.
        
        Args:
            llm_response: Raw response from LLM
            combined_contexts: Original contexts for citation validation
            
        Returns:
            Dictionary with processed response and citations
        """
        try:
            # Extract citations from the response
            citations = self._extract_citations(llm_response, combined_contexts)
            
            # Clean up the response text
            cleaned_response = self._clean_response_text(llm_response)
            
            # Add legal disclaimer if not present
            if 'disclaimer' not in cleaned_response.lower():
                cleaned_response += self._get_legal_disclaimer()
            
            return {
                'response': cleaned_response,
                'citations': citations
            }
            
        except Exception as e:
            logger.error(f"Error processing LLM response: {e}")
            return {
                'response': llm_response,
                'citations': []
            }
    
    def _extract_citations(self, response_text: str, combined_contexts: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract and validate citations from the response"""
        try:
            citations = []
            contexts = combined_contexts.get('contexts', [])
            
            # Find citation patterns in the response
            citation_patterns = [
                r'\[Personal Doc: ([^\]]+)\]',
                r'\[Article (\d+)\]',
                r'\[Constitutional Provision[^\]]*\]',
                r'\[([^,\]]+, [^\]]+)\]',  # Case citations
                r'\[Legal Authority[^\]]*\]'
            ]
            
            for pattern in citation_patterns:
                matches = re.findall(pattern, response_text)
                for match in matches:
                    citation_text = match if isinstance(match, str) else match[0] if match else ''
                    
                    # Find corresponding context
                    source_context = self._find_source_context(citation_text, contexts)
                    
                    citation = {
                        'text': citation_text,
                        'type': self._determine_citation_type(citation_text, pattern),
                        'source_context': source_context
                    }
                    citations.append(citation)
            
            # Remove duplicates
            unique_citations = []
            seen_texts = set()
            for citation in citations:
                if citation['text'] not in seen_texts:
                    seen_texts.add(citation['text'])
                    unique_citations.append(citation)
            
            return unique_citations
            
        except Exception as e:
            logger.error(f"Error extracting citations: {e}")
            return []
    
    def _find_source_context(self, citation_text: str, contexts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Find the source context for a citation"""
        try:
            for context in contexts:
                # Check document ID match for personal documents
                if context.get('context_type') == 'personal':
                    doc_id = context.get('document_id', '')
                    if citation_text in doc_id or doc_id in citation_text:
                        return {
                            'source': 'personal',
                            'document_id': doc_id,
                            'chunk_id': context.get('chunk_id'),
                            'score': context.get('combined_score', context.get('score', 0))
                        }
                
                # Check entity name match for graph contexts
                elif context.get('context_type') == 'public_graph':
                    entity_name = context.get('name', '')
                    if citation_text.lower() in entity_name.lower() or entity_name.lower() in citation_text.lower():
                        return {
                            'source': 'public_graph',
                            'entity_id': context.get('entity_id'),
                            'entity_type': context.get('entity_type'),
                            'name': entity_name
                        }
                
                # Check content match for semantic contexts
                elif context.get('context_type') == 'public_semantic':
                    text = context.get('text', '')
                    if citation_text.lower() in text.lower():
                        return {
                            'source': 'public_semantic',
                            'document_id': context.get('document_id'),
                            'document_type': context.get('document_type'),
                            'legal_domain': context.get('legal_domain')
                        }
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding source context: {e}")
            return None
    
    def _determine_citation_type(self, citation_text: str, pattern: str) -> str:
        """Determine the type of citation based on text and pattern"""
        if 'Personal Doc' in pattern:
            return 'personal_document'
        elif 'Article' in pattern:
            return 'constitutional_article'
        elif 'Constitutional' in pattern:
            return 'constitutional_provision'
        elif 'Legal Authority' in pattern:
            return 'legal_authority'
        else:
            return 'case_law'
    
    def _clean_response_text(self, response_text: str) -> str:
        """Clean and format the response text"""
        try:
            # Remove excessive whitespace
            cleaned = re.sub(r'\n\s*\n', '\n\n', response_text.strip())
            
            # Ensure proper paragraph spacing
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Error cleaning response text: {e}")
            return response_text
    
    def _get_legal_disclaimer(self) -> str:
        """Get standard legal disclaimer text"""
        return """

**Legal Disclaimer**: This response is generated by an AI system and is for informational purposes only. It does not constitute legal advice and should not be relied upon as a substitute for consultation with a qualified legal professional. For specific legal matters, please consult with an attorney licensed to practice in your jurisdiction."""
    
    def _fallback_response(self, query: str, combined_contexts: Dict[str, Any], error: str = None) -> Dict[str, Any]:
        """Generate a fallback response when LLM synthesis fails"""
        try:
            contexts = combined_contexts.get('contexts', [])
            has_personal = combined_contexts.get('has_personal_context', False)
            has_public = combined_contexts.get('has_public_context', False)
            
            if not contexts:
                response_text = f"""I apologize, but I couldn't find relevant information to answer your query: "{query}".

This could be because:
1. No relevant documents were found in your personal library
2. No matching constitutional provisions or legal precedents were identified
3. The query might need to be more specific or use different legal terminology

Please try rephrasing your question or providing more context about the specific legal issue you're researching."""
            
            else:
                response_text = f"""Based on the available information, I found {len(contexts)} relevant sources for your query: "{query}".

"""
                if has_personal:
                    personal_count = combined_contexts.get('personal_count', 0)
                    response_text += f"• {personal_count} matches from your personal documents\n"
                
                if has_public:
                    public_count = combined_contexts.get('public_semantic_count', 0) + combined_contexts.get('public_graph_count', 0)
                    response_text += f"• {public_count} matches from public legal knowledge\n"
                
                response_text += "\nHowever, I encountered an issue generating a comprehensive analysis. Please review the source documents directly or try rephrasing your query."
            
            if error:
                response_text += f"\n\nTechnical note: {error}"
            
            response_text += self._get_legal_disclaimer()
            
            return {
                'query': query,
                'response': response_text,
                'citations': [],
                'has_personal_context': has_personal,
                'has_public_context': has_public,
                'context_summary': combined_contexts.get('context_summary', {}),
                'generated_at': datetime.now().isoformat(),
                'model_used': 'fallback',
                'error': error
            }
            
        except Exception as e:
            logger.error(f"Error generating fallback response: {e}")
            return {
                'query': query,
                'response': f"I apologize, but I encountered an error processing your query: {query}. Please try again or contact support if the issue persists.",
                'citations': [],
                'error': str(e)
            }