import React, { useEffect, useState } from 'react';
import { reportAPI } from '../services/api';
import './Analytics.css';

function Analytics() {
  const [trends, setTrends] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchTrends();
  }, []);

  const fetchTrends = async () => {
    try {
      setLoading(true);
      const response = await reportAPI.getTrends();
      setTrends(response.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div className="analytics"><p>Loading...</p></div>;
  if (error) return <div className="analytics"><p>Error: {error}</p></div>;

  return (
    <div className="analytics">
      <h1>Analytics & Trends</h1>
      <div className="analytics-content">
        <p>90-day trend data will be displayed here as charts.</p>
        {trends && (
          <pre>{JSON.stringify(trends, null, 2)}</pre>
        )}
      </div>
    </div>
  );
}

export default Analytics;
