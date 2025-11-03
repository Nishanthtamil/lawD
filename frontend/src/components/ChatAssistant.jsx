// src/components/ChatAssistant.jsx
import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import './ChatAssistant.css';

const API_URL = 'http://localhost:8000/api';

function ChatAssistant() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hello! I\'m your legal assistant. Ask me anything about the Indian Constitution - fundamental rights, articles, parts, or any constitutional provisions.'
    }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage = input.trim();
    setInput('');
    
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setLoading(true);

    try {
      const response = await axios.post(`${API_URL}/chat/`, {
        message: userMessage
      });

      setMessages(prev => [...prev, {
        role: 'assistant',
        content: response.data.response
      }]);
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '❌ Error: ' + (error.response?.data?.error || 'Failed to get response. Please try again.')
      }]);
    } finally {
      setLoading(false);
    }
  };

  const exampleQuestions = [
    "What are fundamental rights?",
    "Explain Article 21",
    "List all articles in Part III",
    "What are the rights of an arrested person?"
  ];

  return (
    <div className="chat-page-container">
      {/* This wrapper scrolls */}
      <div className="chat-messages-wrapper">
        
        {/* Conditional Welcome Screen */}
        {messages.length === 1 && (
          <div className="chat-welcome">
            <h2>Legal Assistant Chat</h2>
            <p>Ask questions about the Indian Constitution</p>
            
            <div className="example-questions">
              <p><strong>Try asking:</strong></p>
              {exampleQuestions.map((q, idx) => (
                <button
                  key={idx}
                  className="example-btn"
                  onClick={() => setInput(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* The Chat Messages */}
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            <div className="message-avatar">
              {msg.role === 'user' ? '👤' : '⚖️'}
            </div>
            <div className="message-content">
              <div className="message-text">{msg.content}</div>
            </div>
          </div>
        ))}
        
        {loading && (
          <div className="message assistant">
            <div className="message-avatar">⚖️</div>
            <div className="message-content">
              <div className="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* This area is fixed at the bottom */}
      <div className="chat-input-area">
        <form className="chat-input-form" onSubmit={handleSubmit}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about constitutional articles, rights, or legal provisions..."
            disabled={loading}
            className="chat-input"
          />
          <button type="submit" disabled={loading || !input.trim()} className="send-btn">
            {loading ? '...' : 'Send'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default ChatAssistant;