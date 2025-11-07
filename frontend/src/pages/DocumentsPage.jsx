import React, { useState, useEffect } from 'react';
import axiosInstance from '../utils/axios';
import { 
  HiUpload, 
  HiDocument, 
  HiEye, 
  HiDownload, 
  HiTrash, 
  HiSearch,
  HiClock,
  HiCheckCircle,
  HiExclamationCircle
} from 'react-icons/hi';
import './DocumentsPage.css';

function DocumentsPage() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [summaryType, setSummaryType] = useState('comprehensive');
  const [dragActive, setDragActive] = useState(false);
  const [processingDoc, setProcessingDoc] = useState(null);

  useEffect(() => {
    loadDocuments();
  }, []);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const response = await axiosInstance.get('/documents/');
      setDocuments(response.data.documents);
    } catch (error) {
      console.error('Failed to load documents:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setSelectedFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setUploading(true);

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('summary_type', summaryType);

    try {
      const response = await axiosInstance.post('/documents/upload/', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      // Add to list and start summarization
      const newDoc = response.data.document;
      setDocuments([newDoc, ...documents]);
      setSelectedFile(null);

      // Auto-summarize
      handleSummarize(newDoc.id);
    } catch (error) {
      alert('Upload failed: ' + (error.response?.data?.error || 'Unknown error'));
    } finally {
      setUploading(false);
    }
  };

  const handleSummarize = async (docId) => {
    setProcessingDoc(docId);

    try {
      const response = await axiosInstance.post(`/documents/${docId}/summarize/`, {
        summary_type: summaryType
      });

      // Update document in list
      setDocuments(documents.map(doc =>
        doc.id === docId ? response.data.document : doc
      ));
    } catch (error) {
      alert('Summarization failed: ' + (error.response?.data?.error || 'Unknown error'));
    } finally {
      setProcessingDoc(null);
    }
  };

  const handleDelete = async (docId) => {
    if (!window.confirm('Delete this document?')) return;

    try {
      await axiosInstance.delete(`/documents/${docId}/delete/`);
      setDocuments(documents.filter(doc => doc.id !== docId));
    } catch (error) {
      alert('Delete failed: ' + (error.response?.data?.error || 'Unknown error'));
    }
  };

  const handleDownload = (doc) => {
    window.open(doc.file_url, '_blank');
  };

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="documents-page">
      <div className="documents-header">
        <div className="header-content">
          <h1 className="text-gradient">
            <HiDocument className="header-icon" />
            My Documents
          </h1>
          <p>Upload and analyze legal documents with AI-powered summarization</p>
        </div>
      </div>

      {/* Upload Section */}
      <div className="upload-section">
        <div className="upload-card">
          <h2>Upload New Document</h2>

          <div
            className={`drop-zone ${dragActive ? 'active' : ''} ${selectedFile ? 'has-file' : ''}`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
          >
            <input
              type="file"
              id="file-input"
              accept=".pdf,.docx,.doc,.txt"
              onChange={handleFileSelect}
              className="file-input"
            />

            <label htmlFor="file-input" className="drop-zone-label">
              {selectedFile ? (
                <>
                  <div className="file-preview">
                    <HiDocument className="file-icon" />
                    <div className="file-details">
                      <p className="file-name">{selectedFile.name}</p>
                      <p className="file-size">{formatFileSize(selectedFile.size)}</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="change-file"
                    onClick={(e) => {
                      e.preventDefault();
                      setSelectedFile(null);
                    }}
                  >
                    Remove
                  </button>
                </>
              ) : (
                <>
                  <HiUpload className="upload-icon" />
                  <p className="upload-text">Drop your document here or click to browse</p>
                  <p className="upload-hint">Supported: PDF, DOCX, TXT (Max 10MB)</p>
                </>
              )}
            </label>
          </div>

          {selectedFile && (
            <>
              <div className="summary-types">
                <label className="summary-label">Analysis Type:</label>
                <div className="radio-options">
                  {[
                    { value: 'brief', label: 'Brief', desc: 'Quick summary' },
                    { value: 'comprehensive', label: 'Comprehensive', desc: 'Detailed analysis' },
                    { value: 'legal_issues', label: 'Legal Issues', desc: 'Focus on legal aspects' },
                    { value: 'clause_by_clause', label: 'Clause-by-Clause', desc: 'Section breakdown' }
                  ].map(option => (
                    <label key={option.value} className="radio-label">
                      <input
                        type="radio"
                        value={option.value}
                        checked={summaryType === option.value}
                        onChange={(e) => setSummaryType(e.target.value)}
                      />
                      <div className="radio-text">
                        <strong>{option.label}</strong>
                        <span>{option.desc}</span>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              <button
                className="upload-btn"
                onClick={handleUpload}
                disabled={uploading}
              >
                {uploading ? (
                  <>
                    <div className="spinner-small"></div>
                    Uploading...
                  </>
                ) : (
                  <>
                    <HiUpload size={20} />
                    Upload & Analyze
                  </>
                )}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Documents List */}
      <div className="documents-list-section">
        <h2>Your Documents ({documents.length})</h2>

        {loading ? (
          <div className="loading-state">
            <div className="spinner-large"></div>
            <p>Loading documents...</p>
          </div>
        ) : documents.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📭</div>
            <p>No documents yet</p>
            <p className="empty-hint">Upload your first document to get started</p>
          </div>
        ) : (
          <div className="documents-grid">
            {documents.map(doc => (
              <div key={doc.id} className="document-card">
                <div className="doc-header">
                  <div className="doc-icon">
                    {doc.file_type === 'pdf' ? '📕' : doc.file_type === 'docx' ? '📘' : '📄'}
                  </div>
                  <div className="doc-info">
                    <h3 className="doc-name">{doc.file_name}</h3>
                    <p className="doc-meta">
                      {formatFileSize(doc.file_size)} • {formatDate(doc.created_at)}
                    </p>
                  </div>
                </div>

                <div className="doc-status">
                  {doc.status === 'pending' && (
                    <span className="status-badge pending">
                      <HiClock size={16} />
                      Pending
                    </span>
                  )}
                  {doc.status === 'processing' && (
                    <span className="status-badge processing">
                      <div className="spinner-tiny"></div>
                      Processing
                    </span>
                  )}
                  {doc.status === 'completed' && (
                    <span className="status-badge completed">
                      <HiCheckCircle size={16} />
                      Completed
                    </span>
                  )}
                  {doc.status === 'failed' && (
                    <span className="status-badge failed">
                      <HiExclamationCircle size={16} />
                      Failed
                    </span>
                  )}
                </div>

                {doc.summary && (
                  <div className="doc-summary">
                    <p className="summary-label">Summary ({doc.summary_type}):</p>
                    <p className="summary-preview">
                      {doc.summary.length > 200
                        ? doc.summary.substring(0, 200) + '...'
                        : doc.summary}
                    </p>
                  </div>
                )}

                <div className="doc-actions">
                  {doc.status === 'completed' && doc.summary && (
                    <button
                      className="action-btn view"
                      onClick={() => {
                        // Open summary in modal or navigate to detail view
                        alert(doc.summary); // Temporary
                      }}
                    >
                      <HiEye size={16} />
                      View Summary
                    </button>
                  )}

                  {doc.status === 'completed' && !doc.summary && (
                    <button
                      className="action-btn analyze"
                      onClick={() => handleSummarize(doc.id)}
                      disabled={processingDoc === doc.id}
                    >
                      {processingDoc === doc.id ? (
                        <div className="spinner-tiny" />
                      ) : (
                        <HiSearch size={16} />
                      )}
                      Analyze
                    </button>
                  )}

                  <button
                    className="action-btn download"
                    onClick={() => handleDownload(doc)}
                  >
                    <HiDownload size={16} />
                    Download
                  </button>

                  <button
                    className="action-btn delete"
                    onClick={() => handleDelete(doc.id)}
                  >
                    <HiTrash size={16} />
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default DocumentsPage;