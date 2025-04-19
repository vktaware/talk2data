import React from 'react';
import MessageList, { Message } from './MessageList';
import InputBar from './InputBar';
import LoginForm from './LoginForm';

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
  isLoading
}) => {
  return (
    <div className={`chat-interface ${!isLoggedIn ? 'login-mode' : ''}`}>
      <div className="chat-header">
        <h2>TalkToData Agent</h2>
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
          <MessageList messages={messages} isLoading={isLoading} />
          <InputBar onSendMessage={onSendMessage} />
        </>
      )}
    </div>
  );
};

export default ChatInterface; 