import React from 'react';

interface SampleQueriesProps {
  onQuerySelect: (queryText: string) => void;
}

const sampleQueriesList = [
  "What is rate of product name {product name}",
  "What are ingredients of Product code {product code}",
  "What is status of my orders placed two days back?",
  "What is status of my order number { order number here}"
];

const SampleQueries: React.FC<SampleQueriesProps> = ({ onQuerySelect }) => {
  return (
    <div className="sample-queries-container">
      <p className="sample-queries-title">Try asking:</p>
      <div className="sample-queries-list">
        {sampleQueriesList.map((query, index) => (
          <button 
            key={index} 
            className="sample-query-button" 
            onClick={() => onQuerySelect(query)}
          >
            {query}
          </button>
        ))}
      </div>
    </div>
  );
};

export default SampleQueries; 