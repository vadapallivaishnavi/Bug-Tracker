import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authAPI, welcomePopupAPI, getWelcomePopupImageUrl } from '../services/api';
import WelcomePopupModal from './WelcomePopupModal';
import './Navigation.css';

// Edit these to point at your real recordings -- label is what shows in the
// dropdown, url is the YouTube link it opens in a new tab.
const INSTALLATION_DEMO_VIDEOS = [
  { label: 'Getting Started (5 min)', url: 'https://www.youtube.com/watch?v=REPLACE_ME_1' },
  { label: 'After Installation', url: 'https://youtu.be/QoVWLt-mGo4?si=ucjnif4kyTe34YCo' },
];

function HelpMenu() {
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    const onEsc = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  return (
    <div className="nav-help-menu" ref={menuRef}>
      <button
        className="nav-help-btn"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
      >
        Help <span className="nav-help-caret">&#9662;</span>
      </button>
      {open && (
        <div className="nav-help-dropdown">
          <a
            className="nav-help-dropdown-item"
            href="/installation-guide.html"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
          >
            Installation
          </a>
          <div className="nav-help-dropdown-section">Installation Demo</div>
          {INSTALLATION_DEMO_VIDEOS.map((video) => (
            <a
              key={video.url}
              className="nav-help-dropdown-item nav-help-dropdown-item--video"
              href={video.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
            >
              &#9658; {video.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

// Small round thumbnail of the same image WelcomePopup shows once after
// sign-in, so it stays reachable for the rest of the session instead of
// disappearing after that first view. Fetches the popup metadata once on
// mount (cheap -- it's just title/caption/enabled flags, the image itself
// loads lazily via <img src>) and simply renders nothing if there's no
// enabled image to show, e.g. an admin has turned the popup off.
function WelcomeThumbnail() {
  const [popup, setPopup] = useState(null);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    welcomePopupAPI.get()
      .then((res) => {
        const data = res.data?.data;
        if (data && data.enabled && data.has_image) {
          setPopup(data);
        }
      })
      .catch(() => {});
  }, []);

  if (!popup) return null;

  return (
    <>
      <button
        className="nav-welcome-thumb"
        onClick={() => setShowModal(true)}
        title={popup.title || 'Welcome'}
        aria-label="View welcome image"
      >
        <img
          className="nav-welcome-thumb-img"
          src={getWelcomePopupImageUrl()}
          alt={popup.title || 'Welcome'}
        />
      </button>
      {showModal && (
        <WelcomePopupModal popup={popup} onClose={() => setShowModal(false)} />
      )}
    </>
  );
}

function Navigation() {
  const navigate = useNavigate();
  const user = authAPI.getUser();
  const restrictedNav = authAPI.isBugTrackerOnlyNav();

  const handleLogout = () => {
    authAPI.logout();
    navigate('/login');
  };

  return (
    <nav className="navigation">
      <div className="nav-container">
        <Link to={restrictedNav ? '/bug-tracker' : '/'} className="nav-brand">
          OSDBcortex
        </Link>
        <ul className="nav-menu">
          {!restrictedNav && <li><Link to="/">Dashboard</Link></li>}
          {!restrictedNav && <li><Link to="/reports">Reports</Link></li>}
          {!restrictedNav && <li><Link to="/analytics">Analytics</Link></li>}
          {!restrictedNav && <li><Link to="/team">Team</Link></li>}
          {!restrictedNav && <li><Link to="/log-work">Log Work</Link></li>}
          <li><Link to="/bug-tracker">Bug Tracker</Link></li>
          {!restrictedNav && <li><Link to="/settings">Settings</Link></li>}
        </ul>
        <div className="nav-user">
          <WelcomeThumbnail />
          <span className="nav-user-name">{user?.name || ''}</span>
          <HelpMenu />
          <button className="nav-logout-btn" onClick={handleLogout}>Logout</button>
        </div>
      </div>
    </nav>
  );
}

export default Navigation;
