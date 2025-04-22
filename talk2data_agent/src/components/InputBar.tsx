import { useState, KeyboardEvent, forwardRef, useImperativeHandle, useRef } from 'react';

interface InputBarProps {
  onSendMessage: (message: string) => void;
  // isLoading?: boolean; // Optional: To disable input/button during API call
}

// Define the type for the methods exposed via the ref
export interface InputBarRef {
  setInputValue: (value: string) => void;
}

const InputBar = forwardRef<InputBarRef, InputBarProps>(({ onSendMessage }, ref) => {
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null); // Ref for the actual input element

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

  // Expose the setInputValue method via the ref
  useImperativeHandle(ref, () => ({
    setInputValue: (value: string) => {
      setInputValue(value);
      // Optionally focus the input after setting the value
      inputRef.current?.focus();
    }
  }));

  return (
    <div className="input-bar">
      <input
        ref={inputRef} // Attach ref to the input element
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
});

export default InputBar; 