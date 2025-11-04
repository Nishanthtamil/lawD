import React, { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import axiosInstance from '../utils/axios';
import './ChatPage.css';

function ChatPage() {
  const { sessionId } = useParams();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionTitle, setSessionTitle] = useState('');
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    if (sessionId) {
      loadSession();
    } else {
      // New chat - show welcome
      setMessages([{
        role: 'assistant',
        content: 'Hello! I\'m your legal assistant specialized in the Indian Constitution. Ask me anything about constitutional law, fundamental rights, articles, or any legal provisions.'
      }]);
    }
  }, [sessionId]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    adjustTextareaHeight();
  }, [input]);

  const loadSession = async () => {
    try {
      const response = await axiosInstance.get(`/chat/sessions/${sessionId}/messages/`);
      setMessages(response.data.messages);
      setSessionTitle(response.data.title);
    } catch (error) {
      console.error('Failed to load session:', error);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!input.trim()) return;

    const userMessage = input.trim();
    setInput('');

    // Add user message optimistically
    const newUserMessage = {
      role: 'user',
      content: userMessage,
      id: Date.now()
    };
    
    setMessages(prev => [...prev, newUserMessage]);
    setLoading(true);

    try {
      const response = await axiosInstance.post(
        `/chat/sessions/${sessionId}/messages/send/`,
        { message: userMessage }
      );

      // Replace optimistic message with real one and add assistant response
      setMessages(prev => [
        ...prev.filter(m => m.id !== newUserMessage.id),
        response.data.user_message,
        response.data.assistant_message
      ]);

      // Update session title if changed
      if (response.data.session?.title && response.data.session.title !== sessionTitle) {
        setSessionTitle(response.data.session.title);
      }

    } catch (error) {
      // Remove optimistic message on error
      setMessages(prev => prev.filter(m => m.id !== newUserMessage.id));
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '❌ Failed to get response. Please try again.',
        id: Date.now()
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const exampleQuestions = [
    "What are fundamental rights?",
    "Explain Article 21 in detail",
    "List all articles in Part III",
    "What are the rights of an arrested person?",
    "Compare Article 19 and Article 21",
    "What is the Right to Education?"
  ];

  return (
    <div className="chat-page">
      {messages.length === 0 || (messages.length === 1 && messages[0].role === 'assistant' && !sessionId) ? (
        <div className="welcome-screen">
          <div className="welcome-content">
            <div className="welcome-icon">⚖️</div>
            <h1 className="welcome-title">Indian Constitution Legal Assistant</h1>
            <p className="welcome-subtitle">
              Ask me anything about constitutional law, fundamental rights, or legal provisions
            </p>

            <div className="example-grid">
              {exampleQuestions.map((question, idx) => (
                <button
                  key={idx}
                  className="example-card"
                  onClick={() => setInput(question)}
                >
                  <span className="example-icon">💬</span>
                  <span className="example-text">{question}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="messages-container">
          <div className="messages-list">
            {messages.map((msg, idx) => (
              <div key={msg.id || idx} className={`message-wrapper ${msg.role}`}>
                <div className="message-bubble">
                  <div className="message-avatar">
                    {msg.role === 'user' ? (
                      <div className="avatar-user">You</div>
                    ) : (
                      <div className="avatar-assistant">⚖️</div>
                    )}
                  </div>
                  <div className="message-content">
                    <div className="message-text">
                      {msg.content}
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {loading && (
              <div className="message-wrapper assistant">
                <div className="message-bubble">
                  <div className="message-avatar">
                    <div className="avatar-assistant">⚖️</div>
                  </div>
                  <div className="message-content">
                    <div className="typing-animation">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      <div className="input-container">
        <form className="input-form" onSubmit={handleSubmit}>
          <div className="input-wrapper">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about the Constitution..."
              className="message-input"
              rows={1}
              disabled={loading}
            />
            <button
              type="submit"
              className="send-button"
              disabled={loading || !input.trim()}
            >
              {loading ? '⏳' : '↑'}
            </button>
          </div>
          <p className="input-hint">
            Press Enter to send, Shift+Enter for new line
          </p>
        </form>
      </div>
    </div>
  );
}

export default ChatPage;