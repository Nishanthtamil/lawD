
import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import axiosInstance from '../utils/axios';
import './ProfilePage.css';

function ProfilePage() {
  const { user, logout, login } = useAuth();
  const navigate = useNavigate();
  
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState(user?.name || '');
  const [email, setEmail] = useState(user?.email || '');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [stats, setStats] = useState({
    totalSessions: 0,
    totalMessages: 0,
    totalDocuments: 0
  });

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      // Load user statistics
      const [sessionsRes, docsRes] = await Promise.all([
        axiosInstance.get('/chat/sessions/'),
        axiosInstance.get('/documents/')
      ]);

      const sessions = sessionsRes.data.sessions;
      const totalMessages = sessions.reduce((sum, s) => sum + s.message_count, 0);

      setStats({
        totalSessions: sessions.length,
        totalMessages: totalMessages,
        totalDocuments: docsRes.data.documents.length
      });
    } catch (error) {
      console.error('Failed to load stats:', error);
    }
  };

  const handleUpdateProfile = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      const response = await axiosInstance.put('/auth/profile/update/', {
        name: name || undefined,
        email: email || undefined
      });

      // Update local user data
      const tokens = JSON.parse(localStorage.getItem('tokens'));
      login(response.data.user, tokens);

      setSuccess('Profile updated successfully!');
      setEditing(false);

      setTimeout(() => setSuccess(''), 3000);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to update profile');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
  };

  return (
    <div className="profile-page">
      <div className="profile-header">
        <h1>👤 Profile Settings</h1>
        <p>Manage your account and preferences</p>
      </div>

      <div className="profile-content">
        {/* Profile Card */}
        <div className="profile-card">
          <div className="profile-avatar-section">
            <div className="profile-avatar-large">
              {user?.name?.[0] || user?.phone_number?.[0] || 'U'}
            </div>
            <div className="profile-basic-info">
              <h2>{user?.name || 'User'}</h2>
              <p className="phone-number">{user?.phone_number}</p>
              {user?.email && <p className="email">{user.email}</p>}
              <p className="join-date">Member since {formatDate(user?.date_joined)}</p>
            </div>
          </div>

          {success && (
            <div className="success-message">
              <span className="success-icon">✅</span>
              {success}
            </div>
          )}

          {error && (
            <div className="error-message">
              <span className="error-icon">⚠️</span>
              {error}
            </div>
          )}

          {!editing ? (
            <div className="profile-display">
              <div className="info-row">
                <label>Name</label>
                <p>{user?.name || 'Not set'}</p>
              </div>

              <div className="info-row">
                <label>Email</label>
                <p>{user?.email || 'Not set'}</p>
              </div>

              <div className="info-row">
                <label>Phone Number</label>
                <p>{user?.phone_number}</p>
              </div>

              <div className="info-row">
                <label>Verification Status</label>
                <p>
                  {user?.is_verified ? (
                    <span className="badge verified">✓ Verified</span>
                  ) : (
                    <span className="badge unverified">⚠ Not Verified</span>
                  )}
                </p>
              </div>

              <button className="edit-btn" onClick={() => setEditing(true)}>
                ✏️ Edit Profile
              </button>
            </div>
          ) : (
            <form className="profile-form" onSubmit={handleUpdateProfile}>
              <div className="form-group">
                <label htmlFor="name">Name</label>
                <input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  className="form-input"
                />
              </div>

              <div className="form-group">
                <label htmlFor="email">Email</label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="form-input"
                />
              </div>

              <div className="form-group">
                <label>Phone Number</label>
                <input
                  type="text"
                  value={user?.phone_number}
                  disabled
                  className="form-input disabled"
                />
                <p className="input-hint">Phone number cannot be changed</p>
              </div>

              <div className="form-actions">
                <button
                  type="submit"
                  className="save-btn"
                  disabled={loading}
                >
                  {loading ? (
                    <>
                      <span className="spinner-small"></span>
                      Saving...
                    </>
                  ) : (
                    '💾 Save Changes'
                  )}
                </button>
                <button
                  type="button"
                  className="cancel-btn"
                  onClick={() => {
                    setEditing(false);
                    setName(user?.name || '');
                    setEmail(user?.email || '');
                    setError('');
                  }}
                  disabled={loading}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Statistics Card */}
        <div className="stats-card">
          <h3>📊 Your Activity</h3>
          <div className="stats-grid">
            <div className="stat-item">
              <div className="stat-icon">💬</div>
              <div className="stat-info">
                <p className="stat-value">{stats.totalSessions}</p>
                <p className="stat-label">Chat Sessions</p>
              </div>
            </div>

            <div className="stat-item">
              <div className="stat-icon">💭</div>
              <div className="stat-info">
                <p className="stat-value">{stats.totalMessages}</p>
                <p className="stat-label">Total Messages</p>
              </div>
            </div>

            <div className="stat-item">
              <div className="stat-icon">📄</div>
              <div className="stat-info">
                <p className="stat-value">{stats.totalDocuments}</p>
                <p className="stat-label">Documents Analyzed</p>
              </div>
            </div>
          </div>
        </div>

        {/* Actions Card */}
        <div className="actions-card">
          <h3>⚙️ Account Actions</h3>
          
          <button className="action-item" onClick={() => navigate('/documents')}>
            <span className="action-icon">📄</span>
            <div className="action-text">
              <strong>Manage Documents</strong>
              <span>View and manage your uploaded documents</span>
            </div>
            <span className="action-arrow">→</span>
          </button>

          <button className="action-item" onClick={() => navigate('/')}>
            <span className="action-icon">💬</span>
            <div className="action-text">
              <strong>Chat Sessions</strong>
              <span>View your conversation history</span>
            </div>
            <span className="action-arrow">→</span>
          </button>

          <button className="action-item danger" onClick={handleLogout}>
            <span className="action-icon">🚪</span>
            <div className="action-text">
              <strong>Logout</strong>
              <span>Sign out from your account</span>
            </div>
            <span className="action-arrow">→</span>
          </button>
        </div>
      </div>
    </div>
  );
}

export default ProfilePage;