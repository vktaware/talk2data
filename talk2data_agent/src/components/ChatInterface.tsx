import React from 'react';
import MessageList, { Message } from './MessageList';
import InputBar, { InputBarRef } from './InputBar';
import LoginForm from './LoginForm';
import SampleQueries from './SampleQueries';

// Use favicon.png for the chat header logo
import logoSrc from '../assets/favicon.png'; 

interface ChatInterfaceProps {
  messages: Message[];
  onSendMessage: (message: string) => void;
  onClose: () => void;
  isLoggedIn: boolean;
  onLogin: (username: string, password: string) => Promise<void>;
  onLogout: () => void;
  loginError: string | null;
  isLoginLoading: boolean;
  isLoading: boolean;
  onSampleQuerySelect: (queryText: string) => void;
  inputBarRef: React.RefObject<InputBarRef | null>;
  onDownloadRawData: (rawData: Record<string, any>[], filename?: string) => void;
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({ 
  messages, 
  onSendMessage, 
  onClose, 
  isLoggedIn, 
  onLogin,
  onLogout,
  loginError,
  isLoginLoading,
  isLoading,
  onSampleQuerySelect,
  inputBarRef,
  onDownloadRawData
}) => {
  const showSampleQueries = isLoggedIn && messages.length === 1;

  return (
    <div className={`chat-interface ${!isLoggedIn ? 'login-mode' : ''}`}>
      <div className="chat-header">
        {/* Replace span with img tag */}
        <img src={logoSrc} alt="Logo" className="chat-logo-icon" /> 
        <h2>LISA : Live Interactive Smart Assistant</h2>
        <div>
          {isLoggedIn && (
            <button onClick={onLogout} className="logout-button" aria-label="Logout">
              Logout
            </button>
          )}
          <button onClick={onClose} className="close-button" aria-label="Close Chat">×</button>
        </div>
      </div>

      {!isLoggedIn ? (
        <LoginForm 
          onLogin={onLogin} 
          error={loginError}
          isLoading={isLoginLoading}
        />
      ) : (
        <>
          <MessageList messages={messages} isLoading={isLoading} onDownloadRawData={onDownloadRawData} />
          {showSampleQueries && <SampleQueries onQuerySelect={onSampleQuerySelect} />}
          <InputBar ref={inputBarRef} onSendMessage={onSendMessage} />
        </>
      )}
    </div>
  );
};

export default ChatInterface; 