import React, { useEffect, useState, useRef } from 'react';
import { reportAPI } from '../services/api';
import LoadingSpinner from '../components/LoadingSpinner';
import './Reports.css';

export default function Reports() {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [filterType, setFilterType] = useState('');
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [lastRefreshTime, setLastRefreshTime] = useState(new Date());
  const intervalRef = useRef(null);
  const componentMountedRef = useRef(true);

  // Main data fetching function
  const fetchReports = async (showLoading = true) => {
    try {
      if (showLoading) setLoading(true);
      const filters = filterType ? { report_type: filterType } : {};
      const response = await reportAPI.listReports(page, 50, filters);
      
      // Only update state if component is still mounted
      if (componentMountedRef.current) {
        setReports(response.data.data);
        setTotalPages(response.data.pages);
        setError(null);
        setLastRefreshTime(new Date());
      }
    } catch (err) {
      if (componentMountedRef.current) {
        setError(err.message || 'Failed to fetch reports');
        console.error('Error fetching reports:', err);
      }
    } finally {
      if (componentMountedRef.current) {
        setLoading(false);
      }
    }
  };

  // Initial fetch
  useEffect(() => {
    fetchReports();
  }, [page, filterType]);

  // Auto-refresh effect - runs every 5 seconds when enabled
  useEffect(() => {
    if (!autoRefreshEnabled) return;

    // Set interval for auto-refresh
    intervalRef.current = setInterval(() => {
      if (componentMountedRef.current) {
        fetchReports(false); // Don't show loading spinner on auto-refresh
      }
    }, 5000); // 5 seconds

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [autoRefreshEnabled, page, filterType]);

  // Cleanup on component unmount
  useEffect(() => {
    return () => {
      componentMountedRef.current = false;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  const handleDownload = async (reportId) => {
    try {
      const response = await reportAPI.downloadReportHTML(reportId);
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `report_${reportId}.html`);
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
    } catch (err) {
      console.error('Error downloading report:', err);
    }
  };

  const handleDelete = async (reportId) => {
    if (window.confirm('Are you sure you want to archive this report?')) {
      try {
        await reportAPI.deleteReport(reportId);
        fetchReports();
      } catch (err) {
        console.error('Error deleting report:', err);
      }
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const truncateText = (text, maxLength = 50) => {
    if (!text) return 'N/A';
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
  };

  const formatHoursWindow = (hours) => {
    if (!hours) return 'N/A';
    if (hours % 24 === 0) {
      const days = hours / 24;
      return `Last ${days} day${days > 1 ? 's' : ''}`;
    }
    return `Last ${hours}h`;
  };

  if (loading && reports.length === 0) {
    return <LoadingSpinner />;
  }

  return (
    <div className="reports-page-fullscreen">
      <div className="reports-header">
        <div className="header-content">
          <h1>Reports Dashboard</h1>
          <p>All generated reports - Full Screen View</p>
        </div>
        <div className="header-controls">
          <div className="refresh-status">
            <span className={`status-indicator ${autoRefreshEnabled ? 'active' : 'inactive'}`}></span>
            <span className="status-text">
              {autoRefreshEnabled ? 'Auto-Refresh: ON' : 'Auto-Refresh: OFF'}
            </span>
            <span className="last-refresh">
              Last updated: {lastRefreshTime.toLocaleTimeString()}
            </span>
          </div>
          <button
            className="toggle-refresh-btn"
            onClick={() => setAutoRefreshEnabled(!autoRefreshEnabled)}
          >
            {autoRefreshEnabled ? 'Pause' : 'Resume'} Auto-Refresh
          </button>
        </div>
      </div>

      <div className="reports-controls">
        <div className="filter-group">
          <label htmlFor="report-filter">Filter by Type:</label>
          <select
            id="report-filter"
            value={filterType}
            onChange={(e) => {
              setFilterType(e.target.value);
              setPage(1);
            }}
            className="filter-select-large"
          >
            <option value="">All Types</option>
            <option value="team">Team Reports</option>
            <option value="personal">Personal Reports</option>
            <option value="project">Project Reports</option>
          </select>
        </div>
        <button
          className="manual-refresh-btn"
          onClick={() => fetchReports()}
          disabled={loading}
        >
          🔄 Refresh Now
        </button>
      </div>

      {error && <div className="error-message-large">{error}</div>}

      {reports.length === 0 && !loading ? (
        <div className="empty-state-large">
          <h2>No Reports Found</h2>
          <p>Try adjusting your filters or create a new report</p>
        </div>
      ) : (
        <>
          <div className="table-container">
            <table className="reports-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Title</th>
                  <th>Type</th>
                  <th>Time Window</th>
                  <th>Created By</th>
                  <th>Created Date</th>
                  <th>Last Modified</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <tr key={report.id} className="report-row">
                    <td className="cell-id" title={report.id}>{truncateText(report.id, 8)}</td>
                    <td className="cell-title" title={report.title}>
                      {truncateText(report.title, 40)}
                    </td>
                    <td className="cell-type">
                      <span className={`badge badge-${report.report_type || 'default'}`}>
                        {report.report_type || 'N/A'}
                      </span>
                    </td>
                    <td className="cell-window">
                      {formatHoursWindow(report.hours_window)}
                    </td>
                    <td className="cell-creator">
                      {/* user_id is null for team-wide reports; backend
                          reports those as "Team" rather than a blank name. */}
                      {report.created_by || 'Team'}
                    </td>
                    <td className="cell-date">
                      {formatDate(report.created_at)}
                    </td>
                    <td className="cell-date">
                      {formatDate(report.updated_at || report.created_at)}
                    </td>
                    <td className="cell-actions">
                      <button
                        className="action-btn download-btn"
                        onClick={() => handleDownload(report.id)}
                        title="Download Report"
                      >
                        ⬇️ Download
                      </button>
                      <button
                        className="action-btn delete-btn"
                        onClick={() => handleDelete(report.id)}
                        title="Archive Report"
                      >
                        🗑️ Archive
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination-large">
            <button
              className="pagination-btn"
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page === 1}
            >
              ← Previous
            </button>
            <span className="page-info-large">
              Page <strong>{page}</strong> of <strong>{totalPages}</strong>
              {reports.length > 0 && (
                <span className="record-count">
                  {' '}• Showing {reports.length} records
                </span>
              )}
            </span>
            <button
              className="pagination-btn"
              onClick={() => setPage(Math.min(totalPages, page + 1))}
              disabled={page === totalPages}
            >
              Next →
            </button>
          </div>
        </>
      )}
    </div>
  );
}
