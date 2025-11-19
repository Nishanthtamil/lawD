// Unified Chat Component - Consolidates ChatAssistant and DocumentSummarizer functionality

import React, { useState, useEffect, useRef } from 'react';
import axios from '../utils/axios';
import './UnifiedChat.css';

const UnifiedChat = () => {
  // State management
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentSession, setCurrentSession] = useState(null);
  const [chatSessions, setChatSessions] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [documents, setDocuments] = useState([]);
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' or 'documents'
  const [systemCapabilities, setSystemCapabilities] = useState(null);
  
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  // Scroll to bottom of messages
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Initialize component
  useEffect(() => {
    loadChatSessions();
    loadDocuments();
    loadSystemCapabilities();
  }, []);

  // ============================================================================
  // API CALLS
  // ============================================================================

  const loadSystemCapabilities = async () => {
    try {
      const response = await axios.get('/api/query/capabilities/');
      setSystemCapabilities(response.data);
    } catch (error) {
      console.error('Failed to load system capabilities:', error);
    }
  };

  const loadChatSessions = async () => {
    try {
      const response = await axios.get('/api/chat/sessions/');
      setChatSessions(response.data.results || response.data);
      
      // Load the most recent session if available
      if (response.data.results?.length > 0) {
        loadChatSession(response.data.results[0].id);
      }
    } catch (error) {
      console.error('Failed to load chat sessions:', error);
    }
  };

  const loadChatSession = async (sessionId) => {
    try {
      const response = await axios.get(`/api/chat/sessions/${sessionId}/messages/`);
      setMessages(response.data.results || response.data);
      setCurrentSession(sessionId);
    } catch (error) {
      console.error('Failed to load chat session:', error);
    }
  };

  const loadDocuments = async () => {
    try {
      const response = await axios.get('/api/documents/');
      setDocuments(response.data.results || response.data);
    } catch (error) {
      console.error('Failed to load documents:', error);
    }
  };

  const createNewSession = async () => {
    try {
      const response = await axios.post('/api/chat/sessions/', {
        title: 'New Chat Session'
      });
      
      const newSession = response.data;
      setChatSessions(prev => [newSession, ...prev]);
      setCurrentSession(newSession.id);
      setMessages([]);
      
      return newSession.id;
    } catch (error) {
      console.error('Failed to create new session:', error);
      return null;
    }
  };

  // ============================================================================
  // CHAT FUNCTIONALITY
  // ============================================================================

  const sendMessage = async () => {
    if (!inputMessage.trim() || isLoading) return;

    const userMessage = {
      id: Date.now(),
      content: inputMessage,
      is_user_message: true,
      created_at: new Date().toISOString(),
      isTemporary: true
    };

    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      let sessionId = currentSession;
      
      // Create new session if none exists
      if (!sessionId) {
        sessionId = await createNewSession();
        if (!sessionId) {
          throw new Error('Failed to create chat session');
        }
      }

      const response = await axios.post('/api/query/chat/', {
        query: inputMessage,
        session_id: sessionId
      });

      // Remove temporary message and add real messages
      setMessages(prev => {
        const filtered = prev.filter(msg => !msg.isTemporary);
        return [
          ...filtered,
          {
            id: response.data.user_message_id,
            content: inputMessage,
            is_user_message: true,
            created_at: new Date().toISOString()
          },
          {
            id: response.data.assistant_message_id,
            content: response.data.response,
            is_user_message: false,
            created_at: response.data.timestamp,
            sources: response.data.sources
          }
        ];
      });

      setInputMessage('');
      
    } catch (error) {
      console.error('Failed to send message:', error);
      
      // Remove temporary message and show error
      setMessages(prev => {
        const filtered = prev.filter(msg => !msg.isTemporary);
        return [
          ...filtered,
          {
            id: Date.now(),
            content: 'Sorry, I encountered an error. Please try again.',
            is_user_message: false,
            created_at: new Date().toISOString(),
            isError: true
          }
        ];
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // ============================================================================
  // DOCUMENT FUNCTIONALITY
  // ============================================================================

  const handleFileSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      setSelectedFile(file);
    }
  };

  const uploadDocument = async () => {
    if (!selectedFile) return;

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('title', selectedFile.name);

    setIsLoading(true);
    setUploadProgress(0);

    try {
      const response = await axios.post('/api/documents/', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const progress = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total
          );
          setUploadProgress(progress);
        },
      });

      // Add uploaded document to list
      setDocuments(prev => [response.data, ...prev]);
      setSelectedFile(null);
      setUploadProgress(0);
      
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }

      // Show success message
      alert('Document uploaded successfully!');
      
    } catch (error) {
      console.error('Failed to upload document:', error);
      alert('Failed to upload document. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const summarizeDocument = async (documentId) => {
    try {
      setIsLoading(true);
      const response = await axios.post(`/api/documents/${documentId}/summarize/`);
      
      // Update document with summary
      setDocuments(prev => 
        prev.map(doc => 
          doc.id === documentId 
            ? { ...doc, summary: response.data.summary }
            : doc
        )
      );
      
    } catch (error) {
      console.error('Failed to summarize document:', error);
      alert('Failed to generate summary. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const deleteDocument = async (documentId) => {
    if (!window.confirm('Are you sure you want to delete this document?')) {
      return;
    }

    try {
      await axios.delete(`/api/documents/${documentId}/`);
      setDocuments(prev => prev.filter(doc => doc.id !== documentId));
    } catch (error) {
      console.error('Failed to delete document:', error);
      alert('Failed to delete document. Please try again.');
    }
  };

  // ============================================================================
  // RENDER HELPERS
  // ============================================================================

  const renderMessage = (message) => (
    <div
      key={message.id}
      className={`message ${message.is_user_message ? 'user-message' : 'assistant-message'} ${
        message.isError ? 'error-message' : ''
      }`}
    >
      <div className="message-content">
        {message.content}
        {message.sources && message.sources.length > 0 && (
          <div className="message-sources">
            <h4>Sources:</h4>
            {message.sources.map((source, index) => (
              <div key={index} className="source-item">
                <span className="source-score">Score: {source.score.toFixed(2)}</span>
                <span className="source-type">{source.source}</span>
                <p className="source-content">{source.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="message-timestamp">
        {new Date(message.created_at).toLocaleTimeString()}
      </div>
    </div>
  );

  const renderDocument = (document) => (
    <div key={document.id} className="document-item">
      <div className="document-header">
        <h3>{document.title}</h3>
        <div className="document-actions">
          <button
            onClick={() => summarizeDocument(document.id)}
            disabled={isLoading}
            className="btn-secondary"
          >
            Summarize
          </button>
          <button
            onClick={() => deleteDocument(document.id)}
            className="btn-danger"
          >
            Delete
          </button>
        </div>
      </div>
      
      <div className="document-info">
        <span className="document-status">
          Status: {document.processing_status || 'Unknown'}
        </span>
        <span className="document-date">
          Uploaded: {new Date(document.uploaded_at || document.created_at).toLocaleDateString()}
        </span>
      </div>

      {document.summary && (
        <div className="document-summary">
          <h4>Summary:</h4>
          <p>{document.summary}</p>
        </div>
      )}
    </div>
  );

  // ============================================================================
  // MAIN RENDER
  // ============================================================================

  return (
    <div className="unified-chat">
      {/* Header */}
      <div className="chat-header">
        <h1>Legal AI Assistant</h1>
        <div className="tab-navigation">
          <button
            className={`tab-button ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
          >
            Chat
          </button>
          <button
            className={`tab-button ${activeTab === 'documents' ? 'active' : ''}`}
            onClick={() => setActiveTab('documents')}
          >
            Documents
          </button>
        </div>
      </div>

      {/* System Status */}
      {systemCapabilities && (
        <div className="system-status">
          <span className={`status-indicator ${
            systemCapabilities.ai_services.status === 'available' ? 'online' : 'offline'
          }`}>
            AI Services: {systemCapabilities.ai_services.status}
          </span>
        </div>
      )}

      {/* Chat Tab */}
      {activeTab === 'chat' && (
        <div className="chat-container">
          {/* Session Sidebar */}
          <div className="sessions-sidebar">
            <div className="sessions-header">
              <h3>Chat Sessions</h3>
              <button onClick={createNewSession} className="btn-primary">
                New Chat
              </button>
            </div>
            <div className="sessions-list">
              {chatSessions.map(session => (
                <div
                  key={session.id}
                  className={`session-item ${currentSession === session.id ? 'active' : ''}`}
                  onClick={() => loadChatSession(session.id)}
                >
                  <div className="session-title">{session.title}</div>
                  <div className="session-date">
                    {new Date(session.updated_at || session.created_at).toLocaleDateString()}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Messages Area */}
          <div className="messages-container">
            <div className="messages-list">
              {messages.length === 0 ? (
                <div className="welcome-message">
                  <h2>Welcome to Legal AI Assistant</h2>
                  <p>Ask me anything about legal documents, constitutional law, or upload documents for analysis.</p>
                </div>
              ) : (
                messages.map(renderMessage)
              )}
              {isLoading && (
                <div className="loading-indicator">
                  <div className="typing-animation">AI is thinking...</div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="input-container">
              <div className="input-wrapper">
                <textarea
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Ask a question about legal documents or constitutional law..."
                  disabled={isLoading}
                  rows={3}
                />
                <button
                  onClick={sendMessage}
                  disabled={!inputMessage.trim() || isLoading}
                  className="send-button"
                >
                  Send
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Documents Tab */}
      {activeTab === 'documents' && (
        <div className="documents-container">
          {/* Upload Section */}
          <div className="upload-section">
            <h2>Upload Document</h2>
            <div className="upload-area">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileSelect}
                accept=".pdf,.docx,.doc,.txt,.jpg,.jpeg,.png,.tiff"
                className="file-input"
              />
              {selectedFile && (
                <div className="selected-file">
                  <span>Selected: {selectedFile.name}</span>
                  <button
                    onClick={uploadDocument}
                    disabled={isLoading}
                    className="btn-primary"
                  >
                    Upload
                  </button>
                </div>
              )}
              {uploadProgress > 0 && uploadProgress < 100 && (
                <div className="upload-progress">
                  <div
                    className="progress-bar"
                    style={{ width: `${uploadProgress}%` }}
                  />
                  <span>{uploadProgress}%</span>
                </div>
              )}
            </div>
          </div>

          {/* Documents List */}
          <div className="documents-list">
            <h2>Your Documents</h2>
            {documents.length === 0 ? (
              <div className="no-documents">
                <p>No documents uploaded yet. Upload your first document to get started!</p>
              </div>
            ) : (
              documents.map(renderDocument)
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default UnifiedChat;