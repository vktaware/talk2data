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
  const [sessionId, setSessionId] = useState<string | null>(null);

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
    
    // Generate a new session ID for this login attempt
    const newSessionId = crypto.randomUUID(); 
    setSessionId(newSessionId); // Store it in state immediately
    // Use console.log and JS template literal for frontend logging
    console.log(`Generated new session ID for login: ${newSessionId}`); 

    try {
      const response = await fetch(`${API_URL}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Send session ID along with credentials
        body: JSON.stringify({ username, password, session_id: newSessionId }),
      });

      const data = await response.json();

      if (!response.ok || data.error) {
        setSessionId(null); // Clear session ID on failed login
        throw new Error(data.error || `HTTP error! status: ${response.status}`);
      }

      if (data.buyer_id) {
        setIsLoggedIn(true);
        setCurrentBuyerId(data.buyer_id); // Store the buyer ID received from response
        setMessages([{ type: 'agent', text: 'Login successful! How can I help you?' }]); 
        // Session ID remains set from before the fetch call
      } else {
        setSessionId(null); // Clear session ID if login response is weird
        throw new Error('Login failed: No Buyer ID returned.');
      }

    } catch (error) {
      console.error("Login failed:", error);
      const errorMsg = error instanceof Error ? error.message : 'An unknown login error occurred.';
      setLoginError(errorMsg);
      setIsLoggedIn(false);
      setCurrentBuyerId(null);
      setSessionId(null); // Clear session ID on error
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
    setSessionId(null); // Clear session ID on logout
  };

  // Send Message Handler (Modified)
  const handleSendMessage = async (messageText: string) => {
    // Ensure session ID exists before sending
    if (!messageText.trim() || !isLoggedIn || currentBuyerId === null || sessionId === null) {
        console.error("Cannot send message: Not logged in or session ID missing.");
        // Optionally show an error to the user
        // setMessages(prev => [...prev, { type: 'agent', text: 'Error: Session invalid. Please log out and log in again.' }]);
        return; 
    }

    // Append Buyer ID to the query - No longer needed as backend uses session ID
    // const queryWithBuyerId = `${messageText} (Buyer ID is ${currentBuyerId})`;
    const queryToSend = messageText; // Send the original query text

    const userMessage: Message = { type: 'user', text: messageText }; 
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            user_query: queryToSend, 
            session_id: sessionId // Use the stored session ID
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
