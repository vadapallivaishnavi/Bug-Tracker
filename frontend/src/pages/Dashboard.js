import React, { useEffect, useState } from 'react';
import { reportAPI } from '../services/api';
import './Dashboard.css';

function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reportType, setReportType] = useState('team');
  const [hoursWindow, setHoursWindow] = useState(24);
  const [generating, setGenerating] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');

  useEffect(() => {
    fetchMetrics();
  }, []);

  const fetchMetrics = async () => {
    try {
      setLoading(true);
      // Fetch team summary from analytics
      const response = await reportAPI.getTeamAnalytics();
      setMetrics(response.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateReport = async (e) => {
    e.preventDefault();
    try {
      setGenerating(true);
      setSuccessMessage('');
      const response = await reportAPI.createReport({
        report_type: reportType,
        hours_window: parseInt(hoursWindow),
      });
      setSuccessMessage(`Report "${response.data.data.title}" generated successfully!`);
      setTimeout(() => setSuccessMessage(''), 5000);
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  };

  if (loading) return <div className="dashboard"><p>Loading...</p></div>;
  if (error) return <div className="dashboard"><p>Error: {error}</p></div>;

  return (
    <div className="dashboard">
      <h1>Dashboard</h1>
      
      {successMessage && (
        <div className="success-message">{successMessage}</div>
      )}
      
      <div className="generate-report-section">
        <h2>Generate New Report</h2>
        <form onSubmit={handleGenerateReport} className="report-form">
          <div className="form-group">
            <label htmlFor="report-type">Report Type:</label>
            <select
              id="report-type"
              value={reportType}
              onChange={(e) => setReportType(e.target.value)}
              className="form-control"
            >
              <option value="team">Team Report</option>
              <option value="personal">Personal Report</option>
              <option value="project">Project Report</option>
            </select>
          </div>
          
          <div className="form-group">
            <label htmlFor="hours-window">Hours Window:</label>
            <select
              id="hours-window"
              value={hoursWindow}
              onChange={(e) => setHoursWindow(e.target.value)}
              className="form-control"
            >
              <option value="24">Last 24 Hours</option>
              <option value="48">Last 48 Hours</option>
              <option value="72">Last 3 Days</option>
              <option value="168">Last 7 Days</option>
              <option value="720">Last 30 Days</option>
            </select>
          </div>
          
          <button
            type="submit"
            disabled={generating}
            className="btn-generate"
          >
            {generating ? 'Generating...' : 'Generate Report'}
          </button>
        </form>
      </div>
      
      <div className="metrics-grid">
        <div className="metric-card">
          <h3>Total Hours</h3>
          <p className="metric-value">{metrics?.total_hours || 0}</p>
        </div>
        <div className="metric-card">
          <h3>Active Projects</h3>
          <p className="metric-value">{metrics?.project_count || 0}</p>
        </div>
        <div className="metric-card">
          <h3>Active Tasks</h3>
          <p className="metric-value">{metrics?.task_count || 0}</p>
        </div>
        <div className="metric-card">
          <h3>Utilization</h3>
          <p className="metric-value">{metrics?.utilization || 0}%</p>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
