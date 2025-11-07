import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';
import Login from './pages/Login';
import ChatPage from './pages/ChatPage';
import DocumentsPage from './pages/DocumentsPage';
import DocumentSummarizer from './components/DocumentSummarizer';
import ProfilePage from './pages/ProfilePage';
import './App.css';

function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<Login />} />

          {/* Protected routes */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout>
                  <ChatPage />
                </Layout>
              </ProtectedRoute>
            }
          />

          <Route
            path="/chat/:sessionId"
            element={
              <ProtectedRoute>
                <Layout>
                  <ChatPage />
                </Layout>
              </ProtectedRoute>
            }
          />

          <Route
            path="/documents"
            element={
              <ProtectedRoute>
                <Layout>
                  <DocumentsPage />
                </Layout>
              </ProtectedRoute>
            }
          />

          <Route
            path="/documents/summarize"
            element={
              <ProtectedRoute>
                <Layout>
                  <DocumentSummarizer />
                </Layout>
              </ProtectedRoute>
            }
          />

          <Route
            path="/profile"
            element={
              <ProtectedRoute>
                <Layout>
                  <ProfilePage />
                </Layout>
              </ProtectedRoute>
            }
          />

          {/* Catch all - redirect to home */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </AuthProvider>
  );
}

export default App;
