import React from 'react';
import { Link } from 'react-router-dom';
import './ReportCard.css';

function ReportCard({ report, onDownload, onDelete }) {
  const date = report.generated_at
    ? new Date(report.generated_at).toLocaleDateString()
    : 'N/A';
  
  return (
    <div className="report-card">
      <div className="report-card-header">
        <h3>{report.title || 'Untitled Report'}</h3>
        <span className={`report-type ${report.report_type}`}>
          {report.report_type || 'unknown'}
        </span>
      </div>
      
      <div className="report-card-body">
        <p><strong>Generated:</strong> {date}</p>
        <p><strong>Hours Window:</strong> {report.hours_window || 0}h</p>
        {report.json_data && Object.keys(report.json_data).length > 0 && (
          <p><strong>Data Points:</strong> {Object.keys(report.json_data).length}</p>
        )}
      </div>
      
      <div className="report-card-actions">
        <Link to={`/reports/${report.id}`} className="btn btn-primary">
          View
        </Link>
        <button
          onClick={() => onDownload(report.id)}
          className="btn btn-secondary"
        >
          Download
        </button>
        <button
          onClick={() => onDelete(report.id)}
          className="btn btn-danger"
        >
          Archive
        </button>
      </div>
    </div>
  );
}

export default ReportCard;
