import React, { useState, FormEvent } from 'react';

interface LoginFormProps {
  onLogin: (username: string, password: string) => Promise<void>; // Make async
  error: string | null;
  isLoading: boolean; // Added loading state
}

const LoginForm: React.FC<LoginFormProps> = ({ onLogin, error, isLoading }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!isLoading) { // Prevent multiple submissions
      onLogin(username, password);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="login-form">
      <h3 className="login-title">Login Required</h3>
      <p className="login-subtitle">Please enter your credentials to chat.</p>
      <div className="input-group">
        <label htmlFor="username">Username</label>
        <input
          type="text"
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          disabled={isLoading}
        />
      </div>
      <div className="input-group">
        <label htmlFor="password">Password</label>
        <input
          type="password"
          id="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={isLoading}
        />
      </div>
      {error && <p className="error-message">{error}</p>}
      <button type="submit" className="login-button" disabled={isLoading}>
        {isLoading ? 'Logging in...' : 'Login'}
      </button>
    </form>
  );
};

export default LoginForm; 