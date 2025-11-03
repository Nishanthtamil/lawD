import os
import tempfile
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

import PyPDF2
import docx
from langchain_groq import ChatGroq

from .models import UserDocument
from .serializers import UserDocumentSerializer
from .views import GROQ_API_KEY, hybrid_query_with_groq


def read_uploaded_file_content(file):
    """Read content from uploaded file"""
    file_extension = os.path.splitext(file.name)[1].lower()
    
    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
        for chunk in file.chunks():
            tmp_file.write(chunk)
        tmp_path = tmp_file.name
    
    try:
        if file_extension == '.txt':
            with open(tmp_path, 'r', encoding='utf-8') as f:
                content = f.read()
        elif file_extension == '.pdf':
            text = ""
            with open(tmp_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            content = text
        elif file_extension in ['.docx', '.doc']:
            doc = docx.Document(tmp_path)
            content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        else:
            return None, f"Unsupported file type: {file_extension}"
        
        return content, None
    finally:
        os.unlink(tmp_path)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_documents(request):
    """
    Get all documents for current user
    """
    documents = UserDocument.objects.filter(user=request.user)
    serializer = UserDocumentSerializer(documents, many=True, context={'request': request})
    return Response({
        "documents": serializer.data
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_document(request):
    """
    Upload a document
    
    Form data:
    - file: Document file (pdf, docx, txt)
    - summary_type: brief, comprehensive, legal_issues, clause_by_clause (optional)
    """
    file = request.FILES.get('file')
    summary_type = request.data.get('summary_type', '')
    
    if not file:
        return Response(
            {"error": "File is required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate file size (10MB max)
    if file.size > 10 * 1024 * 1024:
        return Response(
            {"error": "File size must be less than 10MB"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate file type
    file_extension = os.path.splitext(file.name)[1].lower()
    if file_extension not in ['.pdf', '.docx', '.doc', '.txt']:
        return Response(
            {"error": "Unsupported file type. Supported: PDF, DOCX, TXT"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Create document record
        document = UserDocument.objects.create(
            user=request.user,
            file_name=file.name,
            file_path=file,
            file_size=file.size,
            file_type=file_extension.replace('.', ''),
            summary_type=summary_type,
            status='pending'
        )
        
        return Response({
            "message": "Document uploaded successfully",
            "document": UserDocumentSerializer(document, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        return Response(
            {"error": f"Upload failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def summarize_user_document(request, document_id):
    """
    Generate summary for an uploaded document
    
    Request body:
    {
        "summary_type": "comprehensive"  // brief, comprehensive, legal_issues, clause_by_clause
    }
    """
    document = get_object_or_404(UserDocument, id=document_id, user=request.user)
    
    summary_type = request.data.get('summary_type', 'comprehensive')
    
    if document.status == 'processing':
        return Response(
            {"error": "Document is already being processed"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Update status
        document.status = 'processing'
        document.summary_type = summary_type
        document.save()
        
        print(f"\n=== Processing document: {document.file_name} ===")
        
        # Read file content
        with document.file_path.open('rb') as file:
            from django.core.files.uploadedfile import InMemoryUploadedFile
            uploaded_file = InMemoryUploadedFile(
                file=file,
                field_name='file',
                name=document.file_name,
                content_type='application/octet-stream',
                size=document.file_size,
                charset=None
            )
            content, error = read_uploaded_file_content(uploaded_file)
        
        if error:
            document.status = 'failed'
            document.save()
            return Response(
                {"error": error},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Truncate if too long
        max_chars = 15000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n[Document truncated due to length...]"
        
        # Create LLM instance
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
            constitution_context = hybrid_query_with_groq(
                f"Constitutional provisions related to: {extraction[:500]}", 
                final_topk=5
            )
            constitutional_refs = constitution_context.get("model_text", "")
        except:
            constitutional_refs = "Could not retrieve constitutional references."
        
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
        
        # Update document with summary
        document.summary = summary
        document.status = 'completed'
        document.save()
        
        print(f"=== Document processed successfully ===\n")
        
        return Response({
            "message": "Document summarized successfully",
            "document": UserDocumentSerializer(document, context={'request': request}).data
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n=== ERROR in summarize_document ===")
        print(error_details)
        print(f"=== END ERROR ===\n")
        
        document.status = 'failed'
        document.save()
        
        return Response(
            {"error": f"Summarization failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_document(request, document_id):
    """
    Get a specific document
    """
    document = get_object_or_404(UserDocument, id=document_id, user=request.user)
    serializer = UserDocumentSerializer(document, context={'request': request})
    return Response({
        "document": serializer.data
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_document(request, document_id):
    """
    Delete a document
    """
    document = get_object_or_404(UserDocument, id=document_id, user=request.user)
    
    # Delete file from storage
    if document.file_path:
        document.file_path.delete()
    
    # Delete record
    document.delete()
    
    return Response({
        "message": "Document deleted successfully"
    }, status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_document(request, document_id):
    """
    Download original document file
    """
    document = get_object_or_404(UserDocument, id=document_id, user=request.user)
    
    if not document.file_path:
        return Response(
            {"error": "File not found"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Return file URL for download
    return Response({
        "file_url": request.build_absolute_uri(document.file_path.url),
        "file_name": document.file_name
    })