import React from 'react';
// Use robot.png for the agent button icon
import agentIcon from '../assets/robot.png'; 

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
      {/* Use img tag for the icon */}
      <img src={agentIcon} alt="LISA Agent Icon" className="agent-button-icon" />
    </button>
  );
};

export default AgentButton; 