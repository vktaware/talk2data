import React, { useState, KeyboardEvent } from 'react';

interface InputBarProps {
  onSendMessage: (message: string) => void;
  // isLoading?: boolean; // Optional: To disable input/button during API call
}

const InputBar: React.FC<InputBarProps> = ({ onSendMessage }) => {
  const [inputValue, setInputValue] = useState('');

  const handleSend = () => {
    if (inputValue.trim()) {
      onSendMessage(inputValue);
      setInputValue('');
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      handleSend();
    }
  };

  return (
    <div className="input-bar">
      <input
        type="text"
        placeholder="Ask about products or orders..."
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        // disabled={isLoading} // Optional
      />
      <button onClick={handleSend} > {/* disabled={isLoading || !inputValue.trim()} Optional */} 
        Send
      </button>
    </div>
  );
};

export default InputBar; 