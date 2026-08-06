import React, { useEffect, useState, useCallback, useRef } from 'react';
import { reportAPI, authAPI } from '../services/api';
import './TaskWizard.css';

const STEPS = [
  { id: 1, label: 'Engineer' },
  { id: 2, label: 'Project' },
  { id: 3, label: 'Task' },
  { id: 4, label: 'Log Details' },
  { id: 5, label: 'Review' },
];

const STATUS_LABELS = {
  completed: 'Completed',
  in_progress: 'In Progress',
  blocker: 'Hold / Blocker',
};

function WizardDropdown({ value, onChange, options, placeholder = 'Select...', disabled }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selected = options.find((o) => String(o.value) === String(value));

  return (
    <div className="wizard-dropdown" ref={ref}>
      <button
        type="button"
        className={`wizard-dropdown-trigger ${open ? 'open' : ''}`}
        onClick={() => !disabled && setOpen((prev) => !prev)}
        disabled={disabled}
      >
        <span className={selected ? 'wizard-dropdown-value' : 'wizard-dropdown-placeholder'}>
          {selected ? selected.label : placeholder}
        </span>
        <span className="wizard-dropdown-arrow">&#9662;</span>
      </button>
      {open && (
        <div className="wizard-dropdown-menu">
          {options.length === 0 ? (
            <div className="wizard-dropdown-empty">No options available</div>
          ) : (
            options.map((o) => (
              <div
                key={o.value}
                className={`wizard-dropdown-option ${String(o.value) === String(value) ? 'selected' : ''}`}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
              >
                {o.label}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function TaskWizard() {
  const [step, setStep] = useState(1);
  const [users, setUsers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [taskContext, setTaskContext] = useState(null);
  const [loading, setLoading] = useState({});
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const [mdFile, setMdFile] = useState(null);
  const [mdFileContent, setMdFileContent] = useState('');
  const [kbEnabled, setKbEnabled] = useState(false);
  const [kbLocalCopy, setKbLocalCopy] = useState(true);
  const [xwikiMode, setXwikiMode] = useState('content'); // 'content' | 'attachment'
  const [xwikiSpace, setXwikiSpace] = useState('');
  const [xwikiPage, setXwikiPage] = useState('');
  const [xwikiPageData, setXwikiPageData] = useState(null);
  const [xwikiContent, setXwikiContent] = useState('');
  const [xwikiSaving, setXwikiSaving] = useState(false);

  const [form, setForm] = useState({
    userId: '',
    projectId: '',
    taskId: '',
    userSummary: '',
    status: '',            // 'completed' | 'in_progress' | 'blocker'
    answers: {},            // dynamic { [questionKey]: text }
    supportRequired: '',    // 'yes' | 'no' | ''
    supportPerson: '',
    aiSummary: '',
    customPrompt: '',
    sendEmail: false,
    emailRecipients: '',
    markComplete: false,
    hours: '',
    priority: '',
    date: new Date().toISOString().slice(0, 10),
  });

  const setFormField = (field, value) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const setAnswerField = (key, value) =>
    setForm((prev) => ({ ...prev, answers: { ...prev.answers, [key]: value } }));

  // Support-person typeahead (searches Odoo live)
  const [supportSearchResults, setSupportSearchResults] = useState([]);
  const [supportSearchOpen, setSupportSearchOpen] = useState(false);
  const [supportSearching, setSupportSearching] = useState(false);
  const [supportOtherMode, setSupportOtherMode] = useState(false);
  const supportSearchTimer = useRef(null);
  const supportFieldRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (supportFieldRef.current && !supportFieldRef.current.contains(e.target)) {
        setSupportSearchOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSupportPersonChange = (value) => {
    setFormField('supportPerson', value);
    setSupportSearchOpen(true);
    if (supportSearchTimer.current) clearTimeout(supportSearchTimer.current);
    if (!value || value.trim().length < 2) {
      setSupportSearchResults([]);
      return;
    }
    supportSearchTimer.current = setTimeout(async () => {
      setSupportSearching(true);
      try {
        const res = await reportAPI.searchOdooUsers(value.trim());
        setSupportSearchResults(res.data.data || []);
      } catch (e) {
        setSupportSearchResults([]);
      } finally {
        setSupportSearching(false);
      }
    }, 300);
  };

  const selectedProject = projects.find((p) => String(p.id) === String(form.projectId));
  const selectedTask = tasks.find((t) => String(t.id) === String(form.taskId));
  const selectedUser = users.find((u) => String(u.id) === String(form.userId));

  // True while we're pulling fresh data from Odoo (new tasks, renamed
  // projects, etc.) so newly-created Odoo tasks show up here right away
  // instead of waiting for the next scheduled sync.
  const [syncingOdoo, setSyncingOdoo] = useState(false);

  useEffect(() => {
    fetchUsers();
    syncThenFetchProjects();
    const stored = authAPI.getUser();
    if (stored && stored.id) {
      setForm((prev) => ({ ...prev, userId: stored.id }));
      setStep(2);
    }
  }, []);

  const fetchUsers = async () => {
    setLoading((prev) => ({ ...prev, users: true }));
    try {
      const res = await reportAPI.getUsers();
      setUsers(res.data.data || []);
    } catch (e) {
      setError('Failed to load engineers.');
    } finally {
      setLoading((prev) => ({ ...prev, users: false }));
    }
  };

  const fetchProjects = async () => {
    setLoading((prev) => ({ ...prev, projects: true }));
    try {
      const res = await reportAPI.getProjects();
      setProjects(res.data.data || []);
    } catch (e) {
      setError('Failed to load projects.');
    } finally {
      setLoading((prev) => ({ ...prev, projects: false }));
    }
  };

  // Pull the latest projects/tasks from Odoo first, then refresh the local
  // lists -- this is what makes a task created in Odoo show up here without
  // waiting for the background sync job.
  const syncThenFetchProjects = async () => {
    setSyncingOdoo(true);
    try {
      await reportAPI.syncOdoo();
    } catch (e) {
      // Non-fatal: fall back to whatever is already in the local DB.
      console.error('Odoo sync failed, showing last-known projects/tasks.', e);
    } finally {
      setSyncingOdoo(false);
    }
    await fetchProjects();
    if (form.projectId) {
      await fetchTasks(form.projectId);
    }
  };

  const fetchTasks = useCallback(async (projectId) => {
    if (!projectId) {
      setTasks([]);
      return;
    }
    setLoading((prev) => ({ ...prev, tasks: true }));
    try {
      const res = await reportAPI.getTasks(projectId);
      setTasks(res.data.data || []);
    } catch (e) {
      setError('Failed to load tasks.');
    } finally {
      setLoading((prev) => ({ ...prev, tasks: false }));
    }
  }, []);

  const prevTaskIdRef = useRef(null);

  // Load just recent activity for a task (used for the initial placeholder /
  // skeleton before the engineer has even picked a status).
  const fetchRecentActivity = useCallback(async (taskId) => {
    if (!taskId) {
      setTaskContext(null);
      return;
    }
    setLoading((prev) => ({ ...prev, activity: true }));
    try {
      const res = await reportAPI.getTaskContext(taskId, '', '');
      setTaskContext(res.data.data);
    } catch (e) {
      setError('Failed to load recent activity.');
    } finally {
      setLoading((prev) => ({ ...prev, activity: false }));
    }
  }, []);

  const fetchTaskContext = useCallback(async (taskId, summary, status) => {
    if (!taskId || !status) {
      return;
    }
    setLoading((prev) => ({ ...prev, context: true }));
    try {
      const res = await reportAPI.getTaskContext(taskId, summary || '', status);
      setTaskContext(res.data.data);
      const questions = res.data.data.questions || [];
      // Leave each answer box empty for the user to fill in -- never
      // pre-fill it with the question text itself, and never clobber
      // something the user already typed for a key that's still present.
      setForm((prev) => {
        const nextAnswers = {};
        questions.forEach((q) => { nextAnswers[q.key] = prev.answers[q.key] || ''; });
        return { ...prev, answers: nextAnswers };
      });
      prevTaskIdRef.current = taskId;
    } catch (e) {
      setError('Failed to load task context.');
    } finally {
      setLoading((prev) => ({ ...prev, context: false }));
    }
  }, []);

  useEffect(() => {
    fetchTasks(form.projectId);
  }, [form.projectId, fetchTasks]);

  useEffect(() => {
    if (step === 4 && form.taskId) {
      if (form.status) {
        // Returning to this step with a status already chosen — refresh
        // activity + keep questions in sync with that status (don't fall
        // back to generic placeholder questions).
        fetchTaskContext(form.taskId, form.userSummary, form.status);
      } else {
        fetchRecentActivity(form.taskId);
      }
    }
  }, [step, form.taskId, fetchRecentActivity]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (selectedTask && selectedTask.priority && !form.priority) {
      setFormField('priority', selectedTask.priority);
    }
  }, [selectedTask]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleStatusChange = (status) => {
    setFormField('status', status);
    setFormField('supportRequired', '');
    setFormField('supportPerson', '');
    setFormField('aiSummary', '');
    if (status !== 'completed') setFormField('markComplete', false);
    setSupportOtherMode(false);
    fetchTaskContext(form.taskId, form.userSummary, status);
  };

  useEffect(() => {
    if (kbEnabled && selectedTask) {
      const slug = selectedTask.name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
        .substring(0, 80);
      setXwikiPage(slug);
      setXwikiPageData(null);
      setXwikiContent('');
      reportAPI.getXWikiConfig().then((res) => {
        if (res.data?.data?.default_space) {
          setXwikiSpace(res.data.data.default_space);
        }
      }).catch(() => {});
    }
  }, [kbEnabled, selectedTask]);

  useEffect(() => {
    if (!mdFile && xwikiMode === 'attachment') {
      setXwikiMode('content');
    }
  }, [mdFile, xwikiMode]);

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!file.name.endsWith('.md')) {
      setError('Only .md files are accepted.');
      e.target.value = '';
      return;
    }
    setError(null);
    setMdFile(file);
    const reader = new FileReader();
    reader.onload = (ev) => {
      const content = ev.target.result;
      setMdFileContent(content);
    };
    reader.readAsText(file);
  };

  const handleFetchXWiki = async () => {
    if (!xwikiSpace || !xwikiPage) return;
    setLoading((prev) => ({ ...prev, xwiki: true }));
    setError(null);
    try {
      const res = await reportAPI.getXWikiPage(xwikiSpace, xwikiPage);
      setXwikiPageData(res.data.data);
      const existing = res.data.data?.content || '';
      const initial = existing || (mdFileContent ? await convertMdContent(mdFileContent) : '');
      setXwikiContent(initial);
    } catch (e) {
      setError('Failed to fetch XWiki page.');
    } finally {
      setLoading((prev) => ({ ...prev, xwiki: false }));
    }
  };

  const convertMdContent = async (md) => {
    try {
      const res = await reportAPI.convertMdToXwiki(md);
      return res.data?.data?.xwiki || md;
    } catch {
      return md;
    }
  };

  const handleConvertMd = async () => {
    if (!mdFileContent) return;
    setLoading((prev) => ({ ...prev, convert: true }));
    try {
      const xwiki = await convertMdContent(mdFileContent);
      setXwikiContent(xwiki);
    } finally {
      setLoading((prev) => ({ ...prev, convert: false }));
    }
  };

  const handleSaveXWiki = async () => {
    if (!xwikiSpace || !xwikiPage) return;
    setXwikiSaving(true);
    setError(null);
    try {
      const res = await reportAPI.saveXWikiPage({
        space: xwikiSpace,
        page: xwikiPage,
        title: selectedTask?.name || xwikiPage,
        content: xwikiContent,
      });
      if (res.data.status === 'success') {
        return true;
      } else {
        setError(res.data.message || 'Failed to save to XWiki.');
        return false;
      }
    } catch (e) {
      setError('Failed to save to XWiki.');
      return false;
    } finally {
      setXwikiSaving(false);
    }
  };

  // Sends the original .md file to XWiki as a real file attachment, exactly
  // as uploaded -- no markdown -> XWiki syntax conversion, unlike handleSaveXWiki.
  const handleSaveXWikiAttachment = async () => {
    if (!xwikiSpace || !xwikiPage || !mdFile || !mdFileContent) return false;
    setXwikiSaving(true);
    setError(null);
    try {
      const res = await reportAPI.saveXWikiAttachment({
        space: xwikiSpace,
        page: xwikiPage,
        filename: mdFile.name,
        content: mdFileContent,
      });
      if (res.data.status === 'success') {
        return true;
      } else {
        setError(res.data.message || 'Failed to attach .md file to XWiki.');
        return false;
      }
    } catch (e) {
      setError('Failed to attach .md file to XWiki.');
      return false;
    } finally {
      setXwikiSaving(false);
    }
  };

  const handleGenerateSummary = async () => {
    if (!form.taskId || !form.status) return;
    setLoading((prev) => ({ ...prev, summary: true }));
    setError(null);
    try {
      const res = await reportAPI.generateTaskSummary(form.taskId, {
        status: form.status,
        user_summary: form.userSummary,
        answers: form.answers,
        custom_prompt: form.customPrompt,
      });
      setFormField('aiSummary', res.data.data.summary || '');
    } catch (e) {
      setError('Failed to generate summary.');
    } finally {
      setLoading((prev) => ({ ...prev, summary: false }));
    }
  };

  const handleSendSummaryEmail = async () => {
    if (!form.emailRecipients.trim()) {
      setError('Please enter at least one recipient email address.');
      return false;
    }
    try {
      await reportAPI.sendSummaryEmail({
        to: form.emailRecipients,
        subject: `Task Log Summary: ${selectedTask?.name || 'Task'}${form.priority ? ` [${form.priority}]` : ''}`,
        body: form.aiSummary || form.userSummary || 'No summary available.',
      });
      return true;
    } catch (e) {
      setError('Timesheet logged, but the summary email failed to send.');
      return false;
    }
  };

  // Saves a copy of the .md file to a local folder on the backend server
  // (backend/kb_storage/<project>/<task>/), created automatically if it
  // doesn't exist yet. Independent of the XWiki save above.
  const handleSaveKbLocal = async () => {
    if (!mdFile || !mdFileContent) return false;
    try {
      const res = await reportAPI.saveKbLocal({
        project_name: selectedProject?.name || '',
        task_name: selectedTask?.name || '',
        filename: mdFile.name,
        content: mdFileContent,
      });
      if (res.data.status === 'success') {
        return true;
      } else {
        setError(res.data.message || 'Failed to save local KB copy.');
        return false;
      }
    } catch (e) {
      setError('Failed to save local KB copy.');
      return false;
    }
  };

  const handleSubmit = async () => {
    const hoursVal = parseFloat(form.hours);
    if (!hoursVal || hoursVal <= 0) {
      setError('Please enter a valid number of hours (> 0).');
      return;
    }
    if (hoursVal > 24) {
      setError('Hours cannot exceed 24.');
      return;
    }
    setLoading((prev) => ({ ...prev, submit: true }));
    setError(null);
    setSuccess(null);
    try {
      // The log note should only ever contain the summary, tagged with
      // priority -- status, per-question answers, and support info are
      // sent as their own structured fields, not inlined into the note.
      const summaryText = form.aiSummary || form.userSummary || '';
      const logSummary = [form.priority ? `[${form.priority}]` : '', summaryText]
        .filter(Boolean)
        .join(' ');

      await reportAPI.logTimesheet({
        user_id: form.userId,
        task_id: form.taskId,
        hours: hoursVal,
        description: logSummary,
        log_summary: logSummary,
        date: form.date,
        priority: form.priority || undefined,
        status: form.status || undefined,
        support_required: form.supportRequired === 'yes',
        support_person: form.supportRequired === 'yes' ? form.supportPerson : '',
        mark_complete: form.markComplete,
      });

      let xwikiOk = true;
      if (kbEnabled && xwikiSpace && xwikiPage) {
        if (xwikiMode === 'attachment') {
          xwikiOk = await handleSaveXWikiAttachment();
        } else if (xwikiContent) {
          xwikiOk = await handleSaveXWiki();
        }
      }

      let kbLocalOk = true;
      if (kbEnabled && kbLocalCopy && mdFile) {
        kbLocalOk = await handleSaveKbLocal();
      }

      let emailOk = true;
      if (form.sendEmail) {
        emailOk = await handleSendSummaryEmail();
      }

      if (xwikiOk && kbLocalOk && emailOk) {
        setSuccess(kbEnabled ? 'Timesheet logged and Knowledge Base updated!' : 'Timesheet entry logged successfully!');
      } else if (!xwikiOk) {
        setSuccess('Timesheet logged, but XWiki save failed. Check the error above.');
      } else if (!kbLocalOk) {
        setSuccess('Timesheet logged, but the local KB copy failed to save. Check the error above.');
      } else {
        setSuccess('Timesheet logged successfully!');
      }
      setTimeout(() => {
        setStep(1);
        prevTaskIdRef.current = null;
        setForm({
          userId: '',
          projectId: '',
          taskId: '',
          userSummary: '',
          status: '',
          answers: {},
          supportRequired: '',
          supportPerson: '',
          aiSummary: '',
          customPrompt: '',
          sendEmail: false,
          emailRecipients: '',
          markComplete: false,
          hours: '',
          priority: '',
          date: new Date().toISOString().slice(0, 10),
        });
        setTaskContext(null);
        setMdFile(null);
        setMdFileContent('');
        setKbEnabled(false);
        setXwikiPage('');
        setXwikiSpace('');
        setXwikiPageData(null);
        setXwikiContent('');
        setSuccess(null);
      }, 3000);
    } catch (e) {
      setError(e.response?.data?.message || e.message || 'Failed to log timesheet.');
    } finally {
      setLoading((prev) => ({ ...prev, submit: false }));
    }
  };

  const nextStep = () => {
    setError(null);
    if (step === 1 && !form.userId) { setError('Please select an engineer.'); return; }
    if (step === 2 && !form.projectId) { setError('Please select a project.'); return; }
    if (step === 3 && !form.taskId) { setError('Please select a task.'); return; }
    if (step === 4) {
      if (!form.status) { setError('Please select a task status.'); return; }
      const hasAnswer = Object.values(form.answers).some((v) => v && v.trim());
      if (!hasAnswer && !form.userSummary.trim()) {
        setError('Please fill in at least one log entry field.');
        return;
      }
      if (form.status === 'blocker' && form.supportRequired === 'yes' && !form.supportPerson.trim()) {
        setError('Please specify who support is required from, or set Support Required to No.');
        return;
      }
    }
    setStep((prev) => Math.min(prev + 1, STEPS.length));
  };

  const prevStep = () => {
    setError(null);
    setStep((prev) => Math.max(prev - 1, 1));
  };

  const renderStepIndicator = () => (
    <div className="wizard-progress">
      {STEPS.map((s) => (
        <div
          key={s.id}
          className={`wizard-step-dot ${s.id === step ? 'active' : ''} ${s.id < step ? 'completed' : ''}`}
          onClick={() => s.id < step && setStep(s.id)}
        >
          <div className="wizard-dot">{s.id < step ? '\u2713' : s.id}</div>
          <span className="wizard-step-label">{s.label}</span>
        </div>
      ))}
    </div>
  );

  const renderUserStep = () => (
    <div className="wizard-step-content">
      <h2>Select Engineer</h2>
      <p className="wizard-hint">Who is logging time?</p>
      {loading.users ? (
        <p className="wizard-loading">Loading engineers...</p>
      ) : (
        <WizardDropdown
          value={form.userId}
          onChange={(val) => setFormField('userId', val)}
          options={users.map((u) => ({ value: u.id, label: u.name }))}
          placeholder="-- Select Engineer --"
        />
      )}
      {selectedUser && (
        <div className="wizard-preview-card">
          <div className="wizard-preview-label">Engineer</div>
          <div className="wizard-preview-value">{selectedUser.name}</div>
          <div className="wizard-preview-sub">{selectedUser.email}</div>
        </div>
      )}
    </div>
  );

  const renderProjectStep = () => (
    <div className="wizard-step-content">
      <div className="wizard-step-header-row">
        <h2>Select Project</h2>
        <button
          type="button"
          className="wizard-sync-btn"
          onClick={syncThenFetchProjects}
          disabled={syncingOdoo || loading.projects}
          title="Pull the latest projects and tasks from Odoo (picks up tasks just created there)"
        >
          {syncingOdoo ? 'Syncing from Odoo...' : '\u21bb Sync from Odoo'}
        </button>
      </div>
      <p className="wizard-hint">Which project did you work on?</p>
      {loading.projects ? (
        <p className="wizard-loading">Loading projects...</p>
      ) : (
        <WizardDropdown
          value={form.projectId}
          onChange={(val) => {
            setFormField('projectId', val);
            setFormField('taskId', '');
            setTaskContext(null);
          }}
          options={projects.map((p) => ({ value: p.id, label: p.name }))}
          placeholder="-- Select Project --"
        />
      )}
      {selectedProject && (
        <div className="wizard-preview-card">
          <div className="wizard-preview-label">Project</div>
          <div className="wizard-preview-value">{selectedProject.name}</div>
        </div>
      )}
    </div>
  );

  const renderTaskStep = () => (
    <div className="wizard-step-content">
      <h2>Select Task</h2>
      <p className="wizard-hint">Which task did you work on?</p>
      {!form.projectId ? (
        <p className="wizard-hint">Please select a project first.</p>
      ) : loading.tasks ? (
        <p className="wizard-loading">Loading tasks...</p>
      ) : tasks.length === 0 ? (
        <p className="wizard-hint">No tasks found for this project.</p>
      ) : (
        <div className="wizard-task-table-wrap">
          <table className="wizard-task-table">
            <thead>
              <tr>
                <th className="wizard-task-radio-col"></th>
                <th>Task</th>
                <th>Priority</th>
                <th>Stage</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => {
                const isSelected = String(t.id) === String(form.taskId);
                return (
                  <tr
                    key={t.id}
                    className={`wizard-task-row ${isSelected ? 'selected' : ''}`}
                    onClick={() => {
                      setFormField('taskId', t.id);
                      setTaskContext(null);
                    }}
                  >
                    <td className="wizard-task-radio-cell">
                      <span className={`wizard-task-radio ${isSelected ? 'checked' : ''}`} />
                    </td>
                    <td className="wizard-task-name-cell">{t.name}</td>
                    <td>
                      {t.priority ? (
                        <span className={`wiz-pill wiz-pill-${t.priority.toLowerCase()}`}>
                          {t.priority}
                        </span>
                      ) : '-'}
                    </td>
                    <td>
                      <span className="wiz-pill wiz-pill-stage">{t.stage || 'Unknown'}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {selectedTask && (
        <div className="wizard-preview-card">
          <div className="wizard-preview-label">Task</div>
          <div className="wizard-preview-value">{selectedTask.name}</div>
          <div className="wizard-preview-sub">
            {selectedTask.priority && (
              <span className={`wiz-pill wiz-pill-${selectedTask.priority.toLowerCase()}`}>
                {selectedTask.priority}
              </span>
            )}
            <span className="wiz-pill wiz-pill-stage">{selectedTask.stage || 'Unknown'}</span>
          </div>
        </div>
      )}
    </div>
  );
  const renderActivitySkeleton = () => (
    <div className="wizard-recent-entries wizard-skeleton-block">
      <h3>Recent Activity on This Task</h3>
      <p className="wizard-loading">Loading recent activity&hellip;</p>
      {[1, 2, 3].map((i) => (
        <div key={i} className="wizard-skeleton-entry">
          <div className="wizard-skeleton-line wizard-skeleton-line-sm" />
          <div className="wizard-skeleton-line wizard-skeleton-line-lg" />
        </div>
      ))}
    </div>
  );

  const renderLogDetailsStep = () => (
    <div className="wizard-step-content">
      <h2>What did you do?</h2>
      <p className="wizard-hint">First review recent activity, then tell us the status of this task and answer a few quick questions.</p>

      {loading.activity ? (
        renderActivitySkeleton()
      ) : (
        taskContext && taskContext.recent_timesheets && taskContext.recent_timesheets.length > 0 && (
          <div className="wizard-recent-entries">
            <h3>Recent Activity on This Task</h3>
            {taskContext.recent_timesheets.slice(0, 5).map((ts, i) => (
              <div key={ts.id || i} className="wizard-recent-entry">
                <div className="wiz-recent-head">
                  <strong>{ts.user_name}</strong>
                  <span>{ts.hours}h</span>
                  <span className="wiz-recent-date">{ts.date}</span>
                </div>
                {ts.description && <div className="wiz-recent-desc">{ts.description}</div>}
              </div>
            ))}
          </div>
        )
      )}

      {!loading.activity && (
        <>
          <div className="wizard-status-block">
            <label className="wizard-question-label">
              <span className="wizard-q-icon">&#128203;</span>
              <span>Status of this task:</span>
            </label>
            <div className="wizard-status-options">
              {[
                { value: 'completed', label: 'Completed', icon: '\u2705' },
                { value: 'in_progress', label: 'In Progress', icon: '\u23F3' },
                { value: 'blocker', label: 'Hold / Blocker', icon: '\u26d4' },
              ].map((opt) => (
                <label key={opt.value} className={`wizard-status-radio ${form.status === opt.value ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="taskStatus"
                    checked={form.status === opt.value}
                    onChange={() => handleStatusChange(opt.value)}
                  />
                  <span className="wizard-status-icon">{opt.icon}</span>
                  <span>{opt.label}</span>
                </label>
              ))}
            </div>
          </div>

          {form.status && (
            loading.context ? (
              <p className="wizard-loading">Loading questions...</p>
            ) : taskContext && taskContext.questions ? (
              <>
                <div className="wizard-questions">
                  <div className="wizard-questions-head">
                    <span>A few quick questions</span>
                  </div>
                  {taskContext.questions.map(({ key, label, icon, question }) => (
                    <div key={key} className="wizard-question-block">
                      <label className="wizard-question-label">
                        <span className="wizard-q-icon">{icon}</span>
                        <span>{label}:</span>
                      </label>
                      <div className="wizard-question-prompt">{question}</div>
                      <textarea
                        className="wizard-textarea"
                        rows={3}
                        placeholder="Describe here..."
                        value={form.answers[key] || ''}
                        onChange={(e) => setAnswerField(key, e.target.value)}
                      />
                    </div>
                  ))}
                </div>

                {form.status === 'blocker' && (
                  <div className="wizard-support-block">
                    <label className="wizard-question-label">
                      <span className="wizard-q-icon">&#128308;</span>
                      <span>Support Required?</span>
                    </label>
                    <WizardDropdown
                      value={form.supportRequired}
                      onChange={(val) => setFormField('supportRequired', val)}
                      options={[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]}
                      placeholder="-- Select --"
                    />

                    {form.supportRequired === 'yes' && (
                      <div className="wizard-support-person" ref={supportFieldRef}>
                        <label className="wizard-question-label" style={{marginTop: 12}}>
                          <span className="wizard-q-icon">&#128100;</span>
                          <span>Support Required From:</span>
                        </label>
                        {supportOtherMode ? (
                          <>
                            <input
                              type="text"
                              className="wizard-xwiki-input"
                              placeholder="Type the name..."
                              value={form.supportPerson}
                              onChange={(e) => setFormField('supportPerson', e.target.value)}
                            />
                            <button
                              type="button"
                              className="w-btn w-btn-secondary w-btn-sm"
                              style={{marginTop: 8}}
                              onClick={() => {
                                setSupportOtherMode(false);
                                setFormField('supportPerson', '');
                                setSupportSearchResults([]);
                              }}
                            >
                              Search Odoo instead
                            </button>
                          </>
                        ) : (
                          <>
                            <input
                              type="text"
                              className="wizard-xwiki-input"
                              placeholder="Start typing a name to search Odoo..."
                              value={form.supportPerson}
                              onChange={(e) => handleSupportPersonChange(e.target.value)}
                              onFocus={() => setSupportSearchOpen(true)}
                            />
                            {supportSearchOpen && (
                              <div className="wizard-support-dropdown">
                                {supportSearching ? (
                                  <div className="wizard-support-dropdown-empty">Searching Odoo...</div>
                                ) : (
                                  <>
                                    {supportSearchResults.map((u) => (
                                      <div
                                        key={u.id}
                                        className="wizard-support-dropdown-option"
                                        onClick={() => {
                                          setFormField('supportPerson', u.name);
                                          setSupportSearchOpen(false);
                                        }}
                                      >
                                        <span>{u.name}</span>
                                        {u.email && <span className="wizard-support-dropdown-email">{u.email}</span>}
                                      </div>
                                    ))}
                                    <div
                                      className="wizard-support-dropdown-option"
                                      onClick={() => {
                                        setSupportOtherMode(true);
                                        setSupportSearchOpen(false);
                                        setFormField('supportPerson', '');
                                      }}
                                    >
                                      <span>Others</span>
                                      <span className="wizard-support-dropdown-email">Enter a name manually</span>
                                    </div>
                                  </>
                                )}
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )}

                <div className="wizard-ai-summary-block">
                  <div className="wizard-questions-head">
                    <span>Summary of Today's Work</span>
                    <button
                      className="w-btn w-btn-secondary w-btn-sm"
                      onClick={handleGenerateSummary}
                      disabled={loading.summary}
                    >
                      {loading.summary ? 'Generating...' : 'Generate Summary'}
                    </button>
                  </div>
                  {form.aiSummary && (
                    <textarea
                      className="wizard-textarea wizard-ai-summary-textarea"
                      rows={4}
                      value={form.aiSummary}
                      onChange={(e) => setFormField('aiSummary', e.target.value)}
                    />
                  )}
                  <div className="wizard-custom-prompt">
                    <label className="wizard-question-label" style={{fontSize: 13}}>
                      Optional: steer the summary with your own prompt
                    </label>
                    <input
                      type="text"
                      className="wizard-xwiki-input"
                      placeholder="E.g. Keep it to 2 sentences and emphasize the blocker... (press Enter to regenerate)"
                      value={form.customPrompt}
                      onChange={(e) => setFormField('customPrompt', e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleGenerateSummary();
                        }
                      }}
                    />
                  </div>

                  <label className="wizard-checkbox-label">
                    <input
                      type="checkbox"
                      checked={form.sendEmail}
                      onChange={(e) => setFormField('sendEmail', e.target.checked)}
                    />
                    <span>Email this summary</span>
                  </label>
                  {form.sendEmail && (
                    <input
                      type="text"
                      className="wizard-xwiki-input"
                      placeholder="Recipient email(s), comma-separated"
                      value={form.emailRecipients}
                      onChange={(e) => setFormField('emailRecipients', e.target.value)}
                    />
                  )}
                </div>

                {form.status === 'completed' && (
                  <div className="wizard-complete-block">
                    <label className="wizard-checkbox-label">
                      <input
                        type="checkbox"
                        checked={form.markComplete}
                        onChange={(e) => setFormField('markComplete', e.target.checked)}
                      />
                      <span>Mark this task as completed (updates here and in Odoo)</span>
                    </label>
                  </div>
                )}
              </>
            ) : (
              <p className="wizard-hint">Loading task context...</p>
            )
          )}
        </>
      )}
    </div>
  );

  const renderReviewStep = () => (
    <div className="wizard-step-content">
      <h2>Review & Submit</h2>
      <p className="wizard-hint">Please review your entry before submitting.</p>

      <div className="wizard-review-grid">
        <div className="wizard-review-item">
          <div className="wizard-review-label">Engineer</div>
          <div className="wizard-review-value">{selectedUser?.name || '-'}</div>
        </div>
        <div className="wizard-review-item">
          <div className="wizard-review-label">Project</div>
          <div className="wizard-review-value">{selectedProject?.name || '-'}</div>
        </div>
        <div className="wizard-review-item">
          <div className="wizard-review-label">Task</div>
          <div className="wizard-review-value">{selectedTask?.name || '-'}</div>
        </div>
        <div className="wizard-review-item">
          <div className="wizard-review-label">Hours</div>
          <input
            type="number"
            step="0.25"
            min="0"
            max="24"
            value={form.hours}
            onChange={(e) => setFormField('hours', e.target.value)}
            className="wizard-review-input"
            placeholder="0.0"
          />
        </div>
        <div className="wizard-review-item">
          <div className="wizard-review-label">Date</div>
          <input
            type="date"
            value={form.date}
            onChange={(e) => setFormField('date', e.target.value)}
            className="wizard-review-input"
          />
        </div>
        <div className="wizard-review-item">
          <div className="wizard-review-label">Priority</div>
          <WizardDropdown
            value={form.priority}
            onChange={(val) => setFormField('priority', val)}
            options={[
              { value: 'P1', label: 'P1' },
              { value: 'P2', label: 'P2' },
              { value: 'P3', label: 'P3' },
            ]}
            placeholder="-- Priority --"
          />
        </div>
      </div>

      <div className="wizard-review-log">
        <h3>Log Notes</h3>
        <div className="wizard-review-log-item">
          <div className="wizard-review-log-label">Summary</div>
          <div className="wizard-review-log-text">
            {form.priority ? `[${form.priority}] ` : ''}
            {form.aiSummary || form.userSummary || 'No summary provided yet.'}
          </div>
        </div>
      </div>

      <div className="wizard-review-log">
        {form.markComplete ? (
          <div className="wizard-review-log-item">
            <div className="wizard-review-log-label">Completion Status</div>
            <div className="wizard-review-log-text">
              <span className="wiz-pill wiz-pill-done">Marked Completed (will sync to Odoo)</span>
            </div>
          </div>
        ) : null}
        {form.sendEmail ? (
          <div className="wizard-review-log-item">
            <div className="wizard-review-log-label">Email Summary To</div>
            <div className="wizard-review-log-text">{form.emailRecipients || 'Not specified'}</div>
          </div>
        ) : null}
      </div>

      <div className="wizard-section-divider" />

      <div className="wizard-kb-section">
        <h3>Attach File &amp; Knowledge Base</h3>

        <div className="wizard-file-upload">
          <label className="wizard-question-label">
            <span className="wizard-q-icon">&#128196;</span>
            <span>Attach .md File:</span>
          </label>
          <input
            type="file"
            accept=".md"
            onChange={handleFileSelect}
            className="wizard-file-input"
          />
          {mdFile && (
            <div className="wizard-file-info">
              <span>{mdFile.name}</span>
              <span className="wizard-file-size">{(mdFile.size / 1024).toFixed(1)} KB</span>
            </div>
          )}
        </div>

        <div className="wizard-kb-toggle">
          <label className="wizard-radio-label">
            <input
              type="radio"
              name="kb"
              checked={!kbEnabled}
              onChange={() => setKbEnabled(false)}
            />
            <span>Standard log entry only</span>
          </label>
          <label className="wizard-radio-label">
            <input
              type="radio"
              name="kb"
              checked={kbEnabled}
              onChange={() => setKbEnabled(true)}
            />
            <span>Save to Knowledge Base (XWiki)</span>
          </label>
        </div>

        {kbEnabled && (
          <div className="wizard-xwiki-panel">
            <label className="wizard-checkbox-label" style={{marginBottom: 12}}>
              <input
                type="checkbox"
                checked={kbLocalCopy}
                onChange={(e) => setKbLocalCopy(e.target.checked)}
                disabled={!mdFile}
              />
              <span>Also save a local copy on the backend server{!mdFile ? ' (attach a .md file above first)' : ''}</span>
            </label>

            <div className="wizard-kb-toggle" style={{marginBottom: 12}}>
              <label className="wizard-radio-label">
                <input
                  type="radio"
                  name="xwikiMode"
                  checked={xwikiMode === 'content'}
                  onChange={() => setXwikiMode('content')}
                />
                <span>Convert &amp; save as page content</span>
              </label>
              <label className="wizard-radio-label">
                <input
                  type="radio"
                  name="xwikiMode"
                  checked={xwikiMode === 'attachment'}
                  onChange={() => setXwikiMode('attachment')}
                  disabled={!mdFile}
                />
                <span>Send the .md file itself as an attachment</span>
              </label>
            </div>
            {xwikiMode === 'attachment' && !mdFile && (
              <p className="wizard-hint">Attach a .md file above first to enable this option.</p>
            )}

            <div className="wizard-xwiki-field">
              <label className="wizard-question-label">XWiki Space:</label>
              <input
                type="text"
                value={xwikiSpace}
                onChange={(e) => setXwikiSpace(e.target.value)}
                className="wizard-xwiki-input"
                placeholder="e.g. Projects or Parent.Child"
              />
            </div>
            <div className="wizard-xwiki-field">
              <label className="wizard-question-label">Page Name:</label>
              <input
                type="text"
                value={xwikiPage}
                onChange={(e) => setXwikiPage(e.target.value)}
                className="wizard-xwiki-input"
                placeholder="Auto-generated from task name"
              />
            </div>

            {xwikiMode === 'attachment' ? (
              <>
                <div className="wizard-xwiki-actions">
                  <button
                    className="w-btn w-btn-secondary"
                    onClick={handleFetchXWiki}
                    disabled={loading.xwiki}
                  >
                    {loading.xwiki ? 'Fetching...' : 'Check Page'}
                  </button>
                </div>
                {xwikiPageData && (
                  <div className="wizard-xwiki-info">
                    {xwikiPageData.exists
                      ? <span className="wiz-xwiki-badge exists">Page exists (v{xwikiPageData.version})</span>
                      : <span className="wiz-xwiki-badge new">New page will be created</span>
                    }
                    <div className="wizard-xwiki-title-label">Title: {xwikiPageData.title || selectedTask?.name}</div>
                  </div>
                )}
                {mdFile && (
                  <div className="wizard-file-info">
                    <span>Will attach: {mdFile.name}</span>
                    <span className="wizard-file-size">{(mdFile.size / 1024).toFixed(1)} KB</span>
                  </div>
                )}
                <p className="wizard-hint" style={{marginTop: 6}}>
                  The file is sent to XWiki exactly as uploaded, as a real attachment on the page — it is not converted or reformatted.
                </p>
              </>
            ) : (
              <>
                <div className="wizard-xwiki-actions">
                  <button
                    className="w-btn w-btn-secondary"
                    onClick={handleFetchXWiki}
                    disabled={loading.xwiki}
                  >
                    {loading.xwiki ? 'Fetching...' : 'Fetch Current Page'}
                  </button>
                  {mdFileContent && (
                    <button
                      className="w-btn w-btn-secondary"
                      onClick={handleConvertMd}
                      disabled={loading.convert}
                    >
                      {loading.convert ? 'Converting...' : 'Convert .md to XWiki'}
                    </button>
                  )}
                </div>

                {xwikiPageData && (
                  <div className="wizard-xwiki-info">
                    {xwikiPageData.exists
                      ? <span className="wiz-xwiki-badge exists">Page exists (v{xwikiPageData.version})</span>
                      : <span className="wiz-xwiki-badge new">New page will be created</span>
                    }
                    <div className="wizard-xwiki-title-label">Title: {xwikiPageData.title || selectedTask?.name}</div>
                  </div>
                )}

                <div className="wizard-xwiki-field">
                  <label className="wizard-question-label">XWiki Content:</label>
                  <textarea
                    className="wizard-textarea wizard-xwiki-textarea"
                    rows={10}
                    value={xwikiContent}
                    onChange={(e) => setXwikiContent(e.target.value)}
                    placeholder="XWiki-formatted content will appear here after conversion or fetch..."
                  />
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {success && <div className="wizard-success">{success}</div>}
    </div>
  );

  const renderStep = () => {
    switch (step) {
      case 1: return renderUserStep();
      case 2: return renderProjectStep();
      case 3: return renderTaskStep();
      case 4: return renderLogDetailsStep();
      case 5: return renderReviewStep();
      default: return null;
    }
  };

  return (
    <div className="wizard-container">
      <div className="wizard-card">
        <h1 className="wizard-title">Log Work</h1>
        {renderStepIndicator()}
        {error && <div className="wizard-error">{error}</div>}
        {renderStep()}
        <div className="wizard-nav">
          {step > 1 && (
            <button className="w-btn w-btn-secondary" onClick={prevStep} disabled={loading.submit}>
              Back
            </button>
          )}
          <div className="wizard-nav-spacer" />
          {step < STEPS.length ? (
            <button className="w-btn w-btn-primary" onClick={nextStep} disabled={loading.submit}>
              Next
            </button>
          ) : (
            <button className="w-btn w-btn-success" onClick={handleSubmit} disabled={loading.submit}>
              {loading.submit ? 'Submitting...' : 'Submit'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default TaskWizard;