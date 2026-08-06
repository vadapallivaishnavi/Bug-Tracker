import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import './App.css';
import Navigation from './components/Navigation';
import WelcomePopup from './components/WelcomePopup';
import Dashboard from './pages/Dashboard';
import Reports from './pages/Reports';
import ReportDetail from './pages/ReportDetail';
import Analytics from './pages/Analytics';
import TeamOverview from './pages/TeamOverview';
import Settings from './pages/Settings';
import TaskWizard from './pages/TaskWizard';
import BugTracker from './pages/BugTracker';
import Login from './pages/Login';
import Register from './pages/Register';
import { authAPI } from './services/api';

function PrivateRoute({ children }) {
  const user = authAPI.getUser();
  return user ? children : <Navigate to="/login" replace />;
}

// Same as PrivateRoute, but also blocks self-registered 'reporter' accounts
// from pages outside the bug tracker. This is the actual gate for direct
// URL access -- Navigation.js hiding the links is just the visible half of
// it; the backend (require_role on each endpoint) is the half that matters
// for security, this is just so a reporter doesn't land on a broken/empty
// page if they type the URL in directly.
function EmployeeRoute({ children }) {
  const user = authAPI.getUser();
  if (!user) return <Navigate to="/login" replace />;
  if (authAPI.isBugTrackerOnlyNav()) return <Navigate to="/bug-tracker" replace />;
  return children;
}

function AppLayout({ children }) {
  return (
    <>
      <Navigation />
      <WelcomePopup />
      <main className="main-content">{children}</main>
    </>
  );
}

function HomeRoute() {
  const user = authAPI.getUser();
  if (!user) return <Navigate to="/login" replace />;
  if (authAPI.isBugTrackerOnlyNav()) return <Navigate to="/bug-tracker" replace />;
  return <AppLayout><Dashboard /></AppLayout>;
}

function App() {
  return (
    <Router>
      <div className="app">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/log-work" element={
            <EmployeeRoute>
              <AppLayout><TaskWizard /></AppLayout>
            </EmployeeRoute>
          } />
          <Route path="/bug-tracker" element={
            <PrivateRoute>
              <AppLayout><BugTracker /></AppLayout>
            </PrivateRoute>
          } />
          <Route path="/" element={<HomeRoute />} />
          <Route path="/reports" element={
            <EmployeeRoute>
              <AppLayout><Reports /></AppLayout>
            </EmployeeRoute>
          } />
          <Route path="/reports/:id" element={
            <EmployeeRoute>
              <AppLayout><ReportDetail /></AppLayout>
            </EmployeeRoute>
          } />
          <Route path="/analytics" element={
            <EmployeeRoute>
              <AppLayout><Analytics /></AppLayout>
            </EmployeeRoute>
          } />
          <Route path="/team" element={
            <EmployeeRoute>
              <AppLayout><TeamOverview /></AppLayout>
            </EmployeeRoute>
          } />
          <Route path="/settings" element={
            <EmployeeRoute>
              <AppLayout><Settings /></AppLayout>
            </EmployeeRoute>
          } />
        </Routes>
      </div>
    </Router>
  );
}

export default App;


