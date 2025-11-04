import React, { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import axiosInstance from '../utils/axios';
import './Layout.css';

function Layout({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    try {
      const response = await axiosInstance.get('/chat/sessions/');
      setSessions(response.data.sessions);
    } catch (error) {
      console.error('Failed to load sessions:', error);
    }
  };

  const createNewChat = async () => {
    setLoading(true);
    try {
      const response = await axiosInstance.post('/chat/sessions/create/', {
        title: 'New Conversation'
      });
      setSessions([response.data.session, ...sessions]);
      navigate(`/chat/${response.data.session.id}`);
    } catch (error) {
      console.error('Failed to create session:', error);
    } finally {
      setLoading(false);
    }
  };

  const deleteSession = async (sessionId, e) => {
    e.stopPropagation();
    if (!window.confirm('Delete this conversation?')) return;

    try {
      await axiosInstance.delete(`/chat/sessions/${sessionId}/delete/`);
      setSessions(sessions.filter(s => s.id !== sessionId));
      if (location.pathname.includes(sessionId)) {
        navigate('/');
      }
    } catch (error) {
      console.error('Failed to delete session:', error);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-header">
          <button className="toggle-sidebar" onClick={() => setSidebarOpen(!sidebarOpen)}>
            {sidebarOpen ? '◀' : '▶'}
          </button>
          {sidebarOpen && (
            <div className="logo-sidebar">
              <span className="logo-icon-sm">⚖️</span>
              <span className="logo-text">Legal Assistant</span>
            </div>
          )}
        </div>

        {sidebarOpen && (
          <>
            <button 
              className="new-chat-btn" 
              onClick={createNewChat}
              disabled={loading}
            >
              <span className="btn-icon">✨</span>
              New Chat
            </button>

            <nav className="sidebar-nav">
              <div className="nav-section">
                <h3 className="nav-title">Recent Chats</h3>
                <div className="chat-list">
                  {sessions.length === 0 ? (
                    <div className="empty-state">
                      <p>No conversations yet</p>
                      <p className="empty-hint">Start a new chat to begin</p>
                    </div>
                  ) : (
                    sessions.map(session => (
                      <Link
                        key={session.id}
                        to={`/chat/${session.id}`}
                        className={`chat-item ${location.pathname.includes(session.id) ? 'active' : ''}`}
                      >
                        <div className="chat-item-content">
                          <div className="chat-item-header">
                            <span className="chat-icon">💬</span>
                            <span className="chat-title">{session.title}</span>
                          </div>
                          <div className="chat-meta">
                            <span className="chat-count">{session.message_count} messages</span>
                            <span className="chat-dot">•</span>
                            <span className="chat-time">{formatDate(session.updated_at)}</span>
                          </div>
                        </div>
                        <button
                          className="delete-btn"
                          onClick={(e) => deleteSession(session.id, e)}
                          title="Delete conversation"
                        >
                          🗑️
                        </button>
                      </Link>
                    ))
                  )}
                </div>
              </div>

              <div className="nav-section">
                <Link to="/documents" className="nav-link">
                  <span className="nav-icon">📄</span>
                  <span>My Documents</span>
                </Link>
              </div>
            </nav>

            <div className="sidebar-footer">
              <div className="user-menu-container">
                <button 
                  className="user-button"
                  onClick={() => setShowUserMenu(!showUserMenu)}
                >
                  <div className="user-avatar">{user?.name?.[0] || user?.phone_number?.[0] || 'U'}</div>
                  <div className="user-info">
                    <div className="user-name">{user?.name || 'User'}</div>
                    <div className="user-phone">{user?.phone_number}</div>
                  </div>
                  <span className="menu-arrow">{showUserMenu ? '▲' : '▼'}</span>
                </button>

                {showUserMenu && (
                  <div className="user-dropdown">
                    <Link to="/profile" className="dropdown-item">
                      <span className="dropdown-icon">👤</span>
                      Profile Settings
                    </Link>
                    <button onClick={handleLogout} className="dropdown-item">
                      <span className="dropdown-icon">🚪</span>
                      Logout
                    </button>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </aside>

      {/* Main Content */}
      <main className="main-content">
        {children}
      </main>
    </div>
  );
}

export default Layout;