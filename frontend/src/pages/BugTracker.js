import React, { useEffect, useMemo, useState, useCallback } from 'react';
import {
  bugTrackerAPI, authAPI,
  getAttachmentViewUrl, getAttachmentDownloadUrl,
  getUpdateImageUrl, getUpdateGalleryImageUrl,
  getUpdateAttachmentViewUrl, getUpdateAttachmentDownloadUrl,
} from '../services/api';
import LoadingSpinner from '../components/LoadingSpinner';
import HelpOutlineRoundedIcon from '@mui/icons-material/HelpOutlineRounded';
import BugReportRoundedIcon from '@mui/icons-material/BugReportRounded';
import LightbulbRoundedIcon from '@mui/icons-material/LightbulbRounded';
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import EventRoundedIcon from '@mui/icons-material/EventRounded';
import NotesRoundedIcon from '@mui/icons-material/NotesRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import BlockRoundedIcon from '@mui/icons-material/BlockRounded';
import RepeatRoundedIcon from '@mui/icons-material/RepeatRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import CheckCircleOutlineRoundedIcon from '@mui/icons-material/CheckCircleOutlineRounded';
import CancelRoundedIcon from '@mui/icons-material/CancelRounded';
import DesktopWindowsRoundedIcon from '@mui/icons-material/DesktopWindowsRounded';
import AssignmentRoundedIcon from '@mui/icons-material/AssignmentRounded';
import ExtensionRoundedIcon from '@mui/icons-material/ExtensionRounded';
import GroupRoundedIcon from '@mui/icons-material/GroupRounded';
import ScheduleRoundedIcon from '@mui/icons-material/ScheduleRounded';
import PlaceRoundedIcon from '@mui/icons-material/PlaceRounded';
import BuildRoundedIcon from '@mui/icons-material/BuildRounded';
import LockRoundedIcon from '@mui/icons-material/LockRounded';
import AttachFileRoundedIcon from '@mui/icons-material/AttachFileRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import SyncRoundedIcon from '@mui/icons-material/SyncRounded';
import SkipPreviousRoundedIcon from '@mui/icons-material/SkipPreviousRounded';
import SkipNextRoundedIcon from '@mui/icons-material/SkipNextRounded';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import './BugTracker.css';

// Category icons, rendered with MUI's icon set so they match the rest of
// the app's iconography instead of relying on platform emoji rendering.
const CATEGORY_ICON_COMPONENTS = {
  general: HelpOutlineRoundedIcon,
  bug: BugReportRoundedIcon,
  feature: LightbulbRoundedIcon,
  observation: VisibilityRoundedIcon,
};

function CategoryIcon({ category, className, fontSize = 'small' }) {
  const Icon = CATEGORY_ICON_COMPONENTS[category] || HelpOutlineRoundedIcon;
  return <Icon className={className} fontSize={fontSize} />;
}

// A few of the backend-supplied follow-up questions share the same key
// across categories/status forms (e.g. "what", "why", "next_steps"), so a
// single lookup by key covers the whole question set with one icon each.
const QUESTION_ICON_BY_KEY = {
  what: SettingsRoundedIcon,
  why: HelpOutlineRoundedIcon,
  how: AutoAwesomeRoundedIcon,
  when: EventRoundedIcon,
  anything_else: NotesRoundedIcon,
  next_steps: ArrowForwardRoundedIcon,
  describe_blocker: BlockRoundedIcon,
  summary: HelpOutlineRoundedIcon,
  when_noticed: EventRoundedIcon,
  frequency: RepeatRoundedIcon,
  impact: WarningAmberRoundedIcon,
  expected_behavior: CheckCircleOutlineRoundedIcon,
  actual_behavior: CancelRoundedIcon,
  environment: DesktopWindowsRoundedIcon,
  error_logs: AssignmentRoundedIcon,
  feature_summary: LightbulbRoundedIcon,
  problem_solved: ExtensionRoundedIcon,
  who_benefits: GroupRoundedIcon,
  priority_reason: ScheduleRoundedIcon,
  what_observed: VisibilityRoundedIcon,
  where_observed: PlaceRoundedIcon,
  is_risk: WarningAmberRoundedIcon,
  suggested_action: ArrowForwardRoundedIcon,
  progress_notes: BuildRoundedIcon,
  eta: ScheduleRoundedIcon,
  resolution_details: CheckCircleOutlineRoundedIcon,
  reason: LockRoundedIcon,
};

function QuestionIcon({ fieldKey, className }) {
  const Icon = QUESTION_ICON_BY_KEY[fieldKey] || NotesRoundedIcon;
  return <Icon className={className || 'bugtracker-question-icon'} fontSize="small" />;
}

const CATEGORY_META = {
  bug: { title: 'Code Bug', blurb: 'Something is broken or behaving incorrectly.' },
  feature: { title: 'Feature Request', blurb: 'Suggest something new or an improvement.' },
  general: { title: 'General Issue', blurb: 'Anything that doesn\'t fit the categories above.' },
  observation: { title: 'Observation', blurb: 'Something worth flagging, not urgent.' },
};

const SEVERITIES = [
  { key: 'critical', label: 'Critical', color: '#c92a2a' },
  { key: 'high', label: 'High', color: '#e8590c' },
  { key: 'medium', label: 'Medium', color: '#f08c00' },
  { key: 'low', label: 'Low', color: '#2b8a3e' },
];
const SEVERITY_META = Object.fromEntries(SEVERITIES.map((s) => [s.key, s]));

// Odoo-style progress-through-workflow used for the sprint board's progress bar.
const STATUS_PROGRESS = { open: 0, in_progress: 50, resolved: 90, closed: 100 };

function hasRecoverableAttachments(bug) {
  const missingIn = (list) => (list || []).some((a) => !a.id);
  if (missingIn(bug.attachments)) return true;
  return (bug.status_updates || []).some((u) => missingIn(u.attachments));
}

function AttachmentChips({ attachments, emptyLabel = 'None', getViewUrl = getAttachmentViewUrl, getDownloadUrl = getAttachmentDownloadUrl }) {
  if (!attachments || attachments.length === 0) {
    return <span className="bugtracker-attachment-empty">{emptyLabel}</span>;
  }
  return (
    <span className="bugtracker-attachment-chips">
      {attachments.map((a, idx) => (
        a.id ? (
          <span key={a.id || idx} className="bugtracker-attachment-chip">
            <AttachFileRoundedIcon className="bugtracker-attachment-icon" fontSize="inherit" aria-hidden="true" />
            <a
              href={getViewUrl(a.id)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              title={`Open ${a.filename}`}
              className="bugtracker-attachment-filename"
            >
              {a.filename}
            </a>
            <a
              href={getDownloadUrl(a.id)}
              onClick={(e) => e.stopPropagation()}
              className="bugtracker-attachment-download"
              title={`Download ${a.filename}`}
            >
              <DownloadRoundedIcon fontSize="inherit" />
            </a>
          </span>
        ) : (
          <span key={idx} className="bugtracker-attachment-chip bugtracker-attachment-chip--nofile" title="Saved before file storage was added -- no content to open">
            <AttachFileRoundedIcon className="bugtracker-attachment-icon" fontSize="inherit" aria-hidden="true" />
            <span className="bugtracker-attachment-filename">{a.filename}</span>
          </span>
        )
      ))}
    </span>
  );
}

const STATUS_META = {
  open: { label: 'Open', color: '#1971c2' },
  in_progress: { label: 'In Progress', color: '#f08c00' },
  resolved: { label: 'Resolved', color: '#2b8a3e' },
  closed: { label: 'Closed', color: '#868e96' },
};

const MAX_FILE_SIZE = 8 * 1024 * 1024; // 8MB per file
const MAX_FILES = 5;

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result || '';
      const commaIdx = result.indexOf(',');
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatRelativeTime(iso) {
  try {
    const then = new Date(iso).getTime();
    const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (diffSec < 60) return 'just now';
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    if (diffDay < 7) return `${diffDay}d ago`;
    return new Date(iso).toLocaleDateString();
  } catch {
    return '';
  }
}

export default function BugTracker() {
  const user = authAPI.getUser();
  const [tab, setTab] = useState('submit'); // 'submit' | 'list' | 'sprints' | 'updates'
  // Reporter accounts (self-registered, no Odoo access) don't get the
  // Sprints tab or team-task assignment -- those are internal triage
  // tools, and the backend already rejects these calls for that role too.
  const isReporter = authAPI.isReporter();

  // ---- Status-change follow-up fields (fetched from backend, mirrors categories) ----
  const [statuses, setStatuses] = useState([]);
  useEffect(() => {
    bugTrackerAPI.getStatuses()
      .then((res) => setStatuses(res.data.data || []))
      .catch(() => setStatuses([]));
  }, []);
  const statusFieldsMap = useMemo(
    () => Object.fromEntries(statuses.map((s) => [s.key, s.fields || []])),
    [statuses]
  );

  // Pending status change for whichever bug row is currently being updated.
  // Shape: { bugId, status, fieldValues, files, fileError, submitting, submitError }
  const [pendingChange, setPendingChange] = useState(null);

  // ---- Submit flow state ----
  const [step, setStep] = useState(1); // 1: category, 2: details, 3: review
  const [categories, setCategories] = useState([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  const [category, setCategory] = useState(null);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [severity, setSeverity] = useState('medium');
  const [reporterName, setReporterName] = useState(user?.name || '');
  const [reporterEmail, setReporterEmail] = useState(user?.email || '');
  const [answers, setAnswers] = useState({});
  const [files, setFiles] = useState([]); // { file, name, size, type }
  const [fileError, setFileError] = useState(null);

  const [sendEmail, setSendEmail] = useState(false);
  const [emailRecipients, setEmailRecipients] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitted, setSubmitted] = useState(null);

  // ---- List state ----
  const [bugs, setBugs] = useState([]);
  const [bugsLoading, setBugsLoading] = useState(false);
  const [bugsError, setBugsError] = useState(null);
  const [filterCategory, setFilterCategory] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('');
  const [filterEngineer, setFilterEngineer] = useState('');
  const [filterRoadmap, setFilterRoadmap] = useState(false);
  const [reporters, setReporters] = useState([]);
  const [expandedId, setExpandedId] = useState(null);

  // 'all' | 'first5' | 'last5' -- a quick windowing control shown at the
  // bottom of the All Reports list, so a long list can be trimmed to just
  // the first or last 5 (of the current, already-filtered order) without
  // changing the filters themselves.
  const [listWindow, setListWindow] = useState('all');

  // Inline "edit my report" state for whichever row is being edited.
  // Shape: { bugId, title, description, severity, answers, files, fileError, submitting, submitError }
  const [editingChange, setEditingChange] = useState(null);

  const startEditing = (bug, e) => {
    if (e) e.stopPropagation();
    setExpandedId(bug.id);
    setPendingChange(null);
    setEditingChange({
      bugId: bug.id,
      title: bug.title || '',
      description: bug.description || '',
      severity: bug.severity || 'medium',
      answers: { ...(bug.answers || {}) },
      files: [],
      fileError: null,
      submitting: false,
      submitError: null,
    });
  };

  const cancelEditing = (e) => {
    if (e) e.stopPropagation();
    setEditingChange(null);
  };

  const handleEditFilesSelected = (e) => {
    const chosen = Array.from(e.target.files || []);
    setEditingChange((prev) => {
      if (!prev) return prev;
      if (prev.files.length + chosen.length > MAX_FILES) {
        e.target.value = '';
        return { ...prev, fileError: `You can attach up to ${MAX_FILES} files.` };
      }
      const tooBig = chosen.find((f) => f.size > MAX_FILE_SIZE);
      if (tooBig) {
        e.target.value = '';
        return { ...prev, fileError: `"${tooBig.name}" exceeds the 8MB limit.` };
      }
      e.target.value = '';
      return { ...prev, files: [...prev.files, ...chosen], fileError: null };
    });
  };

  const removeEditFile = (idx) => {
    setEditingChange((prev) => (prev ? { ...prev, files: prev.files.filter((_, i) => i !== idx) } : prev));
  };

  const submitEditing = async () => {
    if (!editingChange) return;
    if (!editingChange.title.trim()) {
      setEditingChange((prev) => ({ ...prev, submitError: 'Title cannot be empty.' }));
      return;
    }
    setEditingChange((prev) => ({ ...prev, submitting: true, submitError: null }));
    try {
      const encodedAttachments = await Promise.all(editingChange.files.map(async (file) => ({
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        content_b64: await fileToBase64(file),
      })));
      await bugTrackerAPI.editBug(editingChange.bugId, {
        title: editingChange.title.trim(),
        description: editingChange.description,
        severity: editingChange.severity,
        answers: editingChange.answers,
        attachments: encodedAttachments,
      });
      setEditingChange(null);
      fetchBugs();
    } catch (e) {
      setEditingChange((prev) => ({
        ...prev,
        submitting: false,
        submitError: e.response?.data?.message || 'Failed to save changes. Please try again.',
      }));
    }
  };

  // ---- Sprint board state ----
  const [sprintBoard, setSprintBoard] = useState(null); // { sprints: [...], backlog: [...] }
  const [sprintBoardLoading, setSprintBoardLoading] = useState(false);
  const [sprintBoardError, setSprintBoardError] = useState(null);
  const [sprintUpdatingId, setSprintUpdatingId] = useState(null);
  const [sprintMessage, setSprintMessage] = useState(null);
  const [sprintDetailBug, setSprintDetailBug] = useState(null);

  const fetchSprintBoard = useCallback(() => {
    setSprintBoardLoading(true);
    setSprintBoardError(null);
    bugTrackerAPI.getSprintBoard()
      .then((res) => setSprintBoard(res.data.data))
      .catch(() => setSprintBoardError('Failed to load the sprint board.'))
      .finally(() => setSprintBoardLoading(false));
  }, []);

  useEffect(() => {
    if (tab === 'sprints') fetchSprintBoard();
  }, [tab, fetchSprintBoard]);

  const handleAssignSprint = async (bugId, sprintValue) => {
    setSprintUpdatingId(bugId);
    setSprintMessage(null);
    try {
      const res = await bugTrackerAPI.assignSprint(bugId, sprintValue);
      setSprintMessage(res.data.message || null);
      fetchSprintBoard();
      if (tab === 'list') fetchBugs();
    } catch (e) {
      setSprintMessage(e.response?.data?.message || 'Failed to update sprint.');
    } finally {
      setSprintUpdatingId(null);
    }
  };

  const handleAssignRoadmap = async (bugId, roadmapValue, note) => {
    setSprintUpdatingId(bugId);
    setSprintMessage(null);
    try {
      const res = await bugTrackerAPI.assignRoadmap(bugId, roadmapValue, note);
      setSprintMessage(res.data.message || null);
      fetchSprintBoard();
      if (tab === 'list') fetchBugs();
    } catch (e) {
      setSprintMessage(e.response?.data?.message || 'Failed to update the roadmap.');
    } finally {
      setSprintUpdatingId(null);
    }
  };

  useEffect(() => {
    bugTrackerAPI.getCategories()
      .then((res) => setCategories(res.data.data || []))
      .catch(() => setCategories([]))
      .finally(() => setCategoriesLoading(false));
  }, []);

  // ---- Per-category report counts (total / in progress / resolved), shown on the category cards ----
  const [categoryStats, setCategoryStats] = useState({});

  useEffect(() => {
    const keys = (categories.length ? categories.map((c) => c.key) : Object.keys(CATEGORY_META));
    if (keys.length === 0) return;
    let cancelled = false;

    Promise.all(
      keys.map((key) =>
        Promise.all([
          bugTrackerAPI.listBugs(1, 1, { category: key }),
          bugTrackerAPI.listBugs(1, 1, { category: key, status: 'in_progress' }),
          bugTrackerAPI.listBugs(1, 1, { category: key, status: 'resolved' }),
        ])
          .then(([totalRes, inProgressRes, resolvedRes]) => [
            key,
            {
              total: totalRes.data.total ?? 0,
              inProgress: inProgressRes.data.total ?? 0,
              resolved: resolvedRes.data.total ?? 0,
            },
          ])
          .catch(() => [key, { total: 0, inProgress: 0, resolved: 0 }])
      )
    ).then((entries) => {
      if (!cancelled) setCategoryStats(Object.fromEntries(entries));
    });

    return () => {
      cancelled = true;
    };
  }, [categories]);

  // ---- Team updates ("+ Post Update") state ----
  const MAX_UPDATE_IMAGES = 10;
  const [updates, setUpdates] = useState([]);
  const [updatesLoading, setUpdatesLoading] = useState(false);
  const [updatesError, setUpdatesError] = useState(null);
  const [showPostModal, setShowPostModal] = useState(false);
  const [postDescription, setPostDescription] = useState('');
  const [postImageFiles, setPostImageFiles] = useState([]); // [{file, preview}]
  const [postAttachmentFiles, setPostAttachmentFiles] = useState([]);
  const [postFileError, setPostFileError] = useState(null);
  const [postError, setPostError] = useState(null);
  const [posting, setPosting] = useState(false);

  const fetchUpdates = useCallback(() => {
    setUpdatesLoading(true);
    setUpdatesError(null);
    bugTrackerAPI.listUpdates()
      .then((res) => setUpdates(res.data.data || []))
      .catch(() => setUpdatesError('Failed to load updates.'))
      .finally(() => setUpdatesLoading(false));
  }, []);

  useEffect(() => {
    if (tab === 'updates') fetchUpdates();
  }, [tab, fetchUpdates]);

  const resetPostModal = () => {
    setShowPostModal(false);
    setPostDescription('');
    postImageFiles.forEach((f) => URL.revokeObjectURL(f.preview));
    setPostImageFiles([]);
    setPostAttachmentFiles([]);
    setPostFileError(null);
    setPostError(null);
  };

  const handlePostImagesChange = (e) => {
    const chosen = Array.from(e.target.files || []);
    e.target.value = '';
    if (chosen.length === 0) return;
    setPostFileError(null);
    const notImage = chosen.find((f) => !f.type.startsWith('image/'));
    if (notImage) {
      setPostFileError(`"${notImage.name}" is not an image.`);
      return;
    }
    if (postImageFiles.length + chosen.length > MAX_UPDATE_IMAGES) {
      setPostFileError(`You can attach up to ${MAX_UPDATE_IMAGES} images.`);
      return;
    }
    const tooBig = chosen.find((f) => f.size > MAX_FILE_SIZE);
    if (tooBig) {
      setPostFileError(`"${tooBig.name}" exceeds the 8MB limit.`);
      return;
    }
    setPostImageFiles((prev) => [
      ...prev,
      ...chosen.map((file) => ({ file, preview: URL.createObjectURL(file) })),
    ]);
  };

  const removePostImage = (idx) => {
    setPostImageFiles((prev) => {
      const removed = prev[idx];
      if (removed) URL.revokeObjectURL(removed.preview);
      return prev.filter((_, i) => i !== idx);
    });
  };

  const handlePostAttachmentsChange = (e) => {
    const chosen = Array.from(e.target.files || []);
    e.target.value = '';
    if (chosen.length === 0) return;
    setPostFileError(null);
    if (postAttachmentFiles.length + chosen.length > MAX_FILES) {
      setPostFileError(`You can attach up to ${MAX_FILES} files.`);
      return;
    }
    const tooBig = chosen.find((f) => f.size > MAX_FILE_SIZE);
    if (tooBig) {
      setPostFileError(`"${tooBig.name}" exceeds the 8MB limit.`);
      return;
    }
    setPostAttachmentFiles((prev) => [...prev, ...chosen]);
  };

  const removePostAttachment = (idx) => {
    setPostAttachmentFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const fileToBase64 = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

  const handlePostUpdate = async () => {
    if (!postDescription.trim()) {
      setPostError('Please add a description.');
      return;
    }
    setPosting(true);
    setPostError(null);
    try {
      const [images, attachments] = await Promise.all([
        Promise.all(postImageFiles.map(async ({ file }) => ({
          filename: file.name,
          content_type: file.type,
          content_b64: await fileToBase64(file),
        }))),
        Promise.all(postAttachmentFiles.map(async (file) => ({
          filename: file.name,
          content_type: file.type || 'application/octet-stream',
          content_b64: await fileToBase64(file),
        }))),
      ]);
      await bugTrackerAPI.postUpdate({
        description: postDescription.trim(),
        images,
        attachments,
      });
      resetPostModal();
      setTab('updates');
      fetchUpdates();
    } catch (e) {
      setPostError(e.response?.data?.message || 'Failed to post update. Please try again.');
    } finally {
      setPosting(false);
    }
  };

  const handleDeleteUpdate = async (updateId) => {
    if (!window.confirm('Delete this update?')) return;
    try {
      await bugTrackerAPI.deleteUpdate(updateId);
      fetchUpdates();
    } catch (e) {
      setUpdatesError(e.response?.data?.message || 'Failed to delete update.');
    }
  };

  // ---- Team task assignment state ----
  const [teams, setTeams] = useState([]);
  const [selectedTeam, setSelectedTeam] = useState(null); // team object or null
  const [teamTaskDescription, setTeamTaskDescription] = useState('');
  const [teamTaskFiles, setTeamTaskFiles] = useState([]);
  const [teamTaskFileError, setTeamTaskFileError] = useState(null);
  const [teamTaskSendEmail, setTeamTaskSendEmail] = useState(false);
  const [teamTaskEmailRecipients, setTeamTaskEmailRecipients] = useState('');
  const [teamTaskSubmitting, setTeamTaskSubmitting] = useState(false);
  const [teamTaskSubmitError, setTeamTaskSubmitError] = useState(null);
  const [teamTaskSubmitted, setTeamTaskSubmitted] = useState(null);
  const [recentTeamTasks, setRecentTeamTasks] = useState([]);

  useEffect(() => {
    bugTrackerAPI.getTeams()
      .then((res) => setTeams(res.data.data || []))
      .catch(() => setTeams([]));
  }, []);

  const fetchRecentTeamTasks = useCallback((teamKey) => {
    bugTrackerAPI.listTeamTasks(1, 10, teamKey ? { team_key: teamKey } : {})
      .then((res) => setRecentTeamTasks(res.data.data || []))
      .catch(() => setRecentTeamTasks([]));
  }, []);

  const handleSelectTeam = (team) => {
    setSelectedTeam(team);
    setTeamTaskDescription('');
    setTeamTaskFiles([]);
    setTeamTaskFileError(null);
    setTeamTaskSendEmail(false);
    setTeamTaskEmailRecipients((team.members || []).map((m) => m.email).join(', '));
    setTeamTaskSubmitError(null);
    setTeamTaskSubmitted(null);
    fetchRecentTeamTasks(team.key);
  };

  const handleTeamTaskSendEmailToggle = (checked) => {
    setTeamTaskSendEmail(checked);
    if (checked && !teamTaskEmailRecipients.trim() && selectedTeam) {
      setTeamTaskEmailRecipients((selectedTeam.members || []).map((m) => m.email).join(', '));
    }
  };

  const handleTeamTaskFilesSelected = (e) => {
    const chosen = Array.from(e.target.files || []);
    setTeamTaskFileError(null);
    if (teamTaskFiles.length + chosen.length > MAX_FILES) {
      setTeamTaskFileError(`You can attach up to ${MAX_FILES} files.`);
      e.target.value = '';
      return;
    }
    const tooBig = chosen.find((f) => f.size > MAX_FILE_SIZE);
    if (tooBig) {
      setTeamTaskFileError(`"${tooBig.name}" exceeds the 8MB limit.`);
      e.target.value = '';
      return;
    }
    setTeamTaskFiles((prev) => [...prev, ...chosen]);
    e.target.value = '';
  };

  const removeTeamTaskFile = (idx) => {
    setTeamTaskFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const closeTeamTaskForm = () => {
    setSelectedTeam(null);
    setTeamTaskSubmitted(null);
    setTeamTaskSubmitError(null);
  };

  const handleTeamTaskSubmit = async () => {
    if (!selectedTeam) return;
    if (!teamTaskDescription.trim()) {
      setTeamTaskSubmitError('Please write a description of the task.');
      return;
    }
    setTeamTaskSubmitting(true);
    setTeamTaskSubmitError(null);
    try {
      const encodedAttachments = await Promise.all(teamTaskFiles.map(async (file) => ({
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        content_b64: await fileToBase64(file),
      })));

      const payload = {
        team_key: selectedTeam.key,
        description: teamTaskDescription.trim(),
        attachments: encodedAttachments,
        send_email: teamTaskSendEmail,
        email_recipients: teamTaskEmailRecipients,
        assigned_by_name: reporterName,
        assigned_by_email: reporterEmail,
      };

      const res = await bugTrackerAPI.submitTeamTask(payload);
      setTeamTaskSubmitted(res.data.data);
      fetchRecentTeamTasks(selectedTeam.key);
    } catch (e) {
      setTeamTaskSubmitError(e.response?.data?.message || 'Failed to assign task. Please try again.');
    } finally {
      setTeamTaskSubmitting(false);
    }
  };

  const activeCategory = useMemo(
    () => categories.find((c) => c.key === category) || null,
    [categories, category]
  );

  const fetchBugs = useCallback(() => {
    setBugsLoading(true);
    setBugsError(null);
    const filters = {};
    if (filterCategory) filters.category = filterCategory;
    if (filterStatus) filters.status = filterStatus;
    if (filterSeverity) filters.severity = filterSeverity;
    if (filterEngineer) filters.reporter = filterEngineer;
    if (filterRoadmap) filters.roadmap = 'true';
    bugTrackerAPI.listBugs(1, 50, filters)
      .then((res) => setBugs(res.data.data || []))
      .catch(() => setBugsError('Failed to load bug reports.'))
      .finally(() => setBugsLoading(false));
  }, [filterCategory, filterStatus, filterSeverity, filterEngineer, filterRoadmap]);

  useEffect(() => {
    if (tab === 'list') fetchBugs();
  }, [tab, fetchBugs]);

  useEffect(() => {
    if (tab === 'list' && reporters.length === 0) {
      bugTrackerAPI.getReporters()
        .then((res) => setReporters(res.data.data || []))
        .catch(() => setReporters([]));
    }
  }, [tab, reporters.length]);

  // Reset the first-5/last-5 window whenever the underlying list changes,
  // so switching filters doesn't leave a stale trimmed view behind.
  useEffect(() => {
    setListWindow('all');
  }, [filterCategory, filterStatus, filterSeverity, filterEngineer, filterRoadmap]);

  const visibleBugs = useMemo(() => {
    if (listWindow === 'first5') return bugs.slice(0, 5);
    if (listWindow === 'last5') return bugs.slice(-5);
    return bugs;
  }, [bugs, listWindow]);

  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadingAll, setDownloadingAll] = useState(false);

  const handleDownloadBug = async (bug) => {
    try {
      setDownloadingId(bug.id);
      const response = await bugTrackerAPI.downloadBug(bug.id);
      const url = window.URL.createObjectURL(new Blob([response.data], { type: 'text/html' }));
      const link = document.createElement('a');
      link.href = url;
      const safeTitle = (bug.title || 'report').replace(/[^a-z0-9]+/gi, '_').toLowerCase();
      link.setAttribute('download', `${safeTitle}_${bug.id.slice(0, 8)}.html`);
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Error downloading report:', e);
      alert('Failed to download report. Please try again.');
    } finally {
      setDownloadingId(null);
    }
  };

  const [recoveringId, setRecoveringId] = useState(null);
  const [recoveringAll, setRecoveringAll] = useState(false);

  const handleRecoverAttachments = async (bug) => {
    try {
      setRecoveringId(bug.id);
      const res = await bugTrackerAPI.backfillAttachments(bug.id);
      const updated = res.data.data;
      setBugs((prev) => prev.map((b) => (b.id === bug.id ? updated : b)));
      const recovered = res.data.recovered || 0;
      if (recovered === 0) {
        alert('No matching attachments were found on the linked Odoo task for this report.');
      }
    } catch (e) {
      console.error('Error recovering attachments from Odoo:', e);
      alert('Failed to fetch attachments from Odoo. Please try again.');
    } finally {
      setRecoveringId(null);
    }
  };

  const handleRecoverAllAttachments = async () => {
    try {
      setRecoveringAll(true);
      const res = await bugTrackerAPI.backfillAllAttachments();
      const { recovered = 0, reports_updated: reportsUpdated = 0 } = res.data;
      alert(
        recovered > 0
          ? `Recovered ${recovered} attachment(s) from Odoo across ${reportsUpdated} report(s).`
          : 'No missing attachments could be matched on their linked Odoo tasks.'
      );
      fetchBugs();
    } catch (e) {
      console.error('Error running bulk Odoo attachment recovery:', e);
      alert('Failed to fetch attachments from Odoo. Please try again.');
    } finally {
      setRecoveringAll(false);
    }
  };

  const handleDownloadAll = async () => {
    try {
      setDownloadingAll(true);
      const filters = {};
      if (filterCategory) filters.category = filterCategory;
      if (filterStatus) filters.status = filterStatus;
      if (filterSeverity) filters.severity = filterSeverity;
      if (filterEngineer) filters.reporter = filterEngineer;
      if (filterRoadmap) filters.roadmap = 'true';
      const response = await bugTrackerAPI.downloadAllBugs(filters);
      const url = window.URL.createObjectURL(new Blob([response.data], { type: 'text/html' }));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `all_bug_reports_${Date.now()}.html`);
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Error downloading all reports:', e);
      alert('Failed to download all reports. Please try again.');
    } finally {
      setDownloadingAll(false);
    }
  };

  const handleSelectCategory = (key) => {
    setCategory(key);
    setAnswers({});
    setStep(2);
  };

  const handleAnswerChange = (key, value) => {
    setAnswers((prev) => ({ ...prev, [key]: value }));
  };

  const handleFilesSelected = (e) => {
    const chosen = Array.from(e.target.files || []);
    setFileError(null);
    if (files.length + chosen.length > MAX_FILES) {
      setFileError(`You can attach up to ${MAX_FILES} files.`);
      e.target.value = '';
      return;
    }
    const tooBig = chosen.find((f) => f.size > MAX_FILE_SIZE);
    if (tooBig) {
      setFileError(`"${tooBig.name}" exceeds the 8MB limit.`);
      e.target.value = '';
      return;
    }
    setFiles((prev) => [...prev, ...chosen]);
    e.target.value = '';
  };

  const removeFile = (idx) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const canProceedToReview = title.trim().length > 0;

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const encodedAttachments = await Promise.all(files.map(async (file) => ({
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        content_b64: await fileToBase64(file),
      })));

      const payload = {
        category,
        title: title.trim(),
        description,
        severity,
        reporter_name: reporterName,
        reporter_email: reporterEmail,
        answers,
        attachments: encodedAttachments,
        send_email: sendEmail,
        email_recipients: emailRecipients,
      };

      const res = await bugTrackerAPI.submitBug(payload);
      setSubmitted(res.data.data);
      setStep(4);
    } catch (e) {
      setSubmitError(e.response?.data?.message || 'Failed to submit. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const resetForm = () => {
    setStep(1);
    setCategory(null);
    setTitle('');
    setDescription('');
    setSeverity('medium');
    setAnswers({});
    setFiles([]);
    setFileError(null);
    setSendEmail(false);
    setEmailRecipients('');
    setSubmitError(null);
    setSubmitted(null);
  };

  const handleStatusSelect = (bug, newStatus) => {
    if (newStatus === bug.status) {
      setPendingChange(null);
      return;
    }
    setPendingChange({
      bugId: bug.id,
      status: newStatus,
      fieldValues: {},
      files: [],
      fileError: null,
      submitting: false,
      submitError: null,
    });
  };

  const cancelPendingChange = () => setPendingChange(null);

  const handlePendingFieldChange = (key, value) => {
    setPendingChange((prev) => (prev ? { ...prev, fieldValues: { ...prev.fieldValues, [key]: value } } : prev));
  };

  const handlePendingFilesSelected = (e) => {
    const chosen = Array.from(e.target.files || []);
    setPendingChange((prev) => {
      if (!prev) return prev;
      if (prev.files.length + chosen.length > MAX_FILES) {
        e.target.value = '';
        return { ...prev, fileError: `You can attach up to ${MAX_FILES} files.` };
      }
      const tooBig = chosen.find((f) => f.size > MAX_FILE_SIZE);
      if (tooBig) {
        e.target.value = '';
        return { ...prev, fileError: `"${tooBig.name}" exceeds the 8MB limit.` };
      }
      e.target.value = '';
      return { ...prev, files: [...prev.files, ...chosen], fileError: null };
    });
  };

  const removePendingFile = (idx) => {
    setPendingChange((prev) => (prev ? { ...prev, files: prev.files.filter((_, i) => i !== idx) } : prev));
  };

  const submitPendingChange = async () => {
    if (!pendingChange) return;
    const fieldDefs = statusFieldsMap[pendingChange.status] || [];
    const missing = fieldDefs.filter((f) => f.required && !(pendingChange.fieldValues[f.key] || '').trim());
    if (missing.length) {
      setPendingChange((prev) => ({
        ...prev,
        submitError: `Missing required field(s): ${missing.map((f) => f.label).join(', ')}`,
      }));
      return;
    }
    setPendingChange((prev) => ({ ...prev, submitting: true, submitError: null }));
    try {
      const encodedAttachments = await Promise.all(pendingChange.files.map(async (file) => ({
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        content_b64: await fileToBase64(file),
      })));
      await bugTrackerAPI.updateBug(pendingChange.bugId, {
        status: pendingChange.status,
        fields: pendingChange.fieldValues,
        attachments: encodedAttachments,
      });
      setPendingChange(null);
      fetchBugs();
    } catch (e) {
      setPendingChange((prev) => ({
        ...prev,
        submitting: false,
        submitError: e.response?.data?.message || 'Failed to update status. Please try again.',
      }));
    }
  };

  return (
    <div className={`bugtracker-container ${tab === 'list' ? 'bugtracker-container--wide' : ''} ${tab === 'submit' ? 'bugtracker-container--submit-wide' : ''} ${tab === 'sprints' ? 'bugtracker-container--sprints' : ''} ${tab === 'updates' ? 'bugtracker-container--wide' : ''}`}>
      <div className="bugtracker-header">
        <h1 className="bugtracker-title">Bug Tracker &mdash; OSDBcortex</h1>
        <p className="bugtracker-subtitle">Report issues, bugs, feature requests, or observations for the OSDBcortex project.</p>
      </div>

      <div className="bugtracker-tabs">
        <button
          className={`bugtracker-tab ${tab === 'submit' ? 'active' : ''}`}
          onClick={() => setTab('submit')}
        >
          Submit New
        </button>
        <button
          className={`bugtracker-tab ${tab === 'list' ? 'active' : ''}`}
          onClick={() => setTab('list')}
        >
          All Reports
        </button>
        {!isReporter && (
          <button
            className={`bugtracker-tab ${tab === 'sprints' ? 'active' : ''}`}
            onClick={() => setTab('sprints')}
          >
            Sprints
          </button>
        )}
        <button
          className={`bugtracker-tab ${tab === 'updates' ? 'active' : ''}`}
          onClick={() => setTab('updates')}
        >
          Updates
        </button>

        {!isReporter && (
          <button className="bugtracker-post-update-btn" onClick={() => setShowPostModal(true)}>
            <AddRoundedIcon fontSize="small" /> Post Update
          </button>
        )}
      </div>

      {tab === 'submit' && (
        <div className="bugtracker-card">
          {step > 1 && step < 4 && (
            <div className="bugtracker-progress">
              {[1, 2, 3].map((n) => (
                <div key={n} className={`bugtracker-progress-dot ${step >= n ? 'active' : ''}`}>{n}</div>
              ))}
            </div>
          )}

          {step === 1 && !selectedTeam && (
            <div className="bugtracker-category-section">
              <div className="bugtracker-category-section-wrapper">
                <div className="bugtracker-category-image-side">
                  <img
                    src="/assets/cortex-byte.jpeg"
                    alt="Cortex Byte - Database Intelligence"
                    className="bugtracker-category-image"
                  />
                </div>
                <div className="bugtracker-category-content-side">
                  <h2 className="bugtracker-step-title">What would you like to report?</h2>
                  {categoriesLoading ? (
                    <LoadingSpinner />
                  ) : (
                    <div className="bugtracker-category-grid">
                    {(categories.length ? categories : Object.keys(CATEGORY_META).map((key) => ({ key }))).map((c) => {
                      const meta = CATEGORY_META[c.key] || {};
                      const stats = categoryStats[c.key];
                      return (
                        <button
                          key={c.key}
                          className="bugtracker-category-card"
                          onClick={() => handleSelectCategory(c.key)}
                        >
                          <span className="bugtracker-category-icon"><CategoryIcon category={c.key} fontSize="medium" /></span>
                          <span className="bugtracker-category-text">
                            <span className="bugtracker-category-name">{c.label || meta.title}</span>
                            <span className="bugtracker-category-blurb">{meta.blurb}</span>
                          </span>
                          <span className="bugtracker-category-stats">
                            <span className="bugtracker-category-stat">
                              <span className="bugtracker-category-stat-value">{stats ? stats.total : '–'}</span>
                              <span className="bugtracker-category-stat-label">Total</span>
                            </span>
                            <span className="bugtracker-category-stat">
                              <span className="bugtracker-category-stat-value">{stats ? stats.inProgress : '–'}</span>
                              <span className="bugtracker-category-stat-label">In Progress</span>
                            </span>
                            <span className="bugtracker-category-stat">
                              <span className="bugtracker-category-stat-value">{stats ? stats.resolved : '–'}</span>
                              <span className="bugtracker-category-stat-label">Resolved</span>
                            </span>
                          </span>
                        </button>
                      );
                    })}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {step === 1 && selectedTeam && (
            <div>
              <div className="bugtracker-step-header">
                <button className="bugtracker-back-link" onClick={closeTeamTaskForm}>
                  <ArrowBackRoundedIcon fontSize="inherit" /> Back to categories &amp; teams
                </button>
                <h2 className="bugtracker-step-title">Assign a Task to {selectedTeam.label}</h2>
              </div>
              <p className="bugtracker-hint">
                Members: {(selectedTeam.members || []).map((m) => m.name).join(', ')}
              </p>

              {!teamTaskSubmitted && (
                <div className="bugtracker-team-form">
                  <label className="bugtracker-label">Task description *</label>
                  <textarea
                    className="bugtracker-textarea"
                    rows={4}
                    placeholder="Describe the task for this team..."
                    value={teamTaskDescription}
                    onChange={(e) => setTeamTaskDescription(e.target.value)}
                  />

                  <h3 className="bugtracker-section-title">Attachments</h3>
                  <p className="bugtracker-hint">Photos or files for this task (up to {MAX_FILES}, 8MB each).</p>
                  <input
                    type="file"
                    multiple
                    onChange={handleTeamTaskFilesSelected}
                    className="bugtracker-file-input"
                    accept="image/*,.md,.txt,.log,.pdf,.json,.csv"
                  />
                  {teamTaskFileError && <div className="bugtracker-error">{teamTaskFileError}</div>}
                  {teamTaskFiles.length > 0 && (
                    <ul className="bugtracker-file-list">
                      {teamTaskFiles.map((f, idx) => (
                        <li key={idx} className="bugtracker-file-item">
                          <span>{f.name}</span>
                          <span className="bugtracker-file-size">{formatBytes(f.size)}</span>
                          <button className="bugtracker-file-remove" onClick={() => removeTeamTaskFile(idx)}><CloseRoundedIcon fontSize="inherit" /></button>
                        </li>
                      ))}
                    </ul>
                  )}

                  <div className="bugtracker-email-toggle">
                    <label className="bugtracker-checkbox-label">
                      <input
                        type="checkbox"
                        checked={teamTaskSendEmail}
                        onChange={(e) => handleTeamTaskSendEmailToggle(e.target.checked)}
                      />
                      Send an email to {selectedTeam.label} about this task
                    </label>
                    {teamTaskSendEmail && (
                      <input
                        className="bugtracker-input"
                        type="text"
                        placeholder="Recipient email(s), comma-separated"
                        value={teamTaskEmailRecipients}
                        onChange={(e) => setTeamTaskEmailRecipients(e.target.value)}
                      />
                    )}
                  </div>

                  {teamTaskSubmitError && <div className="bugtracker-error">{teamTaskSubmitError}</div>}

                  <div className="bugtracker-actions">
                    <button className="bugtracker-btn-primary" disabled={teamTaskSubmitting} onClick={handleTeamTaskSubmit}>
                      {teamTaskSubmitting ? 'Assigning...' : 'Assign Task'}
                    </button>
                  </div>
                </div>
              )}

              {teamTaskSubmitted && (
                <div className="bugtracker-success">
                  <div className="bugtracker-success-icon"><CheckCircleRoundedIcon fontSize="inherit" /></div>
                  <h3 className="bugtracker-step-title">Task assigned to {selectedTeam.label}</h3>
                  {teamTaskSubmitted.email_sent && (
                    <p className="bugtracker-hint">Email sent to {teamTaskSubmitted.email_recipients}.</p>
                  )}
                  {teamTaskSubmitted.send_email && !teamTaskSubmitted.email_sent && (
                    <p className="bugtracker-error">Task saved, but the email failed to send{teamTaskSubmitted.email_error ? `: ${teamTaskSubmitted.email_error}` : '.'}</p>
                  )}
                  <div className="bugtracker-actions">
                    <button className="bugtracker-btn-primary" onClick={() => handleSelectTeam(selectedTeam)}>Assign Another</button>
                    <button className="bugtracker-btn-secondary" onClick={closeTeamTaskForm}>Done</button>
                  </div>
                </div>
              )}

              {recentTeamTasks.length > 0 && (
                <div className="bugtracker-team-recent">
                  <h3 className="bugtracker-section-title">Recent tasks for {selectedTeam.label}</h3>
                  <ul className="bugtracker-list">
                    {recentTeamTasks.map((t) => (
                      <li key={t.id} className="bugtracker-list-item">
                        <div className="bugtracker-list-detail" style={{ display: 'block' }}>
                          <p>{t.description}</p>
                          {(t.attachments || []).length > 0 && (
                            <div className="bugtracker-review-row">
                              <strong>Attachments:</strong> {t.attachments.map((a) => a.filename).join(', ')}
                            </div>
                          )}
                          <div className="bugtracker-review-row"><strong>Assigned by:</strong> {t.assigned_by_name || 'Unknown'}</div>
                          <span className="bugtracker-list-date">{formatDate(t.created_at)}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {step === 2 && activeCategory && (
            <div>
              <div className="bugtracker-step-header">
                <button className="bugtracker-back-link" onClick={() => setStep(1)}>
                  <ArrowBackRoundedIcon fontSize="inherit" /> Change category
                </button>
                <h2 className="bugtracker-step-title bugtracker-step-title--with-icon">
                  <CategoryIcon category={category} fontSize="medium" /> {activeCategory.label}
                </h2>
              </div>

              <label className="bugtracker-label">Title *</label>
              <input
                className="bugtracker-input"
                type="text"
                placeholder="Short, descriptive title..."
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />

              <label className="bugtracker-label">Description</label>
              <textarea
                className="bugtracker-textarea"
                rows={3}
                placeholder="Give an overview in your own words..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />

              <label className="bugtracker-label">Severity / Priority</label>
              <div className="bugtracker-severity-row">
                {SEVERITIES.map((s) => (
                  <button
                    key={s.key}
                    className={`bugtracker-severity-pill ${severity === s.key ? 'active' : ''}`}
                    style={severity === s.key ? { background: s.color, borderColor: s.color } : { borderColor: s.color, color: s.color }}
                    onClick={() => setSeverity(s.key)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>

              <h3 className="bugtracker-section-title">A few more details</h3>
              {activeCategory.questions.map((q) => (
                <div key={q.key} className="bugtracker-question">
                  <label className="bugtracker-label"><QuestionIcon fieldKey={q.key} /> {q.label}</label>
                  <textarea
                    className="bugtracker-textarea"
                    rows={2}
                    placeholder={q.placeholder}
                    value={answers[q.key] || ''}
                    onChange={(e) => handleAnswerChange(q.key, e.target.value)}
                  />
                </div>
              ))}

              <h3 className="bugtracker-section-title">Attachments</h3>
              <p className="bugtracker-hint">Upload screenshots, .md notes, logs, or any other supporting files (up to {MAX_FILES}, 8MB each). </p>
              <input
                type="file"
                multiple
                onChange={handleFilesSelected}
                className="bugtracker-file-input"
                accept="image/*,.md,.txt,.log,.pdf,.json,.csv"
              />
              {fileError && <div className="bugtracker-error">{fileError}</div>}
              {files.length > 0 && (
                <ul className="bugtracker-file-list">
                  {files.map((f, idx) => (
                    <li key={idx} className="bugtracker-file-item">
                      <span>{f.name}</span>
                      <span className="bugtracker-file-size">{formatBytes(f.size)}</span>
                      <button className="bugtracker-file-remove" onClick={() => removeFile(idx)}><CloseRoundedIcon fontSize="inherit" /></button>
                    </li>
                  ))}
                </ul>
              )}

              <h3 className="bugtracker-section-title">Reporter</h3>
              <div className="bugtracker-two-col">
                <div>
                  <label className="bugtracker-label">Name</label>
                  <input className="bugtracker-input" type="text" value={reporterName} onChange={(e) => setReporterName(e.target.value)} disabled={isReporter} />
                </div>
                <div>
                  <label className="bugtracker-label">Email</label>
                  <input className="bugtracker-input" type="email" value={reporterEmail} onChange={(e) => setReporterEmail(e.target.value)} disabled={isReporter} />
                </div>
              </div>
              {isReporter && (
                <p className="bugtracker-hint">Reports are always tied to your account.</p>
              )}

              <div className="bugtracker-email-toggle">
                <label className="bugtracker-checkbox-label">
                  <input
                    type="checkbox"
                    checked={sendEmail}
                    onChange={(e) => setSendEmail(e.target.checked)}
                  />
                  Also send this as an email
                </label>
                {sendEmail && (
                  <input
                    className="bugtracker-input"
                    type="text"
                    placeholder="Recipient email(s), comma-separated"
                    value={emailRecipients}
                    onChange={(e) => setEmailRecipients(e.target.value)}
                  />
                )}
              </div>

              <div className="bugtracker-actions">
                <button
                  className="bugtracker-btn-primary"
                  disabled={!canProceedToReview}
                  onClick={() => setStep(3)}
                >
                  Review &amp; Submit
                </button>
              </div>
            </div>
          )}

          {step === 3 && activeCategory && !submitting && (
            <div>
              <div className="bugtracker-step-header">
                <button className="bugtracker-back-link" onClick={() => setStep(2)}>
                  <ArrowBackRoundedIcon fontSize="inherit" /> Back to edit
                </button>
                <h2 className="bugtracker-step-title">Review</h2>
              </div>

              <div className="bugtracker-review-block">
                <div className="bugtracker-review-row"><strong>Category:</strong> {activeCategory.label}</div>
                <div className="bugtracker-review-row"><strong>Title:</strong> {title}</div>
                <div className="bugtracker-review-row"><strong>Severity:</strong> {severity}</div>
                {description && <div className="bugtracker-review-row"><strong>Description:</strong> {description}</div>}
                {activeCategory.questions.filter((q) => answers[q.key]).map((q) => (
                  <div key={q.key} className="bugtracker-review-row"><strong>{q.label}:</strong> {answers[q.key]}</div>
                ))}
                {files.length > 0 && (
                  <div className="bugtracker-review-row">
                    <strong>Attachments:</strong> {files.map((f) => f.name).join(', ')}
                  </div>
                )}
                <div className="bugtracker-review-row"><strong>Reporter:</strong> {reporterName} ({reporterEmail})</div>
                {sendEmail && (
                  <div className="bugtracker-review-row"><strong>Email to:</strong> {emailRecipients || '(none entered)'}</div>
                )}
              </div>

              {submitError && <div className="bugtracker-error">{submitError}</div>}

              <div className="bugtracker-actions">
                <button className="bugtracker-btn-primary" disabled={submitting} onClick={handleSubmit}>
                  Submit Report
                </button>
              </div>
            </div>
          )}

          {step === 3 && submitting && (
            <div className="bugtracker-submitting">
              <div className="bugtracker-submitting-rings">
                <span className="bugtracker-submitting-ring" />
                <span className="bugtracker-submitting-ring" />
                <span className="bugtracker-submitting-ring" />
                <CheckCircleRoundedIcon className="bugtracker-submitting-check" fontSize="large" />
              </div>
              <h2 className="bugtracker-step-title">Submitting your report...</h2>
              <p className="bugtracker-hint">Hang tight, this only takes a moment.</p>
            </div>
          )}

          {step === 4 && submitted && (
            <div className="bugtracker-success bugtracker-success--animated">
              <div className="bugtracker-success-icon"><CheckCircleRoundedIcon fontSize="inherit" /></div>
              <h2 className="bugtracker-step-title">Report submitted</h2>
              <p>Your {CATEGORY_META[submitted.category]?.title?.toLowerCase() || 'report'} has been recorded.</p>
              {submitted.email_sent && <p className="bugtracker-hint">Email notification sent to {submitted.email_recipients}.</p>}
              <div className="bugtracker-actions">
                <button className="bugtracker-btn-primary" onClick={resetForm}>Submit Another</button>
                <button className="bugtracker-btn-secondary" onClick={() => { setTab('list'); resetForm(); }}>View All Reports</button>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'list' && (
        <div className="bugtracker-card bugtracker-card--wide">
          {sprintMessage && <div className="bugtracker-hint bugtracker-sprint-message">{sprintMessage}</div>}
          <div className="bugtracker-filters">
            <select className="bugtracker-select" value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
              <option value="">All Categories</option>
              {Object.entries(CATEGORY_META).map(([key, meta]) => (
                <option key={key} value={key}>{meta.title}</option>
              ))}
            </select>
            <select className="bugtracker-select" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">All Statuses</option>
              {Object.entries(STATUS_META).map(([key, meta]) => (
                <option key={key} value={key}>{meta.label}</option>
              ))}
            </select>
            <select className="bugtracker-select" value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)}>
              <option value="">All Priorities</option>
              {SEVERITIES.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
            {!isReporter && (
              <select className="bugtracker-select" value={filterEngineer} onChange={(e) => setFilterEngineer(e.target.value)}>
                <option value="">All Engineers</option>
                {reporters.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            )}

            {!isReporter && (
              <button
                className="bugtracker-btn-download-all"
                onClick={handleDownloadAll}
                disabled={downloadingAll || bugs.length === 0}
                title="Download every report in this list as one file"
              >
                {downloadingAll ? 'Downloading...' : (<><DownloadRoundedIcon fontSize="inherit" /> Download All</>)}
              </button>
            )}
          </div>

          {bugsLoading ? (
            <LoadingSpinner />
          ) : bugsError ? (
            <div className="bugtracker-error">{bugsError}</div>
          ) : bugs.length === 0 ? (
            <div className="bugtracker-empty">No bug reports found.</div>
          ) : (
            <ul className="bugtracker-list">
              {visibleBugs.map((b) => (
                <li key={b.id} className="bugtracker-list-item">
                  <div className="bugtracker-list-row" onClick={() => setExpandedId(expandedId === b.id ? null : b.id)}>
                    <span className="bugtracker-list-category" title={CATEGORY_META[b.category]?.title || b.category}>
                      <span className="bugtracker-list-icon"><CategoryIcon category={b.category} /></span>
                      <span className="bugtracker-list-category-label">{CATEGORY_META[b.category]?.title || b.category}</span>
                    </span>
                    <span className="bugtracker-list-title">{b.title}</span>
                    {b.roadmap && (
                      <span
                        className="bugtracker-roadmap-chip"
                        title={b.roadmap_note ? `On the Future Roadmap: ${b.roadmap_note}` : 'On the Future Roadmap'}
                      >
                        <PlaceRoundedIcon fontSize="inherit" />
                      </span>
                    )}
                    <span className="bugtracker-badge" style={{ background: STATUS_META[b.status]?.color || '#868e96' }}>
                      {STATUS_META[b.status]?.label || b.status}
                    </span>
                  </div>

                  {/* Always-visible summary line -- no click required to see
                      who reported it, when, priority, or attachments. */}
                  <div className="bugtracker-list-meta">
                    <span className="bugtracker-meta-item">
                      <strong>Reported by:</strong> {b.reporter_name || 'Unknown'}
                    </span>
                    <span className="bugtracker-meta-item">
                      <strong>Date:</strong> {formatDate(b.created_at)}
                    </span>
                    <span
                      className="bugtracker-priority-badge"
                      style={{
                        background: SEVERITY_META[b.severity]?.color ? `${SEVERITY_META[b.severity].color}1a` : '#f1f3f5',
                        color: SEVERITY_META[b.severity]?.color || '#495057',
                        borderColor: SEVERITY_META[b.severity]?.color || '#ced4da',
                      }}
                    >
                      Priority: {SEVERITY_META[b.severity]?.label || b.severity || 'Medium'}
                    </span>
                    <span className="bugtracker-meta-item bugtracker-meta-attachments">
                      <strong>Attachments:</strong>{' '}
                      <AttachmentChips attachments={b.attachments} />
                    </span>
                    <span className="bugtracker-meta-actions">
                      {hasRecoverableAttachments(b) && (
                        <button
                          className="bugtracker-btn-edit"
                          onClick={(e) => { e.stopPropagation(); handleRecoverAttachments(b); }}
                          disabled={recoveringId === b.id}
                          title="Fetch this report's original attachment(s) from its linked Odoo task"
                        >
                          {recoveringId === b.id ? 'Fetching...' : (<><SyncRoundedIcon fontSize="inherit" /> Fetch from Odoo</>)}
                        </button>
                      )}
                      {!isReporter && (
                        <button
                          className="bugtracker-btn-edit"
                          onClick={(e) => startEditing(b, e)}
                          title="Edit this report"
                        >
                          <EditRoundedIcon fontSize="inherit" /> Edit
                        </button>
                      )}
                      <button
                        className="bugtracker-btn-download"
                        onClick={(e) => { e.stopPropagation(); handleDownloadBug(b); }}
                        disabled={downloadingId === b.id}
                        title="Download this report"
                      >
                        {downloadingId === b.id ? 'Downloading...' : (<><DownloadRoundedIcon fontSize="inherit" /> Download</>)}
                      </button>
                    </span>
                  </div>

                  {editingChange?.bugId === b.id && (
                    <div className="bugtracker-list-detail" onClick={(e) => e.stopPropagation()}>
                      <h3 className="bugtracker-section-title">Edit report</h3>

                      <label className="bugtracker-label">Title</label>
                      <input
                        className="bugtracker-input"
                        type="text"
                        value={editingChange.title}
                        onChange={(e) => setEditingChange((prev) => ({ ...prev, title: e.target.value }))}
                      />

                      <label className="bugtracker-label">Description</label>
                      <textarea
                        className="bugtracker-textarea"
                        rows={4}
                        value={editingChange.description}
                        onChange={(e) => setEditingChange((prev) => ({ ...prev, description: e.target.value }))}
                      />

                      <label className="bugtracker-label">Severity / Priority</label>
                      <div className="bugtracker-severity-row">
                        {SEVERITIES.map((s) => (
                          <button
                            key={s.key}
                            type="button"
                            className={`bugtracker-severity-pill ${editingChange.severity === s.key ? 'active' : ''}`}
                            style={editingChange.severity === s.key ? { background: s.color, borderColor: s.color } : { borderColor: s.color, color: s.color }}
                            onClick={() => setEditingChange((prev) => ({ ...prev, severity: s.key }))}
                          >
                            {s.label}
                          </button>
                        ))}
                      </div>

                      {Object.keys(editingChange.answers || {}).length > 0 && (
                        <>
                          <h3 className="bugtracker-section-title">Details</h3>
                          {Object.entries(editingChange.answers).map(([k, v]) => (
                            <div key={k}>
                              <label className="bugtracker-label">{k.replace(/_/g, ' ')}</label>
                              <textarea
                                className="bugtracker-textarea"
                                rows={2}
                                value={v || ''}
                                onChange={(e) => setEditingChange((prev) => ({
                                  ...prev,
                                  answers: { ...prev.answers, [k]: e.target.value },
                                }))}
                              />
                            </div>
                          ))}
                        </>
                      )}

                      <label className="bugtracker-label">Add more attachments (optional)</label>
                      <input
                        type="file"
                        multiple
                        onChange={handleEditFilesSelected}
                        className="bugtracker-file-input"
                        accept="image/*,.md,.txt,.log,.pdf,.json,.csv"
                      />
                      {editingChange.fileError && <div className="bugtracker-error">{editingChange.fileError}</div>}
                      {editingChange.files.length > 0 && (
                        <ul className="bugtracker-file-list">
                          {editingChange.files.map((f, idx) => (
                            <li key={idx} className="bugtracker-file-item">
                              <span>{f.name}</span>
                              <span className="bugtracker-file-size">{formatBytes(f.size)}</span>
                              <button className="bugtracker-file-remove" onClick={() => removeEditFile(idx)}><CloseRoundedIcon fontSize="inherit" /></button>
                            </li>
                          ))}
                        </ul>
                      )}

                      {editingChange.submitError && <div className="bugtracker-error">{editingChange.submitError}</div>}

                      <div className="bugtracker-actions">
                        <button className="bugtracker-btn-secondary" onClick={cancelEditing} disabled={editingChange.submitting}>
                          Cancel
                        </button>
                        <button className="bugtracker-btn-primary" onClick={submitEditing} disabled={editingChange.submitting}>
                          {editingChange.submitting ? 'Saving...' : 'Save Changes'}
                        </button>
                      </div>
                    </div>
                  )}

                  {expandedId === b.id && editingChange?.bugId !== b.id && (
                    <div className="bugtracker-list-detail">
                      {b.description && <p>{b.description}</p>}
                      {Object.entries(b.answers || {}).filter(([, v]) => v).map(([k, v]) => (
                        <div key={k} className="bugtracker-review-row"><strong>{k.replace(/_/g, ' ')}:</strong> {v}</div>
                      ))}
                      {b.odoo_task_id && <div className="bugtracker-review-row"><strong>Odoo task:</strong> #{b.odoo_task_id} in {b.project_name}</div>}
                      {b.odoo_sync_error && <div className="bugtracker-error">Odoo sync error: {b.odoo_sync_error}</div>}

                      {(b.status_updates || []).length > 0 && (
                        <div className="bugtracker-status-history">
                          <h3 className="bugtracker-section-title">Status history</h3>
                          <ul className="bugtracker-status-history-list">
                            {b.status_updates.map((u, i) => (
                              <li key={i} className="bugtracker-status-history-item">
                                <div className="bugtracker-status-history-head">
                                  <span className="bugtracker-badge" style={{ background: STATUS_META[u.status]?.color || '#868e96' }}>
                                    {STATUS_META[u.status]?.label || u.status}
                                  </span>
                                  <span className="bugtracker-list-date">{formatDate(u.created_at)}</span>
                                </div>
                                {Object.entries(u.fields || {}).filter(([, v]) => v).map(([k, v]) => (
                                  <div key={k} className="bugtracker-review-row"><strong>{k.replace(/_/g, ' ')}:</strong> {v}</div>
                                ))}
                                {(u.attachments || []).length > 0 && (
                                  <div className="bugtracker-review-row">
                                    <strong>Attachments:</strong> <AttachmentChips attachments={u.attachments} />
                                  </div>
                                )}
                                {u.odoo_sync_error && <div className="bugtracker-error">Odoo sync error: {u.odoo_sync_error}</div>}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      <div className="bugtracker-status-row">
                        {isReporter ? (
                          <>
                            <label className="bugtracker-label">Status:</label>
                            <span>{STATUS_META[b.status]?.label || b.status}</span>
                          </>
                        ) : (
                          <>
                            <label className="bugtracker-label">Update status:</label>
                            <select
                              className="bugtracker-select"
                              value={pendingChange?.bugId === b.id ? pendingChange.status : b.status}
                              onChange={(e) => handleStatusSelect(b, e.target.value)}
                            >
                              {Object.entries(STATUS_META).map(([key, meta]) => (
                                <option key={key} value={key}>{meta.label}</option>
                              ))}
                            </select>
                          </>
                        )}
                      </div>

                      {pendingChange?.bugId === b.id && (
                        <div className="bugtracker-status-update-form">
                          <h3 className="bugtracker-section-title">
                            Update to {STATUS_META[pendingChange.status]?.label}
                          </h3>

                          {(statusFieldsMap[pendingChange.status] || []).map((f) => (
                            <div key={f.key}>
                              <label className="bugtracker-label">
                                <QuestionIcon fieldKey={f.key} /> {f.label}{f.required ? ' *' : ''}
                              </label>
                              <textarea
                                className="bugtracker-textarea"
                                rows={2}
                                placeholder={f.placeholder}
                                value={pendingChange.fieldValues[f.key] || ''}
                                onChange={(e) => handlePendingFieldChange(f.key, e.target.value)}
                              />
                            </div>
                          ))}

                          <label className="bugtracker-label">Attachments (optional)</label>
                          <p className="bugtracker-hint">Up to {MAX_FILES} files, 8MB each.</p>
                          <input
                            type="file"
                            multiple
                            onChange={handlePendingFilesSelected}
                            className="bugtracker-file-input"
                            accept="image/*,.md,.txt,.log,.pdf,.json,.csv"
                          />
                          {pendingChange.fileError && <div className="bugtracker-error">{pendingChange.fileError}</div>}
                          {pendingChange.files.length > 0 && (
                            <ul className="bugtracker-file-list">
                              {pendingChange.files.map((f, idx) => (
                                <li key={idx} className="bugtracker-file-item">
                                  <span>{f.name}</span>
                                  <span className="bugtracker-file-size">{formatBytes(f.size)}</span>
                                  <button className="bugtracker-file-remove" onClick={() => removePendingFile(idx)}><CloseRoundedIcon fontSize="inherit" /></button>
                                </li>
                              ))}
                            </ul>
                          )}

                          {pendingChange.submitError && <div className="bugtracker-error">{pendingChange.submitError}</div>}

                          <div className="bugtracker-actions">
                            <button className="bugtracker-btn-secondary" onClick={cancelPendingChange} disabled={pendingChange.submitting}>
                              Cancel
                            </button>
                            <button className="bugtracker-btn-primary" onClick={submitPendingChange} disabled={pendingChange.submitting}>
                              {pendingChange.submitting ? 'Updating...' : 'Confirm Update'}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {!bugsLoading && !bugsError && bugs.length > 0 && (
            <div className="bugtracker-list-window">
              <span className="bugtracker-list-window-label">Show:</span>
              <button
                type="button"
                className={`bugtracker-window-btn ${listWindow === 'first5' ? 'active' : ''}`}
                onClick={() => setListWindow(listWindow === 'first5' ? 'all' : 'first5')}
                title="Show the first 5 reports (most recent)"
              >
                <SkipPreviousRoundedIcon fontSize="inherit" /> First 5
              </button>
              <button
                type="button"
                className={`bugtracker-window-btn ${listWindow === 'last5' ? 'active' : ''}`}
                onClick={() => setListWindow(listWindow === 'last5' ? 'all' : 'last5')}
                title="Show the last 5 reports (oldest of this list)"
              >
                Last 5 <SkipNextRoundedIcon fontSize="inherit" />
              </button>
              {listWindow !== 'all' && (
                <button
                  type="button"
                  className="bugtracker-window-btn"
                  onClick={() => setListWindow('all')}
                  title="Show every report in this list"
                >
                  Show All ({bugs.length})
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'sprints' && (
        <div className="bugtracker-card bugtracker-card--sprints">
          {sprintMessage && <div className="bugtracker-hint bugtracker-sprint-message">{sprintMessage}</div>}

          {sprintBoardLoading ? (
            <LoadingSpinner />
          ) : sprintBoardError ? (
            <div className="bugtracker-error">{sprintBoardError}</div>
          ) : sprintBoard ? (
            <div className="bugtracker-sprint-board">
              <div className="bugtracker-sprint-col bugtracker-sprint-col--backlog">
                <div className="bugtracker-sprint-col-head">
                  <span>Backlog</span>
                  <span className="bugtracker-sprint-count">{sprintBoard.backlog.length}</span>
                </div>
                {sprintBoard.backlog.length === 0 ? (
                  <div className="bugtracker-sprint-empty">Empty</div>
                ) : (
                  <ul className="bugtracker-sprint-items">
                    {sprintBoard.backlog.map((b) => (
                      <SprintCard
                        key={b.id}
                        bug={b}
                        variant="backlog"
                        onOpen={() => setSprintDetailBug(b)}
                        onAssignSprint={(n) => handleAssignSprint(b.id, n)}
                        removing={sprintUpdatingId === b.id}
                      />
                    ))}
                  </ul>
                )}
              </div>

              {sprintBoard.sprints.map((s) => (
                <div key={s.number} className={`bugtracker-sprint-col ${s.full ? 'bugtracker-sprint-col--full' : ''}`}>
                  <div className="bugtracker-sprint-col-head">
                    <span>Sprint</span>
                    <span className={`bugtracker-sprint-count ${s.full ? 'bugtracker-sprint-count--full' : ''}`}>
                      {s.count}/{s.capacity}{s.full ? ' \u2022 full' : ''}
                    </span>
                  </div>
                  <div className="bugtracker-sprint-capacity-track">
                    <div
                      className="bugtracker-sprint-capacity-fill"
                      style={{
                        width: `${Math.min(100, (s.count / s.capacity) * 100)}%`,
                        background: s.full ? '#e8590c' : '#1971c2',
                      }}
                    />
                  </div>
                  {s.items.length === 0 ? (
                    <div className="bugtracker-sprint-empty">No reports planned yet</div>
                  ) : (
                    <ul className="bugtracker-sprint-items">
                      {s.items.map((b) => (
                        <SprintCard
                          key={b.id}
                          bug={b}
                          variant="sprint"
                          onOpen={() => setSprintDetailBug(b)}
                          onRemoveSprint={() => handleAssignSprint(b.id, null)}
                          onToggleRoadmap={(v, note) => handleAssignRoadmap(b.id, v, note)}
                          removing={sprintUpdatingId === b.id}
                        />
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}

      {tab === 'updates' && (
        <div className="bugtracker-card bugtracker-updates-card">
          <div className="bugtracker-step-header">
            <h2 className="bugtracker-step-title">Team Updates</h2>
          </div>
          {updatesLoading ? (
            <LoadingSpinner />
          ) : updatesError ? (
            <div className="bugtracker-error">{updatesError}</div>
          ) : updates.length === 0 ? (
            <div className="bugtracker-empty-state">No updates posted yet.</div>
          ) : (
            <div className="bugtracker-updates-grid">
              {updates.map((u) => {
                const images = u.images && u.images.length > 0
                  ? u.images
                  : (u.has_image ? [{ id: null, legacy: true, filename: u.description }] : []);
                return (
                  <div key={u.id} className="bugtracker-update-card">
                    {images.length > 0 && (
                      images.length === 1 ? (
                        <div className="bugtracker-update-image-wrap">
                          <img
                            className="bugtracker-update-image"
                            src={images[0].id ? getUpdateGalleryImageUrl(images[0].id) : getUpdateImageUrl(u.id)}
                            alt={u.description}
                            loading="lazy"
                          />
                        </div>
                      ) : (
                        <div className="bugtracker-update-image-scroll">
                          {images.map((img, idx) => (
                            <div key={img.id || idx} className="bugtracker-update-image-wrap bugtracker-update-image-wrap--scroll">
                              <img
                                className="bugtracker-update-image"
                                src={img.id ? getUpdateGalleryImageUrl(img.id) : getUpdateImageUrl(u.id)}
                                alt={`${u.description} (${idx + 1}/${images.length})`}
                                loading="lazy"
                              />
                            </div>
                          ))}
                        </div>
                      )
                    )}
                    <div className="bugtracker-update-body">
                      <p className="bugtracker-update-description">{u.description}</p>
                      {u.attachments && u.attachments.length > 0 && (
                        <div className="bugtracker-update-attachments">
                          <AttachmentChips
                            attachments={u.attachments}
                            getViewUrl={getUpdateAttachmentViewUrl}
                            getDownloadUrl={getUpdateAttachmentDownloadUrl}
                          />
                        </div>
                      )}
                      <div className="bugtracker-update-meta">
                        <span className="bugtracker-update-author">{u.author_name || 'Unknown'}</span>
                        <span className="bugtracker-update-dot">&bull;</span>
                        <span className="bugtracker-update-time">{formatRelativeTime(u.created_at)}</span>
                        {!isReporter && (
                          <button
                            className="bugtracker-update-delete"
                            onClick={() => handleDeleteUpdate(u.id)}
                            title="Delete update"
                          >
                            <CloseRoundedIcon fontSize="inherit" />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {sprintDetailBug && (
        <BugDetailModal
          bug={sprintDetailBug}
          onClose={() => setSprintDetailBug(null)}
          onDownload={() => handleDownloadBug(sprintDetailBug)}
          downloading={downloadingId === sprintDetailBug.id}
          onEdit={() => {
            setSprintDetailBug(null);
            setTab('list');
            startEditing(sprintDetailBug);
          }}
          onAssignSprint={(n) => {
            handleAssignSprint(sprintDetailBug.id, n);
            setSprintDetailBug((prev) => (prev ? { ...prev, sprint: n } : prev));
          }}
          onAssignRoadmap={(v, note) => {
            handleAssignRoadmap(sprintDetailBug.id, v, note);
            setSprintDetailBug((prev) => (prev ? { ...prev, roadmap: v, roadmap_note: v ? note : null } : prev));
          }}
          sprintUpdating={sprintUpdatingId === sprintDetailBug.id}
        />
      )}

      {showPostModal && (
        <div className="bugtracker-modal-overlay" onClick={resetPostModal}>
          <div className="bugtracker-modal bugtracker-post-modal" onClick={(e) => e.stopPropagation()}>
            <button className="bugtracker-modal-close" onClick={resetPostModal} title="Close">
              <CloseRoundedIcon fontSize="small" />
            </button>
            <h2 className="bugtracker-modal-title">Post an Update</h2>

            <div className="bugtracker-post-image-grid">
              {postImageFiles.map((img, idx) => (
                <div key={idx} className="bugtracker-post-image-thumb">
                  <img src={img.preview} alt={`Selected ${idx + 1}`} />
                  <button
                    type="button"
                    className="bugtracker-post-image-remove"
                    onClick={() => removePostImage(idx)}
                    title="Remove image"
                  >
                    <CloseRoundedIcon fontSize="inherit" />
                  </button>
                </div>
              ))}
              {postImageFiles.length < MAX_UPDATE_IMAGES && (
                <label className="bugtracker-post-image-drop bugtracker-post-image-drop--add" htmlFor="post-update-images">
                  <span className="bugtracker-post-image-placeholder">
                    <AddRoundedIcon fontSize="medium" />
                    {postImageFiles.length === 0 ? 'Add images' : 'Add more'}
                  </span>
                </label>
              )}
            </div>
            <input
              id="post-update-images"
              type="file"
              accept="image/*"
              multiple
              onChange={handlePostImagesChange}
              style={{ display: 'none' }}
            />
            <p className="bugtracker-hint">Images are optional -- up to {MAX_UPDATE_IMAGES}, 8MB each.</p>

            <textarea
              className="bugtracker-textarea"
              placeholder="Say something about this update..."
              rows={3}
              value={postDescription}
              onChange={(e) => setPostDescription(e.target.value)}
              maxLength={2000}
            />

            <label className="bugtracker-post-file-attach" htmlFor="post-update-files">
              <AttachFileRoundedIcon fontSize="small" />
              Attach files (optional)
            </label>
            <input
              id="post-update-files"
              type="file"
              multiple
              onChange={handlePostAttachmentsChange}
              style={{ display: 'none' }}
            />
            {postAttachmentFiles.length > 0 && (
              <ul className="bugtracker-post-file-list">
                {postAttachmentFiles.map((f, idx) => (
                  <li key={idx} className="bugtracker-post-file-item">
                    <AttachFileRoundedIcon fontSize="inherit" />
                    <span className="bugtracker-post-file-name">{f.name}</span>
                    <button
                      type="button"
                      className="bugtracker-post-file-remove"
                      onClick={() => removePostAttachment(idx)}
                      title="Remove file"
                    >
                      <CloseRoundedIcon fontSize="inherit" />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {postFileError && <div className="bugtracker-error">{postFileError}</div>}
            {postError && <div className="bugtracker-error">{postError}</div>}

            <div className="bugtracker-actions">
              <button className="bugtracker-btn-secondary" onClick={resetPostModal} disabled={posting}>
                Cancel
              </button>
              <button className="bugtracker-btn-primary" onClick={handlePostUpdate} disabled={posting}>
                {posting ? 'Posting...' : 'Post Update'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// A single Odoo-kanban-style card: colored status bar, category + priority
// chips, reporter, an attachment count, and a workflow progress bar (Odoo's
// project.task kanban shows the same kind of stage-progress indicator).
//
// `variant` controls the action button in the footer:
//   'backlog' -- unplanned -> "+ Sprint"
//   'sprint'  -- currently in the active sprint -> "Backlog" (remove), plus
//                an inline "Future roadmap" checkbox right on the card --
//                flagging a sprint item for the roadmap doesn't move it
//                anywhere, it just tags it. Checking it reveals a small
//                optional note field (e.g. "Target: Q3") saved on blur.
function SprintCard({ bug, onOpen, variant = 'sprint', removing, onAssignSprint, onRemoveSprint, onToggleRoadmap }) {
  const progress = STATUS_PROGRESS[bug.status] ?? 0;
  const statusColor = STATUS_META[bug.status]?.color || '#868e96';
  const [noteDraft, setNoteDraft] = useState(bug.roadmap_note || '');

  return (
    <li className={`bugtracker-sprint-item ${bug.roadmap ? 'bugtracker-sprint-item--roadmap' : ''}`} onClick={onOpen}>
      <div className="bugtracker-sprint-item-statusbar" style={{ background: statusColor }} />
      <div className="bugtracker-sprint-item-body">
        <div className="bugtracker-sprint-item-toprow">
          <span className="bugtracker-list-icon"><CategoryIcon category={bug.category} /></span>
          <span className="bugtracker-sprint-item-title" title={bug.title}>{bug.title}</span>
          {bug.roadmap && (
            <span
              className="bugtracker-roadmap-chip"
              title={bug.roadmap_note ? `On the Future Roadmap: ${bug.roadmap_note}` : 'On the Future Roadmap'}
            >
              <PlaceRoundedIcon fontSize="inherit" />
            </span>
          )}
        </div>
        <div className="bugtracker-sprint-item-metarow">
          <span
            className="bugtracker-priority-badge bugtracker-priority-badge--sm"
            style={{
              background: SEVERITY_META[bug.severity]?.color ? `${SEVERITY_META[bug.severity].color}1a` : '#f1f3f5',
              color: SEVERITY_META[bug.severity]?.color || '#495057',
              borderColor: SEVERITY_META[bug.severity]?.color || '#ced4da',
            }}
          >
            {SEVERITY_META[bug.severity]?.label || bug.severity}
          </span>
          <span className="bugtracker-sprint-item-reporter" title={bug.reporter_name}>{bug.reporter_name || 'Unknown'}</span>
          {(bug.attachments || []).length > 0 && (
            <span className="bugtracker-sprint-item-attachcount" title={`${bug.attachments.length} attachment(s)`}>
              <AttachFileRoundedIcon fontSize="inherit" /> {bug.attachments.length}
            </span>
          )}
        </div>
        <div className="bugtracker-sprint-progress-track" title={`${STATUS_META[bug.status]?.label || bug.status} \u2022 ${progress}%`}>
          <div className="bugtracker-sprint-progress-fill" style={{ width: `${progress}%`, background: statusColor }} />
        </div>

        {variant === 'sprint' && (
          <div className="bugtracker-roadmap-control" onClick={(e) => e.stopPropagation()}>
            <label className="bugtracker-roadmap-checkbox">
              <input
                type="checkbox"
                checked={!!bug.roadmap}
                disabled={removing}
                onChange={(e) => {
                  const checked = e.target.checked;
                  onToggleRoadmap(checked, checked ? noteDraft : '');
                  if (!checked) setNoteDraft('');
                }}
              />
              Add to future roadmap?
            </label>
            {bug.roadmap && (
              <input
                type="text"
                className="bugtracker-roadmap-note-input"
                placeholder="Optional note (e.g. Target: Q3)"
                value={noteDraft}
                maxLength={280}
                disabled={removing}
                onChange={(e) => setNoteDraft(e.target.value)}
                onBlur={() => onToggleRoadmap(true, noteDraft)}
              />
            )}
          </div>
        )}

        <div className="bugtracker-sprint-item-footrow">
          <span className="bugtracker-badge bugtracker-badge--sm" style={{ background: statusColor }}>
            {STATUS_META[bug.status]?.label || bug.status}
          </span>
          {variant === 'backlog' ? (
            <button
              className="bugtracker-sprint-add-btn"
              onClick={(e) => { e.stopPropagation(); onAssignSprint(1); }}
              disabled={removing}
              title="Add to the sprint"
            >
              <AddRoundedIcon fontSize="inherit" /> Add to Sprint
            </button>
          ) : (
            <button
              className="bugtracker-sprint-item-remove"
              onClick={(e) => { e.stopPropagation(); onRemoveSprint(); }}
              disabled={removing}
              title="Move back to Backlog"
            >
              <CloseRoundedIcon fontSize="inherit" /> Backlog
            </button>
          )}
        </div>
      </div>
    </li>
  );
}

// Full-detail modal for a report -- reachable from a Sprint card click, so
// you can open and read (and edit/download) a report without leaving the
// sprint board.
function BugDetailModal({ bug, onClose, onDownload, downloading, onEdit, onAssignSprint, onAssignRoadmap, sprintUpdating }) {
  const progress = STATUS_PROGRESS[bug.status] ?? 0;
  const statusColor = STATUS_META[bug.status]?.color || '#868e96';
  const [roadmapNoteDraft, setRoadmapNoteDraft] = useState(bug.roadmap_note || '');
  return (
    <div className="bugtracker-modal-overlay" onClick={onClose}>
      <div className="bugtracker-modal" onClick={(e) => e.stopPropagation()}>
        <button className="bugtracker-modal-close" onClick={onClose} title="Close"><CloseRoundedIcon fontSize="small" /></button>

        <div className="bugtracker-list-category" title={CATEGORY_META[bug.category]?.title || bug.category}>
          <span className="bugtracker-list-icon"><CategoryIcon category={bug.category} /></span>
          <span className="bugtracker-list-category-label">{CATEGORY_META[bug.category]?.title || bug.category}</span>
        </div>
        <h2 className="bugtracker-modal-title">{bug.title}</h2>

        <div className="bugtracker-sprint-progress-track" title={`${STATUS_META[bug.status]?.label || bug.status} \u2022 ${progress}%`}>
          <div className="bugtracker-sprint-progress-fill" style={{ width: `${progress}%`, background: statusColor }} />
        </div>
        <div className="bugtracker-modal-status-row">
          <span className="bugtracker-badge" style={{ background: statusColor }}>{STATUS_META[bug.status]?.label || bug.status}</span>
          <span className="bugtracker-modal-progress-label">{progress}% through workflow</span>
        </div>

        <div className="bugtracker-list-meta bugtracker-modal-meta">
          <span className="bugtracker-meta-item"><strong>Reported by:</strong> {bug.reporter_name || 'Unknown'}</span>
          <span className="bugtracker-meta-item"><strong>Date:</strong> {formatDate(bug.created_at)}</span>
          <span
            className="bugtracker-priority-badge"
            style={{
              background: SEVERITY_META[bug.severity]?.color ? `${SEVERITY_META[bug.severity].color}1a` : '#f1f3f5',
              color: SEVERITY_META[bug.severity]?.color || '#495057',
              borderColor: SEVERITY_META[bug.severity]?.color || '#ced4da',
            }}
          >
            Priority: {SEVERITY_META[bug.severity]?.label || bug.severity}
          </span>
        </div>

        {bug.description && <p className="bugtracker-modal-description">{bug.description}</p>}

        {Object.entries(bug.answers || {}).filter(([, v]) => v).map(([k, v]) => (
          <div key={k} className="bugtracker-review-row"><strong>{k.replace(/_/g, ' ')}:</strong> {v}</div>
        ))}

        <div className="bugtracker-review-row">
          <strong>Attachments:</strong> <AttachmentChips attachments={bug.attachments} />
        </div>

        {bug.odoo_task_id && <div className="bugtracker-review-row"><strong>Odoo task:</strong> #{bug.odoo_task_id} in {bug.project_name}</div>}
        {bug.odoo_sync_error && <div className="bugtracker-error">Odoo sync error: {bug.odoo_sync_error}</div>}

        <div className="bugtracker-modal-sprint-row">
          <label className="bugtracker-label">Sprint:</label>
          {bug.sprint ? (
            <button
              className="bugtracker-sprint-toggle-btn bugtracker-sprint-toggle-btn--in"
              onClick={() => onAssignSprint(null)}
              disabled={sprintUpdating}
            >
              <CheckRoundedIcon fontSize="inherit" /> In Sprint -- click to move to Backlog
            </button>
          ) : (
            <button
              className="bugtracker-sprint-toggle-btn"
              onClick={() => onAssignSprint(1)}
              disabled={sprintUpdating}
            >
              <AddRoundedIcon fontSize="inherit" /> Add to Sprint
            </button>
          )}
        </div>

        {onAssignRoadmap && (
          <div className="bugtracker-modal-sprint-row bugtracker-modal-roadmap-row">
            <label className="bugtracker-label">Future Roadmap:</label>
            {bug.roadmap ? (
              <>
                <button
                  className="bugtracker-sprint-toggle-btn bugtracker-sprint-toggle-btn--in"
                  onClick={() => onAssignRoadmap(false, '')}
                  disabled={sprintUpdating}
                >
                  <CheckRoundedIcon fontSize="inherit" /> Flagged -- click to unflag
                </button>
                <input
                  type="text"
                  className="bugtracker-roadmap-note-input"
                  placeholder="Optional note (e.g. Target: Q3)"
                  value={roadmapNoteDraft}
                  maxLength={280}
                  disabled={sprintUpdating}
                  onChange={(e) => setRoadmapNoteDraft(e.target.value)}
                  onBlur={() => onAssignRoadmap(true, roadmapNoteDraft)}
                />
              </>
            ) : (
              <button
                className="bugtracker-sprint-toggle-btn"
                onClick={() => onAssignRoadmap(true, roadmapNoteDraft)}
                disabled={sprintUpdating}
                title="Also carry this onto the future roadmap"
              >
                <AddRoundedIcon fontSize="inherit" /> Flag for Roadmap
              </button>
            )}
          </div>
        )}

        <div className="bugtracker-actions">
          <button className="bugtracker-btn-secondary" onClick={onDownload} disabled={downloading}>
            {downloading ? 'Downloading...' : (<><DownloadRoundedIcon fontSize="inherit" /> Download</>)}
          </button>
          <button className="bugtracker-btn-primary" onClick={onEdit}>
            <EditRoundedIcon fontSize="inherit" /> Edit Report
          </button>
        </div>
      </div>
    </div>
  );
}