import React from 'react';
import { getWelcomePopupImageUrl } from '../services/api';
import './WelcomePopup.css';

/**
 * Pure presentational popup card: an image with an optional title/caption.
 * Used two ways:
 *   1. <WelcomePopup> mounts this automatically right after sign-in.
 *   2. <Navigation>'s small thumbnail mounts this again on click, any time
 *      later in the session, so the same image/caption stays reachable
 *      after the one-time auto-popup has already been dismissed.
 */
function WelcomePopupModal({ popup, onClose }) {
  if (!popup) return null;

  return (
    <div className="welcome-popup-overlay" onClick={onClose}>
      <div className="welcome-popup-card" onClick={(e) => e.stopPropagation()}>
        <button
          className="welcome-popup-close"
          onClick={onClose}
          aria-label="Close"
        >
          &times;
        </button>
        <img
          className="welcome-popup-image"
          src={getWelcomePopupImageUrl()}
          alt={popup.title || 'Welcome'}
        />
        {(popup.title || popup.caption) && (
          <div className="welcome-popup-body">
            {popup.title && <h2 className="welcome-popup-title">{popup.title}</h2>}
            {popup.caption && <p className="welcome-popup-caption">{popup.caption}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

export default WelcomePopupModal;
