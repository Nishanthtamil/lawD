import React, { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import axiosInstance from '../utils/axios';
import { 
  HiMenuAlt3, 
  HiX, 
  HiPlus, 
  HiChat, 
  HiDocument, 
  HiUser, 
  HiLogout,
  HiTrash,
  HiChevronDown,
  HiChevronUp,
  HiSearch
} from 'react-icons/hi';
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
            {sidebarOpen ? <HiX size={18} /> : <HiMenuAlt3 size={18} />}
          </button>
          {sidebarOpen && (
            <div className="logo-sidebar">
              <div className="logo-icon-sm">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 2L2 7v10c0 5.55 3.84 9.739 9 11 5.16-1.261 9-5.45 9-11V7l-10-5z"/>
                </svg>
              </div>
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
              <HiPlus size={20} />
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
                            <HiChat size={16} className="chat-icon" />
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
                          <HiTrash size={14} />
                        </button>
                      </Link>
                    ))
                  )}
                </div>
              </div>

              <div className="nav-section">
                <Link to="/documents" className="nav-link">
                  <HiDocument size={20} className="nav-icon" />
                  <span>My Documents</span>
                </Link>
                <Link to="/documents/summarize" className="nav-link">
                  <HiSearch size={20} className="nav-icon" />
                  <span>Document Summarizer</span>
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
                  {showUserMenu ? <HiChevronUp size={16} /> : <HiChevronDown size={16} />}
                </button>

                {showUserMenu && (
                  <div className="user-dropdown">
                    <Link to="/profile" className="dropdown-item">
                      <HiUser size={18} className="dropdown-icon" />
                      Profile Settings
                    </Link>
                    <button onClick={handleLogout} className="dropdown-item">
                      <HiLogout size={18} className="dropdown-icon" />
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