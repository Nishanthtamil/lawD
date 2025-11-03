import os
import tempfile
import threading # <-- ADD THIS IMPORT
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from django.conf import settings
import PyPDF2
import docx

from langchain.agents import create_agent
from langchain_community.graphs import Neo4jGraph
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_groq import ChatGroq

# Import your hybrid search function
try:
    from .hybrid_with_groq import hybrid_query_with_groq
except ImportError:
    # This pass is fine, but in production, you might want to log this
    hybrid_query_with_groq = None 
    pass

# ============================================
# Configuration
# ============================================

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ============================================
# Tools Definition
# ============================================

@tool
def hybrid_search(query: str) -> str:
    """
    Use this tool for complex, conceptual, or semantic questions.
    """
    try:
        # Check if the function was imported
        if hybrid_query_with_groq is None:
            return "Error: Hybrid search function is not available."
            
        result_dict = hybrid_query_with_groq(query, final_topk=3)
        return result_dict.get("model_text", "No answer found.")
    except Exception as e:
        return f"Hybrid search failed with error: {e}"

@tool
def text_to_cypher_search(query: str) -> str:
    """
    Use this tool for structural questions, lists, or counting.
    """
    # This tool is well-written: it initializes the client *inside*
    try:
        graph = Neo4jGraph(
            url=NEO4J_URI,
            username=NEO4J_USER,
            password=NEO4J_PASSWORD
        )
        
        # This initialization is safe because it's inside the tool call
        cypher_llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, groq_api_key=GROQ_API_KEY)
        
        cypher_generation_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a Neo4j Cypher expert. Generate ONLY the Cypher query.
            
Schema:
- Clause {{id: STRING, article_no: STRING, article_title: STRING, text: STRING, part: STRING}}
- Part {{title: STRING}}
- (Part)-[:CONTAINS]->(Clause)

Examples:
- "List all articles in Part III" -> MATCH (p:Part {{title: "Part III"}})-[:CONTAINS]->(c:Clause) RETURN c.article_no, c.article_title
"""),
            ("human", "{question}")
        ])
        
        chain = cypher_generation_prompt | cypher_llm
        cypher_query = chain.invoke({"question": query}).content.strip()
        
        if cypher_query.startswith("```"):
            lines = cypher_query.split("\n")
            cypher_query = "\n".join(lines[1:-1]) if len(lines) > 2 else cypher_query
        
        result = graph.query(cypher_query)
        return str(result) if result else "No results found."
        
    except Exception as e:
        return f"Graph search failed with error: {e}"

# ============================================
# Initialize Agent (LAZILY)
# ============================================

tools = [hybrid_search, text_to_cypher_search]

# --- START OF THE FIX ---

# We define them as None at the global level.
# They won't be created until the first request comes in.
agent_llm = None
agent_executor = None
agent_lock = threading.Lock() # To prevent race conditions in production

SYSTEM_MESSAGE = """You are a helpful junior legal assistant with access to the Indian Constitution database.
Choose the best tool for each query:

1. **hybrid_search**: For conceptual questions ("what are...", "explain...")
2. **text_to_cypher_search**: For structural queries ("list all...", "how many...")

Be accurate and cite constitutional articles when relevant."""

def get_agent_executor():
    """
    Lazily initializes and returns the global agent executor.
    This is thread-safe and only runs once.
    """
    global agent_llm, agent_executor
    
    # Use a lock to ensure this block only runs once
    # across all threads
    with agent_lock:
        # If the agent is still None, it means we are the first
        # thread to acquire the lock, so we create the agent.
        if agent_executor is None:
            # Now we read the API key. If it's missing,
            # it will fail here, during an API call, which is correct.
            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                # This will be caught by the view
                raise ValueError("GROQ_API_KEY environment variable not set.")
                
            agent_llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                temperature=0,
                groq_api_key=api_key
            )
            
            agent_executor = create_agent(agent_llm, tools)
            print("--- Global Agent Executor Initialized ---") # For logging
            
    return agent_executor

# --- END OF THE FIX ---


# ============================================
# File Reading Utilities
# ============================================

def read_txt_file(file_path: str) -> str:
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def read_pdf_file(file_path: str) -> str:
    text = ""
    with open(file_path, 'rb') as f:
        pdf_reader = PyPDF2.PdfReader(f)
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def read_docx_file(file_path: str) -> str:
    doc = docx.Document(file_path)
    return "\n".join([paragraph.text for paragraph in doc.paragraphs])

def read_uploaded_file(file):
    """Read uploaded file and return content"""
    # Save to temp file
    suffix = os.path.splitext(file.name)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        for chunk in file.chunks():
            tmp_file.write(chunk)
        tmp_path = tmp_file.name
    
    try:
        if suffix == '.txt':
            content = read_txt_file(tmp_path)
        elif suffix == '.pdf':
            content = read_pdf_file(tmp_path)
        elif suffix in ['.docx', '.doc']:
            content = read_docx_file(tmp_path)
        else:
            return None, f"Unsupported file type: {suffix}"
        
        return content, None
    finally:
        os.unlink(tmp_path)

# ============================================
# API Endpoints
# ============================================

@api_view(['POST'])
@parser_classes([JSONParser])
def chat(request):
    """
    Legal Assistant Chat endpoint
    
    Request body:
    {
        "message": "What are fundamental rights?"
    }
    """
    try:
        message = request.data.get('message')
        
        if not message:
            return Response(
                {"error": "Message is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # --- MODIFIED SECTION ---
        # Get the agent executor. 
        # This will initialize it if it's the first request.
        try:
            executor = get_agent_executor()
        except ValueError as e:
            # This catches the "GROQ_API_KEY not set" error
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        # --- END MODIFIED SECTION ---

        # Invoke agent
        result = executor.invoke({ # Use the 'executor' variable
            "messages": [
                SystemMessage(content=SYSTEM_MESSAGE),
                HumanMessage(content=message)
            ]
        })
        
        final_message = result["messages"][-1]
        
        return Response({
            "response": final_message.content,
            "status": "success"
        })
        
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def summarize_document(request):
    """
    Document Summarization endpoint
    
    Form data:
    - file: Document file (pdf, docx, txt)
    - summary_type: brief, comprehensive, legal_issues, clause_by_clause
    """
    # THIS FUNCTION IS ALREADY WRITTEN CORRECTLY
    # It initializes clients *inside* the view
    
    try:
        file = request.FILES.get('file')
        summary_type = request.data.get('summary_type', 'comprehensive')
        
        if not file:
            return Response(
                {"error": "File is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Read file content
        content, error = read_uploaded_file(file)
        if error:
            return Response(
                {"error": error},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Truncate if too long
        max_chars = 15000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n[Document truncated due to length...]"
        
        # Create LLM instance (safe, inside the view)
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.3, groq_api_key=GROQ_API_KEY)
        
        # Step 1: Extract key concepts
        extraction_prompt = f"""Analyze this legal document and extract:
1. Main legal concepts and topics
2. Constitutional article references
3. Key legal issues

Document:
{content}

Provide structured extraction:"""

        extraction = llm.invoke(extraction_prompt).content
        
        # Step 2: Query Constitution database
        try:
            if hybrid_query_with_groq is None:
                 raise ImportError("Hybrid search module not loaded")
                 
            constitution_context = hybrid_query_with_groq(
                f"Constitutional provisions related to: {extraction[:500]}", 
                final_topk=5
            )
            constitutional_refs = constitution_context.get("model_text", "")
        except Exception as e:
            constitutional_refs = f"Could not retrieve constitutional references: {e}"
        
        # Step 3: Generate summary based on type
        summary_prompts = {
            "brief": f"""As a legal expert, provide a BRIEF summary (2-3 paragraphs):

Document: {content}

Constitutional Context: {constitutional_refs}

Brief Summary:""",

            "comprehensive": f"""Provide COMPREHENSIVE analysis:
1. Overview
2. Key Points
3. Constitutional Analysis
4. Legal Implications
5. Relevant Articles

Document: {content}

Constitutional Context: {constitutional_refs}

Analysis:""",

            "legal_issues": f"""Analyze LEGAL ISSUES:
1. Identify all legal issues
2. Constitutional law context
3. Cite relevant articles
4. Highlight conflicts

Document: {content}

Constitutional Context: {constitutional_refs}

Legal Issues:""",

            "clause_by_clause": f"""CLAUSE-BY-CLAUSE analysis:
1. Break down key sections
2. Explain each in simple terms
3. Constitutional implications
4. Legal issues per section

Document: {content}

Constitutional Context: {constitutional_refs}

Analysis:"""
        }
        
        prompt = summary_prompts.get(summary_type, summary_prompts["comprehensive"])
        summary = llm.invoke(prompt).content
        
        return Response({
            "summary": summary,
            "summary_type": summary_type,
            "file_name": file.name,
            "status": "success"
        })
        
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
def health_check(request):
    """Health check endpoint"""
    return Response({
        "status": "healthy",
        "service": "Legal Assistant API"
    })