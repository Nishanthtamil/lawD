from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from .models import ChatSession, ChatMessage, User
from .serializers import (
    ChatSessionSerializer, 
    ChatSessionListSerializer, 
    ChatMessageSerializer
)
from .views import tools, SYSTEM_MESSAGE, GROQ_API_KEY

# Initialize agent (same as before)
agent_llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0, groq_api_key=GROQ_API_KEY)
agent_executor = create_agent(agent_llm, tools)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_chat_sessions(request):
    """
    Get all chat sessions for current user
    """
    sessions = ChatSession.objects.filter(user=request.user)
    serializer = ChatSessionListSerializer(sessions, many=True)
    return Response({
        "sessions": serializer.data
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_chat_session(request):
    """
    Create a new chat session
    
    Request body:
    {
        "title": "Constitutional Law Questions"  // Optional
    }
    """
    title = request.data.get('title', 'New Conversation')
    
    session = ChatSession.objects.create(
        user=request.user,
        title=title
    )
    
    return Response({
        "session": ChatSessionSerializer(session).data
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_chat_session(request, session_id):
    """
    Get a specific chat session with all messages
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    serializer = ChatSessionSerializer(session)
    return Response({
        "session": serializer.data
    })


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_chat_session(request, session_id):
    """
    Update chat session (e.g., rename)
    
    Request body:
    {
        "title": "New Title"
    }
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    
    title = request.data.get('title')
    if title:
        session.title = title
        session.save()
    
    return Response({
        "session": ChatSessionSerializer(session).data
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_chat_session(request, session_id):
    """
    Delete a chat session
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    session.delete()
    
    return Response({
        "message": "Session deleted successfully"
    }, status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def send_message(request, session_id):
    """
    Send a message in a chat session
    
    Request body:
    {
        "message": "What are fundamental rights?"
    }
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    
    message_content = request.data.get('message')
    
    if not message_content:
        return Response(
            {"error": "Message is required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Save user message
        user_message = ChatMessage.objects.create(
            session=session,
            role='user',
            content=message_content
        )
        
        print(f"\n=== User {request.user.phone_number} in session {session_id} ===")
        print(f"Message: {message_content}")
        
        # Get chat history for context (last 10 messages)
        history = session.messages.order_by('-created_at')[:10][::-1]
        
        # Build context messages
        context_messages = [SystemMessage(content=SYSTEM_MESSAGE)]
        for msg in history[:-1]:  # Exclude the current message
            if msg.role == 'user':
                context_messages.append(HumanMessage(content=msg.content))
            else:
                context_messages.append(SystemMessage(content=msg.content))
        
        # Add current message
        context_messages.append(HumanMessage(content=message_content))
        
        # Invoke agent
        result = agent_executor.invoke({"messages": context_messages})
        
        final_message = result["messages"][-1]
        response_content = final_message.content
        
        # Save assistant response
        assistant_message = ChatMessage.objects.create(
            session=session,
            role='assistant',
            content=response_content
        )
        
        # Update session timestamp
        session.save()  # This updates updated_at
        
        # Auto-generate title if this is the first exchange
        if session.messages.count() == 2 and session.title == "New Conversation":
            # Use first few words of user's message as title
            title_words = message_content.split()[:6]
            session.title = ' '.join(title_words) + ('...' if len(message_content.split()) > 6 else '')
            session.save()
        
        print(f"Response: {response_content[:100]}...")
        print(f"=== END ===\n")
        
        return Response({
            "user_message": ChatMessageSerializer(user_message).data,
            "assistant_message": ChatMessageSerializer(assistant_message).data,
            "session": ChatSessionListSerializer(session).data
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n=== ERROR in send_message ===")
        print(error_details)
        print(f"=== END ERROR ===\n")
        
        return Response(
            {"error": f"Server error: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_session_messages(request, session_id):
    """
    Get all messages in a session
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    messages = session.messages.all()
    serializer = ChatMessageSerializer(messages, many=True)
    
    return Response({
        "messages": serializer.data,
        "session_id": str(session.id),
        "title": session.title
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def clear_session_messages(request, session_id):
    """
    Clear all messages in a session
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    session.messages.all().delete()
    
    return Response({
        "message": "All messages cleared"
    })