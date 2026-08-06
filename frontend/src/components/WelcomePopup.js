import React, { useEffect, useState } from 'react';
import { welcomePopupAPI } from '../services/api';
import WelcomePopupModal from './WelcomePopupModal';

/**
 * Shown once right after a user signs in or creates an account (Login.js /
 * Register.js set a one-shot sessionStorage flag via authAPI.setSession).
 * Content is entirely admin-editable from Settings -- swap the image, change
 * the caption, or turn it off -- with no code change or redeploy, which is
 * what makes this "dynamic".
 *
 * This is only the auto-show-once trigger; the actual card is
 * <WelcomePopupModal>, which <Navigation>'s thumbnail also reuses so the
 * same image stays viewable later in the session.
 */
function WelcomePopup() {
  const [popup, setPopup] = useState(null);

  useEffect(() => {
    const shouldCheck = sessionStorage.getItem('showWelcomePopup') === '1';
    sessionStorage.removeItem('showWelcomePopup');
    if (!shouldCheck) return;

    welcomePopupAPI.get()
      .then((res) => {
        const data = res.data?.data;
        if (data && data.enabled && data.has_image) {
          setPopup(data);
        }
      })
      .catch(() => {});
  }, []);

  return <WelcomePopupModal popup={popup} onClose={() => setPopup(null)} />;
}

export default WelcomePopup;
