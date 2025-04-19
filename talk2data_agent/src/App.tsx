import React, { useState, useEffect } from 'react';
import AgentButton from './components/AgentButton';
import ChatInterface from './components/ChatInterface';
import { Message } from './components/MessageList'; // Import the Message type
import './AgentStyles.css';

// Environment variable for API URL (ensure your build process handles this)
// For Vite, use import.meta.env.VITE_API_URL
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'; // Fallback for dev

function App() {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false); // Loading state for API query call
  const [isLoginLoading, setIsLoginLoading] = useState(false); // Separate loading for login
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentBuyerId, setCurrentBuyerId] = useState<number | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState('');

  const toggleChat = () => setIsChatOpen(!isChatOpen);

  // Clear messages and login state when chat is closed
  useEffect(() => {
    if (!isChatOpen) {
      // Reset login state if needed, or maintain login across closures?
      // setIsLoggedIn(false); 
      // setCurrentBuyerId(null);
      // setMessages([]); 
      // setLoginError(null);
    }
  }, [isChatOpen]);

  // Login Handler
  const handleLogin = async (username: string, password: string) => {
    setLoginError(null); // Clear previous errors
    setIsLoginLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (!response.ok || data.error) {
        throw new Error(data.error || `HTTP error! status: ${response.status}`);
      }

      if (data.buyer_id) {
        setIsLoggedIn(true);
        setCurrentBuyerId(data.buyer_id);
        setMessages([{ type: 'agent', text: 'Login successful! How can I help you?' }]); // Welcome message on login
      } else {
        // Should be caught by the error check above, but as a fallback
        throw new Error('Login failed: No Buyer ID returned.');
      }

    } catch (error) {
      console.error("Login failed:", error);
      const errorMsg = error instanceof Error ? error.message : 'An unknown login error occurred.';
      setLoginError(errorMsg);
      setIsLoggedIn(false);
      setCurrentBuyerId(null);
    } finally {
      setIsLoginLoading(false);
    }
  };

  // Logout Handler
  const handleLogout = () => {
    setIsLoggedIn(false);
    setCurrentBuyerId(null);
    setMessages([]); // Clear messages on logout
    setLoginError(null);
    // Maybe add a logged out message?
    // setMessages([{ type: 'agent', text: 'You have been logged out.' }]);
  };

  // Send Message Handler (Modified)
  const handleSendMessage = async (messageText: string) => {
    if (!messageText.trim() || !isLoggedIn || currentBuyerId === null) return;

    const queryWithBuyerId = `${messageText} (Buyer ID is ${currentBuyerId})`;
    const userMessage: Message = { type: 'user', text: messageText };
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            user_query: queryWithBuyerId, 
            session_id: sessionId
        }), 
      });

      if (!response.ok) {
        let errorMsg = `HTTP error! status: ${response.status}`;
        try { const errorData = await response.json(); errorMsg = errorData.detail || errorMsg; } catch (e) {} 
        throw new Error(errorMsg);
      }

      const data = await response.json();
      const agentResponseText = data.answer || data.error || 'Sorry, I could not process your request.';
      const agentMessage: Message = { type: 'agent', text: agentResponseText };
      setMessages(prev => [...prev, agentMessage]);

    } catch (error) {
      console.error("Failed to send message:", error);
      const errorText = error instanceof Error ? error.message : String(error);
      const errorMessage: Message = { type: 'agent', text: `Sorry, I encountered an error: ${errorText}` };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="talk2data-agent-container">
      <AgentButton onClick={toggleChat} />
      {isChatOpen && (
        <ChatInterface 
          messages={messages} 
          onSendMessage={handleSendMessage} 
          onClose={toggleChat} 
          isLoggedIn={isLoggedIn}
          onLogin={handleLogin}
          onLogout={handleLogout}
          loginError={loginError}
          isLoginLoading={isLoginLoading}
          isLoading={isLoading}
        />
      )}
    </div>
  );
}

export default App;
