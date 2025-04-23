import { useState, useEffect, useRef } from 'react';
import AgentButton from './components/AgentButton';
import ChatInterface from './components/ChatInterface';
import { Message } from './components/MessageList'; // Import the Message type
import { InputBarRef } from './components/InputBar'; // Import InputBarRef
import './AgentStyles.css';

// Environment variable for API URL (ensure your build process handles this)
// For Vite, use import.meta.env.VITE_API_URL
//const API_URL = import.meta.env.VITE_API_URL || 'https://lisa-d7bfbka9fgg9haem.centralindia-01.azurewebsites.net/'; // Fallback for dev
const API_URL = 'http://localhost:8080'; // Fallback for dev

// Helper function to format agent responses
function formatAgentResponse(text: string): string {
  const lines = text.trim().split('\n');
  let formattedLines: string[] = [];
  let srNo = 1;

  // --- Refined Table Parsing --- 
  const isTable = lines.length >= 3 && 
                  lines[0].includes('|') && 
                  lines[1].includes('---') && lines[1].includes('|') &&
                  lines[2].includes('|');

  if (isTable) {
    const headers = lines[0].split('|').map(h => h.trim()).filter(h => h); // Extract headers
    const dataRows = lines.slice(2); 

    for (const row of dataRows) {
      const cells = row.split('|').map(c => c.trim()).filter(c => c);
      if (cells.length === headers.length) {
        for (let i = 0; i < headers.length; i++) {
          // Ensure we don't generate empty items
          if (headers[i] && cells[i]) { 
            formattedLines.push(`${srNo}. **${headers[i]}**: ${cells[i]}`);
            srNo++;
          }
        }
        // NO blank line between table rows items - create one continuous list
      } else {
        // If row is malformed but not empty, add it as raw info
        const trimmedRow = row.trim();
        if (trimmedRow && !trimmedRow.startsWith('|') && !trimmedRow.endsWith('|')) { // Avoid adding empty | lines
           formattedLines.push(`${srNo}. **Info**: ${trimmedRow}`);
           srNo++;
        }
      }
    }
    // If we processed a table, return the result directly
    return formattedLines.join('\n').trim(); 
  }

  // --- Existing logic for non-table formats (key-value, lists) --- 
  // Only run this if it wasn't detected as a table
  const potentialStructureLines = lines.filter(line => line.includes(':') || line.trim().startsWith('*') || line.trim().startsWith('-')).length;
  const alreadyFormatted = /^\s*\d+\.\s+\*\*/.test(lines[0]?.trim() || '');

  if (potentialStructureLines > 1 && !alreadyFormatted) {
    for (const line of lines) {
      const trimmedLine = line.trim();
      if (!trimmedLine) continue;

      let heading = '';
      let details = '';

      const colonIndex = trimmedLine.indexOf(':');
      if (colonIndex > 0) {
        heading = trimmedLine.substring(0, colonIndex).trim();
        heading = heading.replace(/^[-*]\s*/, ''); 
        details = trimmedLine.substring(colonIndex + 1).trim();
      } else if (trimmedLine.startsWith('* ') || trimmedLine.startsWith('- ')) {
         heading = "Item";
         details = trimmedLine.substring(2).trim();
      } else {
        // Avoid numbering single-line plain text responses
        if (lines.length === 1) {
            formattedLines.push(trimmedLine);
            continue; // Don't number single lines
        }
        // If multiple lines but no clear structure, treat as Info
        heading = "Info"; 
        details = trimmedLine;
      }
      
      // Add formatted line if heading and details exist
      if(heading && details) {
          if(heading.startsWith('**') && heading.endsWith('**')){
            formattedLines.push(`${srNo}. ${heading}: ${details}`);
          } else {
            formattedLines.push(`${srNo}. **${heading}**: ${details}`);
          }
          srNo++;
      } else if (trimmedLine) { // Fallback for lines that couldn't be parsed
         formattedLines.push(trimmedLine); // Add as plain line
      }
    }
    return formattedLines.join('\n');
  } 
  
  // --- Fallback: Return original text if no formatting applied --- 
  return lines.join('\n'); 
}

// --- Helper function to generate CSV ---
// (Could be moved to a utils file later)
function convertToCSV(data: Record<string, any>[]): string {
  if (!data || data.length === 0) {
    return '';
  }

  const keys = Object.keys(data[0]);
  const header = keys.map(key => `"${key.replace(/"/g, '""')}"`).join(','); // Quote headers

  const rows = data.map(row => {
    return keys.map(key => {
      let value = row[key];
      if (value === null || value === undefined) {
        value = '';
      } else {
        value = String(value); // Convert to string
        // Quote values containing commas, quotes, or newlines
        if (value.includes(',') || value.includes('"') || value.includes('\n')) {
          value = `"${value.replace(/"/g, '""')}"`;
        }
      }
      return value;
    }).join(',');
  });

  return `${header}\n${rows.join('\n')}`;
}

function App() {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false); // Loading state for API query call
  const [isLoginLoading, setIsLoginLoading] = useState(false); // Separate loading for login
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentBuyerId, setCurrentBuyerId] = useState<number | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const inputBarRef = useRef<InputBarRef>(null); // Create ref for InputBar

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
        setCurrentBuyerId(data.buyer_id); 
        // Set the new welcome message
        const welcomeMessage = `Hi I am LISA: Live Interactive Smart Assistant\nI have information about your Orders, Products and Stocks.\nHow can I help you?`;
        setMessages([{ type: 'agent', text: welcomeMessage }]); 
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

  // Handler for sample query button clicks
  const handleSampleQuerySelect = (queryText: string) => {
    // Use the ref to call the setInputValue method on InputBar
    inputBarRef.current?.setInputValue(queryText);
  };

  // Add the download handler function
  const handleDownloadRawData = (rawData: Record<string, any>[], filename: string = 'details.csv') => {
    if (!rawData || rawData.length === 0) {
      console.error("No raw data to download.");
      // Optionally show a user-friendly message
      return;
    }

    try {
      const csvString = convertToCSV(rawData);
      if (!csvString) {
         console.error("Failed to generate CSV string.");
         return;
      }

      const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement('a');
      const url = URL.createObjectURL(blob);

      link.setAttribute('href', url);
      link.setAttribute('download', filename);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url); // Clean up

    } catch (error) {
       console.error("Error generating or downloading CSV:", error);
       // Optionally show a user-friendly error message
    }
  };

  // Send Message Handler (Modified)
  const handleSendMessage = async (messageText: string) => {
    // Ensure session ID exists before sending
    if (!messageText.trim() || !isLoggedIn || currentBuyerId === null || sessionId === null) {
        console.error("Cannot send message: Not logged in or session ID missing.");
        return; 
    }

    // Re-append Buyer ID to the query text for the LLM
    const queryWithBuyerId = `${messageText} (Buyer ID is ${currentBuyerId})`;

    const userMessage: Message = { type: 'user', text: messageText }; // Show original text to user in UI
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            user_query: queryWithBuyerId, // Send query WITH Buyer ID appended
            session_id: sessionId 
        }), 
      });

      if (!response.ok) {
        let errorMsg = `HTTP error! status: ${response.status}`;
        try { const errorData = await response.json(); errorMsg = errorData.detail || errorMsg; } catch (e) {} 
        throw new Error(errorMsg);
      }

      const data = await response.json();
      const rawAgentResponseText = data.answer || data.error || 'Sorry, I could not process your request.';
      
      // Format the agent response before adding it to state
      const formattedAgentResponseText = formatAgentResponse(rawAgentResponseText);
      
      const agentMessage: Message = {
        type: 'agent',
        text: formattedAgentResponseText,
        raw_data: data.raw_data || undefined // Store raw_data if present
      };
      setMessages(prev => [...prev, agentMessage]);

    } catch (error) {
      console.error("Failed to send message:", error);
      const errorText = error instanceof Error ? error.message : String(error);
      const errorMessage: Message = { type: 'agent', text: `Sorry, I encountered an error: ${errorText}` };
      // Apply formatting to error messages too? Optional.
      // const formattedError: Message = { type: 'agent', text: formatAgentResponse(errorMessage.text) }; 
      // setMessages(prev => [...prev, formattedError]);
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
          onSampleQuerySelect={handleSampleQuerySelect}
          inputBarRef={inputBarRef}
          onDownloadRawData={handleDownloadRawData}
        />
      )}
    </div>
  );
}

export default App;
