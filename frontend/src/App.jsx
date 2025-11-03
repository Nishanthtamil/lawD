import React from 'react';
import { BrowserRouter as Router, Routes, Route, NavLink } from 'react-router-dom';
import ChatAssistant from './components/ChatAssistant';
import DocumentSummarizer from './components/DocumentSummarizer';
import { HiOutlineChatAlt2, HiOutlineDocumentText, HiOutlineScale } from 'react-icons/hi';
import './App.css';

function App() {
  return (
    <Router>
      <div className="app-layout">
        <nav className="sidebar">
          <div className="sidebar-header">
            <h1><HiOutlineScale /> LawD</h1>
            <p>Indian Constitution AI</p>
          </div>
          
          <div className="nav-links">
            <NavLink to="/" className="nav-link" end>
              <HiOutlineChatAlt2 size={20} />
              <span>Your Legal Assistant</span>
            </NavLink>
            <NavLink to="/summarize" className="nav-link">
              <HiOutlineDocumentText size={20} />
              <span>Document Summarization</span>
            </NavLink>
          </div>
          
          <footer className="sidebar-footer">
            <p>© 2025 Legal Assistant</p>
          </footer>
        </nav>

        <main className="main-content">
          <Routes>
            <Route path="/" element={<ChatAssistant />} />
            <Route path="/summarize" element={<DocumentSummarizer />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;