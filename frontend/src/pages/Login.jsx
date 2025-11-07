import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import axios from 'axios';
import { 
  HiPhone, 
  HiUser, 
  HiArrowRight, 
  HiArrowLeft,
  HiInformationCircle,
  HiExclamationCircle
} from 'react-icons/hi';
import './Login.css';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

function Login() {
  const [step, setStep] = useState('phone'); // 'phone' or 'otp'
  const [phoneNumber, setPhoneNumber] = useState('');
  const [otp, setOtp] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [, setOtpSent] = useState(false);
  const [countdown, setCountdown] = useState(0);
  
  const { login } = useAuth();
  const navigate = useNavigate();

  // Start countdown timer
  React.useEffect(() => {
    if (countdown > 0) {
      const timer = setTimeout(() => setCountdown(countdown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [countdown]);

  const handleSendOTP = async (e) => {
    e.preventDefault();
    setError('');
    
    // Validate phone number
    if (!phoneNumber.startsWith('+')) {
      setError('Phone number must start with country code (e.g., +91)');
      return;
    }
    
    if (phoneNumber.length < 10) {
      setError('Please enter a valid phone number');
      return;
    }

    setLoading(true);

    try {
      const response = await axios.post(`${API_URL}/auth/send-otp/`, {
        phone_number: phoneNumber
      });

      setOtpSent(true);
      setStep('otp');
      setCountdown(300); // 5 minutes
      setError('');
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to send OTP. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOTP = async (e) => {
    e.preventDefault();
    setError('');
    
    if (otp.length !== 6) {
      setError('Please enter a 6-digit OTP');
      return;
    }

    setLoading(true);

    try {
      const response = await axios.post(`${API_URL}/auth/verify-otp/`, {
        phone_number: phoneNumber,
        otp: otp,
        name: name || undefined
      });

      // Login successful
      login(response.data.user, response.data.tokens);
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.error || 'Invalid OTP. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleResendOTP = async () => {
    if (countdown > 0) return;
    
    setError('');
    setLoading(true);

    try {
      await axios.post(`${API_URL}/auth/send-otp/`, {
        phone_number: phoneNumber
      });
      
      setCountdown(300);
      setError('');
    } catch (err) {
      setError('Failed to resend OTP. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleBack = () => {
    setStep('phone');
    setOtp('');
    setError('');
  };

  return (
    <div className="login-container">
      <div className="login-background">
        <div className="gradient-orb orb-1"></div>
        <div className="gradient-orb orb-2"></div>
        <div className="gradient-orb orb-3"></div>
      </div>

      <div className="login-card">
        <div className="login-header">
          <div className="logo">
            <div className="logo-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2L2 7v10c0 5.55 3.84 9.739 9 11 5.16-1.261 9-5.45 9-11V7l-10-5z"/>
              </svg>
            </div>
            <h1>Legal Assistant</h1>
          </div>
          <p className="tagline">AI-Powered Constitutional Law Research</p>
        </div>

        {step === 'phone' ? (
          <form onSubmit={handleSendOTP} className="login-form">
            <div className="form-group">
              <label htmlFor="phone">Phone Number</label>
              <div className="input-wrapper">
                <HiPhone className="input-icon" />
                <input
                  id="phone"
                  type="tel"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  placeholder="+91 9876543210"
                  className="form-input"
                  disabled={loading}
                  autoFocus
                />
              </div>
              <p className="input-hint">Enter your phone number with country code</p>
            </div>

            {error && (
              <div className="error-message">
                <HiExclamationCircle className="error-icon" />
                {error}
              </div>
            )}

            <button
              type="submit"
              className="btn-primary"
              disabled={loading || !phoneNumber}
            >
              {loading ? (
                <>
                  <div className="spinner-small"></div>
                  Sending OTP...
                </>
              ) : (
                <>
                  Continue
                  <HiArrowRight className="btn-arrow" />
                </>
              )}
            </button>

            <div className="info-box">
              <HiInformationCircle className="info-icon" />
              <p>You'll receive a 6-digit verification code via SMS</p>
            </div>
          </form>
        ) : (
          <form onSubmit={handleVerifyOTP} className="login-form">
            <div className="back-button" onClick={handleBack}>
              <HiArrowLeft /> Change phone number
            </div>

            <div className="phone-display">
              <HiPhone className="phone-icon" />
              <span className="phone-text">{phoneNumber}</span>
            </div>

            <div className="form-group">
              <label htmlFor="otp">Verification Code</label>
              <input
                id="otp"
                type="text"
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="000000"
                className="form-input otp-input"
                disabled={loading}
                maxLength={6}
                autoFocus
              />
              <p className="input-hint">
                {countdown > 0 ? (
                  <>Code expires in {Math.floor(countdown / 60)}:{(countdown % 60).toString().padStart(2, '0')}</>
                ) : (
                  <span className="text-danger">Code expired</span>
                )}
              </p>
            </div>

            <div className="form-group">
              <label htmlFor="name">Name (Optional)</label>
              <div className="input-wrapper">
                <HiUser className="input-icon" />
                <input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  className="form-input"
                  disabled={loading}
                />
              </div>
            </div>

            {error && (
              <div className="error-message">
                <HiExclamationCircle className="error-icon" />
                {error}
              </div>
            )}

            <button
              type="submit"
              className="btn-primary"
              disabled={loading || otp.length !== 6}
            >
              {loading ? (
                <>
                  <div className="spinner-small"></div>
                  Verifying...
                </>
              ) : (
                <>
                  Verify & Continue
                  <HiArrowRight className="btn-arrow" />
                </>
              )}
            </button>

            <button
              type="button"
              className="btn-secondary"
              onClick={handleResendOTP}
              disabled={loading || countdown > 0}
            >
              {countdown > 0 ? `Resend in ${countdown}s` : 'Resend Code'}
            </button>
          </form>
        )}

        <div className="login-footer">
          <p>Your data is encrypted and secure</p>
        </div>
      </div>
    </div>
  );
}

export default Login;