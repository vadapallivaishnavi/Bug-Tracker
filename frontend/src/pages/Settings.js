import React, { useEffect, useState } from 'react';
import { authAPI, welcomePopupAPI, getWelcomePopupImageUrl } from '../services/api';
import './Settings.css';

const fileToBase64 = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
  reader.onerror = reject;
  reader.readAsDataURL(file);
});

function WelcomePopupManager() {
  const [popup, setPopup] = useState(null);
  const [title, setTitle] = useState('');
  const [caption, setCaption] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [newImageFile, setNewImageFile] = useState(null);
  const [newImagePreview, setNewImagePreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    welcomePopupAPI.get()
      .then((res) => {
        const data = res.data?.data || {};
        setPopup(data);
        setTitle(data.title || '');
        setCaption(data.caption || '');
        setEnabled(data.enabled !== false);
      })
      .catch(() => setError('Failed to load the current popup configuration.'))
      .finally(() => setLoading(false));
  }, []);

  const handleImageChange = (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setError('Please choose an image file.');
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setError('Image is too large (max 8MB).');
      return;
    }
    setError(null);
    setNewImageFile(file);
    setNewImagePreview(URL.createObjectURL(file));
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const payload = { enabled, title, caption };
      if (newImageFile) {
        payload.image = {
          filename: newImageFile.name,
          content_type: newImageFile.type,
          content_b64: await fileToBase64(newImageFile),
        };
      }
      const res = await welcomePopupAPI.update(payload);
      setPopup(res.data?.data || null);
      setNewImageFile(null);
      setNewImagePreview(null);
      setMessage('Saved. The new popup will show the next time someone signs in or creates an account.');
    } catch (e) {
      setError(e.response?.data?.message || 'Failed to save changes.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p>Loading...</p>;

  return (
    <div className="settings-content">
      <h2>Sign-in Welcome Popup</h2>
      <p>
        Shown once, right after any user signs in or creates an account. Swap the image or
        turn it off any time -- changes apply immediately, no redeploy needed.
      </p>

      <div className="welcome-popup-settings-row">
        <label className="welcome-popup-settings-toggle">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          Enabled
        </label>
      </div>

      <div className="welcome-popup-settings-preview">
        {newImagePreview ? (
          <img src={newImagePreview} alt="New preview" />
        ) : popup?.has_image ? (
          <img src={getWelcomePopupImageUrl()} alt="Current popup" />
        ) : (
          <span className="welcome-popup-settings-empty">No image set yet</span>
        )}
      </div>

      <label className="welcome-popup-settings-upload-btn" htmlFor="welcome-popup-image">
        {popup?.has_image || newImageFile ? 'Replace image' : 'Choose image'}
      </label>
      <input
        id="welcome-popup-image"
        type="file"
        accept="image/*"
        onChange={handleImageChange}
        style={{ display: 'none' }}
      />

      <div className="welcome-popup-settings-field">
        <label>Title (optional)</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. What's new"
          maxLength={255}
        />
      </div>

      <div className="welcome-popup-settings-field">
        <label>Caption (optional)</label>
        <textarea
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          placeholder="A short note shown under the image"
          rows={3}
          maxLength={2000}
        />
      </div>

      {error && <div className="welcome-popup-settings-error">{error}</div>}
      {message && <div className="welcome-popup-settings-success">{message}</div>}

      <button
        className="welcome-popup-settings-save"
        onClick={handleSave}
        disabled={saving}
      >
        {saving ? 'Saving...' : 'Save changes'}
      </button>
    </div>
  );
}

function Settings() {
  const user = authAPI.getUser();
  const isAdmin = user?.role === 'admin';

  return (
    <div className="settings">
      <h1>Settings</h1>
      {isAdmin ? (
        <WelcomePopupManager />
      ) : (
        <div className="settings-content">
          <h2>Configuration</h2>
          <p>Application settings and configuration options will appear here.</p>
        </div>
      )}
    </div>
  );
}

export default Settings;
