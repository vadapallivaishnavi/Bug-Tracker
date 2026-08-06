import axios from 'axios';

const defaultHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
const defaultProtocol = typeof window !== 'undefined' ? window.location.protocol : 'http:';
const API_BASE_URL =
  process.env.REACT_APP_API_URL ||
  `${defaultProtocol}//${defaultHost}:5100/api`;

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// These attachment/image endpoints sit behind the same JWT auth as the rest
// of the bugtracker API, but they're used as plain <a href>/<img src>
// targets so the browser can't attach an Authorization header to them --
// so the token is passed as ?token=... instead (the backend accepts the
// token from either place; see JWT_TOKEN_LOCATION in backend/app.py).
const withAuthToken = (url) => {
  const token = localStorage.getItem('token');
  if (!token) return url;
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
};

export const getAttachmentViewUrl = (attachmentId) => withAuthToken(`${API_BASE_URL}/bugtracker/attachments/${attachmentId}`);
export const getAttachmentDownloadUrl = (attachmentId) => withAuthToken(`${API_BASE_URL}/bugtracker/attachments/${attachmentId}/download`);
// Legacy: pre-multi-image posts only have a single image keyed by update id.
export const getUpdateImageUrl = (updateId) => withAuthToken(`${API_BASE_URL}/bugtracker/updates/${updateId}/image`);
// Multi-image gallery: each image has its own id.
export const getUpdateGalleryImageUrl = (imageId) => withAuthToken(`${API_BASE_URL}/bugtracker/updates/images/${imageId}`);
export const getUpdateAttachmentViewUrl = (attachmentId) => withAuthToken(`${API_BASE_URL}/bugtracker/updates/attachments/${attachmentId}`);
export const getUpdateAttachmentDownloadUrl = (attachmentId) => withAuthToken(`${API_BASE_URL}/bugtracker/updates/attachments/${attachmentId}/download`);

// Add token to requests if available
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle response errors
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export const authAPI = {
  login: (email, password) =>
    apiClient.post('/auth/login', { email, password }),

  register: (name, email, password) =>
    apiClient.post('/auth/register', { name, email, password }),

  getMe: () => apiClient.get('/auth/me'),

  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
  },

  getUser: () => {
    const raw = localStorage.getItem('user');
    return raw ? JSON.parse(raw) : null;
  },

  // 'reporter' accounts are self-registered and only get bug-tracker
  // access; 'employee'/'admin' accounts are synced from Odoo and see the
  // full navbar. See Navigation.js and App.js's RoleRoute.
  isReporter: () => authAPI.getUser()?.role === 'reporter',

  // True for actual reporters AND for any admin/employee account flagged
  // bug_tracker_only (e.g. a review-only admin) -- both get the same
  // restricted navbar (Bug Tracker + Help + name + Logout only). Unlike
  // isReporter, this does NOT affect what bug reports the account can see
  // -- that scoping is purely role-based on the backend.
  isBugTrackerOnlyNav: () => {
    const user = authAPI.getUser();
    return user?.role === 'reporter' || !!user?.bug_tracker_only;
  },

  setSession: (token, user) => {
    localStorage.setItem('token', token);
    localStorage.setItem('user', JSON.stringify(user));
    // Consumed once by <WelcomePopup> right after landing on the next page.
    sessionStorage.setItem('showWelcomePopup', '1');
  },
};

export const welcomePopupAPI = {
  get: () => apiClient.get('/welcome-popup'),
  update: (data) => apiClient.post('/welcome-popup', data),
};
export const getWelcomePopupImageUrl = () => withAuthToken(`${API_BASE_URL}/welcome-popup/image`);

export const reportAPI = {
  // Health check
  healthCheck: () => apiClient.get('/health'),

  // Force a fresh pull of users/projects/tasks/timesheets from Odoo.
  // Used so newly-created Odoo tasks show up immediately (e.g. before
  // opening the Log Work project/task pickers).
  syncOdoo: (hours = 24) => apiClient.post('/sync', { hours }),

  // Users
  getUsers: () => apiClient.get('/users'),
  getUser: (userId) => apiClient.get(`/users/${userId}`),

  // Projects
  getProjects: () => apiClient.get('/projects'),

  // Tasks
  getTasks: (projectId) =>
    apiClient.get('/tasks', {
      params: projectId ? { project_id: projectId } : {},
    }),

  getTaskContext: (taskId, summary, status) =>
    apiClient.get(`/tasks/${taskId}/context`, {
      params: {
        ...(summary ? { summary } : {}),
        ...(status ? { status } : {}),
      },
    }),

  generateTaskSummary: (taskId, data) =>
    apiClient.post(`/tasks/${taskId}/summary`, data),

  searchOdooUsers: (q) =>
    apiClient.get('/odoo/users/search', { params: { q } }),

  sendSummaryEmail: (data) => apiClient.post('/email/send', data),

  // Timesheets
  logTimesheet: (data) => apiClient.post('/timesheets/log', data),

  // XWiki
  getXWikiConfig: () => apiClient.get('/xwiki/config'),

  getXWikiPage: (space, page) =>
    apiClient.get('/xwiki/page', { params: { space, page } }),

  saveXWikiPage: (data) => apiClient.post('/xwiki/page', data),

  saveXWikiAttachment: (data) => apiClient.post('/xwiki/attachment', data),

  saveKbLocal: (data) => apiClient.post('/kb/save', data),

  convertMdToXwiki: (markdown) => apiClient.post('/xwiki/convert', { markdown }),

  // Reports
  listReports: (page = 1, perPage = 20, filters = {}) =>
    apiClient.get('/reports', {
      params: { page, per_page: perPage, ...filters },
    }),

  getReport: (reportId, includeHtml = false) =>
    apiClient.get(`/reports/${reportId}`, {
      params: { include_html: includeHtml },
    }),

  createReport: (data) => apiClient.post('/reports', data),

  downloadReportHTML: (reportId) =>
    apiClient.get(`/reports/${reportId}/html`, {
      responseType: 'blob',
    }),

  deleteReport: (reportId) => apiClient.delete(`/reports/${reportId}/delete`),

  // Analytics
  getUserAnalytics: (userId, days = 30) =>
    apiClient.get(`/analytics/user/${userId}/summary`, {
      params: { days },
    }),

  getTeamAnalytics: (days = 7) =>
    apiClient.get('/analytics/team/summary', {
      params: { days },
    }),

  getTrends: (metric = 'total_hours', days = 90) =>
    apiClient.get('/analytics/trends', {
      params: { metric, days },
    }),
};

export const bugTrackerAPI = {
  getCategories: () => apiClient.get('/bugtracker/categories'),

  getStatuses: () => apiClient.get('/bugtracker/statuses'),

  getReporters: () => apiClient.get('/bugtracker/reporters'),

  listBugs: (page = 1, perPage = 20, filters = {}) =>
    apiClient.get('/bugtracker', {
      params: { page, per_page: perPage, ...filters },
    }),

  getBug: (bugId) => apiClient.get(`/bugtracker/${bugId}`),

  downloadBug: (bugId) =>
    apiClient.get(`/bugtracker/${bugId}/download`, {
      responseType: 'blob',
    }),

  downloadAllBugs: (filters = {}) =>
    apiClient.get('/bugtracker/download-all', {
      params: filters,
      responseType: 'blob',
    }),

  updateBug: (bugId, data) => apiClient.patch(`/bugtracker/${bugId}`, data),

  editBug: (bugId, data) => apiClient.patch(`/bugtracker/${bugId}/edit`, data),

  getSprintBoard: () => apiClient.get('/bugtracker/sprints'),

  assignSprint: (bugId, sprint) => apiClient.patch(`/bugtracker/${bugId}/sprint`, { sprint }),

  assignRoadmap: (bugId, roadmap) => apiClient.patch(`/bugtracker/${bugId}/roadmap`, { roadmap }),

  submitBug: (data) => apiClient.post('/bugtracker/submit', data),

  getTeams: () => apiClient.get('/bugtracker/teams'),

  listTeamTasks: (page = 1, perPage = 20, filters = {}) =>
    apiClient.get('/bugtracker/team-tasks', {
      params: { page, per_page: perPage, ...filters },
    }),

  submitTeamTask: (data) => apiClient.post('/bugtracker/team-tasks/submit', data),

  backfillAttachments: (bugId) => apiClient.post(`/bugtracker/${bugId}/backfill-attachments`),

  backfillAllAttachments: () => apiClient.post('/bugtracker/backfill-attachments'),

  listUpdates: () => apiClient.get('/bugtracker/updates'),

  postUpdate: (data) => apiClient.post('/bugtracker/updates', data),

  deleteUpdate: (updateId) => apiClient.delete(`/bugtracker/updates/${updateId}`),
};

export default apiClient;