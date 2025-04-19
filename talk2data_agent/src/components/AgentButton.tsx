import React from 'react';

// Using FontAwesome for an icon - you might need to install it:
// npm install @fortawesome/fontawesome-svg-core @fortawesome/free-solid-svg-icons @fortawesome/react-fontawesome
// Or use a simpler text/SVG icon if preferred.
// import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
// import { faCommentDots } from '@fortawesome/free-solid-svg-icons';

interface AgentButtonProps {
  onClick: () => void;
}

const AgentButton: React.FC<AgentButtonProps> = ({ onClick }) => {
  return (
    <button onClick={onClick} className="agent-button" aria-label="Toggle Chat">
      {/* Replace with an actual icon if desired */}
      {/* <FontAwesomeIcon icon={faCommentDots} /> */}
      🤖 {/* Simple Robot Emoji Icon */}
    </button>
  );
};

export default AgentButton; 