import React, { useState } from 'react';
import axiosInstance from '../utils/axios';
import { 
  HiUpload, 
  HiDocument, 
  HiDownload, 
  HiRefresh,
  HiCheckCircle,
  HiExclamationCircle
} from 'react-icons/hi';
import './DocumentSummarizer.css';

// Remove API_URL since we're using axiosInstance

function DocumentSummarizer() {
  const [file, setFile] = useState(null);
  const [summaryType, setSummaryType] = useState('comprehensive');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [dragActive, setDragActive] = useState(false);

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      setFile(selectedFile);
      setResult(null);
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
      setFile(e.dataTransfer.files[0]);
      setResult(null);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!file) return;

    setLoading(true);
    setResult(null);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('summary_type', summaryType);

    try {
      const response = await axiosInstance.post('/documents/upload/', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      // Auto-summarize the uploaded document
      const docId = response.data.document.id;
      const summaryResponse = await axiosInstance.post(`/documents/${docId}/summarize/`, {
        summary_type: summaryType
      });

      setResult({
        ...summaryResponse.data.document,
        file_name: file.name
      });
    } catch (error) {
      setResult({
        error: error.response?.data?.error || 'Failed to summarize document. Please try again.'
      });
    } finally {
      setLoading(false);
    }
  };

  const downloadSummary = () => {
    if (!result || result.error) return;

    const text = `DOCUMENT SUMMARY
================
File: ${result.file_name}
Summary Type: ${result.summary_type}
Generated: ${new Date().toLocaleString()}

${result.summary}`;

    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `summary_${result.file_name}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="summarizer-container">
      <div className="summarizer-header">
        <h2 className="text-gradient">
          <HiDocument className="header-icon" />
          Document Summarizer
        </h2>
        <p>Upload legal documents for AI-powered analysis with constitutional context</p>
      </div>

      <div className="upload-section">
        <form onSubmit={handleSubmit}>
          <div
            className={`file-drop-zone ${dragActive ? 'active' : ''} ${file ? 'has-file' : ''}`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
          >
            <input
              type="file"
              id="file-upload"
              accept=".pdf,.docx,.doc,.txt"
              onChange={handleFileChange}
              className="file-input"
            />
            <label htmlFor="file-upload" className="file-label">
              {file ? (
                <>
                  <HiDocument className="file-icon" />
                  <p className="file-name">{file.name}</p>
                  <p className="file-size">
                    {(file.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                  <button
                    type="button"
                    className="change-file-btn"
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById('file-upload').click();
                    }}
                  >
                    Change File
                  </button>
                </>
              ) : (
                <>
                  <HiUpload className="upload-icon" />
                  <p className="upload-text">
                    Drop your document here or click to browse
                  </p>
                  <p className="upload-hint">
                    Supported: PDF, DOCX, TXT (Max 10MB)
                  </p>
                </>
              )}
            </label>
          </div>

          <div className="summary-type-selector">
            <label className="selector-label">Choose Analysis Type:</label>
            <div className="radio-group">
              <label className="radio-option">
                <input
                  type="radio"
                  value="brief"
                  checked={summaryType === 'brief'}
                  onChange={(e) => setSummaryType(e.target.value)}
                />
                <div className="radio-content">
                  <strong>Brief Overview</strong>
                  <span>Quick 2-3 paragraph summary</span>
                </div>
              </label>

              <label className="radio-option">
                <input
                  type="radio"
                  value="comprehensive"
                  checked={summaryType === 'comprehensive'}
                  onChange={(e) => setSummaryType(e.target.value)}
                />
                <div className="radio-content">
                  <strong>Comprehensive Analysis</strong>
                  <span>Detailed with constitutional references</span>
                </div>
              </label>

              <label className="radio-option">
                <input
                  type="radio"
                  value="legal_issues"
                  checked={summaryType === 'legal_issues'}
                  onChange={(e) => setSummaryType(e.target.value)}
                />
                <div className="radio-content">
                  <strong>Legal Issues Analysis</strong>
                  <span>Focus on legal questions & conflicts</span>
                </div>
              </label>

              <label className="radio-option">
                <input
                  type="radio"
                  value="clause_by_clause"
                  checked={summaryType === 'clause_by_clause'}
                  onChange={(e) => setSummaryType(e.target.value)}
                />
                <div className="radio-content">
                  <strong>Clause-by-Clause</strong>
                  <span>Detailed section-wise breakdown</span>
                </div>
              </label>
            </div>
          </div>

          <button
            type="submit"
            disabled={!file || loading}
            className="analyze-btn"
          >
            {loading ? (
              <>
                <div className="spinner-small" />
                Analyzing...
              </>
            ) : (
              <>
                <HiRefresh size={20} />
                Analyze Document
              </>
            )}
          </button>
        </form>
      </div>

      {loading && (
        <div className="loading-indicator">
          <div className="spinner"></div>
          <p>Analyzing document with constitutional context...</p>
          <p className="loading-steps">
            Reading document → Extracting concepts → Querying database → Generating analysis
          </p>
        </div>
      )}

      {result && (
        <div className="result-section">
          {result.error ? (
            <div className="error-result glass-effect">
              <div className="error-header">
                <HiExclamationCircle size={24} />
                <h3>Analysis Failed</h3>
              </div>
              <p>{result.error}</p>
            </div>
          ) : (
            <div className="success-result glass-effect">
              <div className="result-header">
                <div className="result-info">
                  <div className="success-header">
                    <HiCheckCircle size={24} />
                    <h3>Analysis Complete</h3>
                  </div>
                  <p className="result-meta">
                    File: {result.file_name} | Type: {result.summary_type?.replace('_', ' ') || summaryType.replace('_', ' ')}
                  </p>
                </div>
                <button onClick={downloadSummary} className="download-btn">
                  <HiDownload size={18} />
                  Download Summary
                </button>
              </div>
              
              <div className="summary-content">
                <pre>{result.summary}</pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default DocumentSummarizer;

