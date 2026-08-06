import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { reportAPI } from '../services/api';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import './ReportDetail.css';

function ReportDetail() {
  const { id } = useParams();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    fetchReport();
  }, [id]);

  const fetchReport = async () => {
    try {
      setLoading(true);
      const response = await reportAPI.getReport(id, true);
      setReport(response.data.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    try {
      setDownloading(true);
      const response = await reportAPI.downloadReportHTML(id);
      const url = window.URL.createObjectURL(new Blob([response.data], { type: 'text/html' }));
      const link = document.createElement('a');
      link.href = url;
      const safeTitle = (report?.title || 'report').replace(/[^a-z0-9]+/gi, '_').toLowerCase();
      link.setAttribute('download', `${safeTitle}_${id}.html`);
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Error downloading report:', err);
      alert('Failed to download report. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

  if (loading) return <div className="report-detail"><p>Loading...</p></div>;
  if (error) return <div className="report-detail"><p>Error: {error}</p></div>;
  if (!report) return <div className="report-detail"><p>Report not found</p></div>;

  return (
    <div className="report-detail">
      <div className="report-detail-header">
        <h1>{report.title}</h1>
        <button
          className="btn btn-download"
          onClick={handleDownload}
          disabled={downloading || !report.html_content}
          title={!report.html_content ? 'No downloadable content available' : 'Download this report'}
        >
          {downloading ? 'Downloading...' : (<><DownloadRoundedIcon fontSize="inherit" /> Download Report</>)}
        </button>
      </div>
      <div className="report-meta">
        <p><strong>Type:</strong> {report.report_type || 'N/A'}</p>
        <p><strong>Generated:</strong> {report.generated_at ? new Date(report.generated_at).toLocaleString() : 'N/A'}</p>
        <p><strong>Hours Window:</strong> {report.hours_window || 0}h</p>
      </div>
      {report.html_content && (
        <iframe
          className="report-content"
          srcDoc={report.html_content}
          title="Report Content"
        />
      )}
    </div>
  );
}

export default ReportDetail;

