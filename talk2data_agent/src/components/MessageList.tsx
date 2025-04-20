import React, { useEffect, useRef } from 'react';
import TypingIndicator from './TypingIndicator'; // Import the loader
import ReactMarkdown from 'react-markdown'; // Import ReactMarkdown

export interface Message {
  type: 'user' | 'agent' | 'loading'; // Add 'loading' type
  text: string;
}

interface MessageListProps {
  messages: Message[];
  isLoading: boolean; // Accept isLoading prop
}

const MessageList: React.FC<MessageListProps> = ({ messages, isLoading }) => {
  const messagesEndRef = useRef<HTMLDivElement>(null); // Ref for scrolling

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  // Adjusted useEffect to scroll when isLoading changes as well,
  // ensuring the loader is scrolled into view when it appears.
  useEffect(() => {
    scrollToBottom(); // Scroll down whenever messages change
  }, [messages, isLoading]);

  return (
    <div className="message-list">
      {messages.map((msg, index) => (
        <div key={index} className={`message ${msg.type}`}>
          <div className="message-content">
            {/* Conditionally render based on message type */}
            {msg.type === 'agent' ? (
              <ReactMarkdown>
                {msg.text}
              </ReactMarkdown>
            ) : (
              msg.text // Render user messages as plain text
            )}
          </div>
        </div>
      ))}
      
      {/* Conditionally render the loader */} 
      {isLoading && (
        <div className="loading-indicator-container">
          <TypingIndicator />
        </div>
      )}
      
      {/* Dummy div to help scroll to the bottom */} 
      <div ref={messagesEndRef} /> 
    </div>
  );
};

export default MessageList; 