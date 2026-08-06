"""
Business logic and services for report generation
"""
import xmlrpc.client
import requests
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from app import db
from models import User, Project, Task, Timesheet, Report, TaskSummary, ReportAnalytics
import os
import yaml
import html as html_mod
from alerting import AlertService

from report_generator import (
    calculate_shift_metrics,
    normalize_stage_bucket,
    get_priority_label,
    calculate_age,
    build_user_task_summary,
    build_task_log_summaries,
    build_top_projects_summary_html,
    generate_project_bubble_chart_html,
    generate_projects_tasks_gantt_html,
    generate_project_criticality_heatmap_html,
    generate_per_user_gantt_charts,
    generate_user_page_html,
    generate_team_overview_page_html,
    generate_html_report,
    generate_project_html_report,
)

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with multiple LLM providers (OpenAI-compatible APIs).

    Supports both the new multi-service config format:
        llm:
          provider: "ollama"
          services:
            digital_ocean: { api_url, model, api_key, max_tokens }
            ollama:        { api_url, model, api_key, max_tokens }

    And the legacy flat format:
        llm:
          api_url: "..."
          model: "..."
          api_key: "..."
          max_tokens: 2000
    """

    def __init__(self, config_path='config.yaml', service_name=None):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        self._parse_llm_config(config.get('llm', {}))
        self.service_name = service_name  # override the default provider

    def _parse_llm_config(self, llm_cfg):
        services = llm_cfg.get('services')
        if services:
            self.services = {}
            for name, svc in services.items():
                self.services[name] = {
                    'api_url': svc.get('api_url', ''),
                    'model': svc.get('model', ''),
                    'api_key': svc.get('api_key', ''),
                    'max_tokens': svc.get('max_tokens', 2000),
                }
            self.default_service = llm_cfg.get(
                'provider',
                next(iter(self.services)) if self.services else None,
            )
        else:
            self.services = {
                'default': {
                    'api_url': llm_cfg.get('api_url', ''),
                    'model': llm_cfg.get('model', ''),
                    'api_key': llm_cfg.get('api_key', ''),
                    'max_tokens': llm_cfg.get('max_tokens', 2000),
                },
            }
            self.default_service = 'default'

    def get_service(self, name=None):
        name = name or self.service_name or self.default_service
        return self.services.get(name)

    def call(self, prompt, system_prompt=None, service_name=None, max_tokens=None, timeout=120):
        svc = self.get_service(service_name)
        if not svc:
            raise ValueError(
                f"LLM service '{service_name or self.service_name or self.default_service}' "
                f"not configured. Available: {list(self.services)}"
            )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if svc['api_key']:
            headers["Authorization"] = f"Bearer {svc['api_key']}"

        # Use a short connect-timeout (5s) so an unreachable host (e.g. a
        # dead/moved Ollama instance) fails fast, while still allowing the
        # full `timeout` for the actual model inference (read timeout) once
        # a connection is established.
        resp = requests.post(
            svc['api_url'],
            json={
                "model": svc['model'],
                "messages": messages,
                "max_tokens": max_tokens or svc['max_tokens'],
            },
            headers=headers,
            timeout=(5, timeout),
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


# Status keys used across the wizard. Each status has its own fixed set of
# basic questions (what / why / how / when / next steps / describe your
# blocker / anything else). These are static and intentionally NOT tailored
# to recent activity or an LLM -- they only vary by the status the engineer
# picked, so the same question set shows every time for a given status.
STATUS_QUESTION_DEFAULTS = {
    'completed': [
        {'key': 'what', 'label': 'What', 'icon': '\u2699',
         'fallback': 'What did you do?'},
        {'key': 'why', 'label': 'Why', 'icon': '\u2753',
         'fallback': 'Why was this work needed?'},
        {'key': 'how', 'label': 'How', 'icon': '\u2728',
         'fallback': 'How did you do it?'},
        {'key': 'when', 'label': 'When', 'icon': '\U0001f4c5',
         'fallback': 'When was it completed?'},
        {'key': 'anything_else', 'label': 'Anything Else', 'icon': '\U0001f4dd',
         'fallback': 'Anything else worth noting?'},
    ],
    'in_progress': [
        {'key': 'what', 'label': 'What', 'icon': '\u2699',
         'fallback': 'What did you do?'},
        {'key': 'why', 'label': 'Why', 'icon': '\u2753',
         'fallback': 'Why is this work needed?'},
        {'key': 'how', 'label': 'How', 'icon': '\u2728',
         'fallback': 'How did you do it?'},
        {'key': 'next_steps', 'label': 'Next Steps', 'icon': '\u27a1',
         'fallback': 'What are the next steps?'},
        {'key': 'anything_else', 'label': 'Anything Else', 'icon': '\U0001f4dd',
         'fallback': 'Anything else worth noting?'},
    ],
    'blocker': [
        {'key': 'what', 'label': 'What', 'icon': '\u2699',
         'fallback': 'What did you do?'},
        {'key': 'why', 'label': 'Why', 'icon': '\u2753',
         'fallback': 'Why is this task blocked?'},
        {'key': 'how', 'label': 'How', 'icon': '\u2728',
         'fallback': 'How did you try to resolve it?'},
        {'key': 'describe_blocker', 'label': 'Describe Your Blocker', 'icon': '\u26d4',
         'fallback': 'Describe your blocker.'},
        {'key': 'next_steps', 'label': 'Next Steps', 'icon': '\u27a1',
         'fallback': 'What is needed to unblock this, and what are the next steps?'},
        {'key': 'anything_else', 'label': 'Anything Else', 'icon': '\U0001f4dd',
         'fallback': 'Anything else worth noting?'},
    ],
}

STATUS_LABELS = {
    'completed': 'Completed',
    'in_progress': 'In Progress',
    'blocker': 'Hold / Blocker',
}


def normalize_status(status):
    status = (status or '').strip().lower().replace('-', '_').replace(' ', '_')
    if status in ('hold', 'blocked', 'blocker', 'on_hold'):
        return 'blocker'
    if status in ('in_progress', 'inprogress', 'progress'):
        return 'in_progress'
    if status in ('completed', 'complete', 'done'):
        return 'completed'
    return 'in_progress'


def generate_task_context_questions(status=None, **_ignored):
    """Return the fixed, basic set of log-detail questions for the given task
    status (completed / in_progress / blocker). These are always the same
    static what / why / how / when / next-steps / describe-your-blocker /
    anything-else questions for a given status -- they do NOT depend on
    recent activity, the engineer's summary, or any LLM call. Any extra
    kwargs (e.g. task_name, log_entries, user_summary) are accepted for
    backwards compatibility but ignored.
    """
    status = normalize_status(status)
    defaults = STATUS_QUESTION_DEFAULTS[status]
    return [
        {'key': d['key'], 'label': d['label'], 'icon': d['icon'], 'question': d['fallback']}
        for d in defaults
    ]


def generate_task_summary(task_name, task_description, status, log_entries, user_summary='',
                            answers=None, custom_prompt='', priority=None, max_logs=10):
    """Generate an AI summary of the work logged, based on recent activity plus the
    engineer's answers to the status-specific questions. Optionally steered by a
    free-form custom_prompt from the user. Prepends a [P1]/[P2]/[P3] priority tag
    when priority is given.
    """
    status = normalize_status(status)
    status_label = STATUS_LABELS[status]
    answers = answers or {}

    combined_logs = "\n".join(log_entries[:max_logs]) if log_entries else "No recent log entries."
    answer_lines = "\n".join(f"- {k}: {v}" for k, v in answers.items() if v)
    user_note = f"\nEngineer's own summary:\n{user_summary}" if user_summary else ""
    custom_note = f"\nAdditional instructions from the engineer for this summary:\n{custom_prompt}" if custom_prompt else ""

    prompt = f"""You are a project management assistant. Write a concise, clear daily work-log summary
for the following task, suitable for a status report.

Task: "{task_name}"
Description: {task_description or "No description provided"}
Status: {status_label}

Recent log entries on this task:
{combined_logs}{user_note}

Engineer's answers to today's log questions:
{answer_lines or "None provided"}{custom_note}

Write a 3-5 sentence summary in a professional tone covering what was done, current status, and (if blocked) what's needed to move forward. Do not repeat the raw Q&A verbatim; synthesize it. Respond with the summary text only, no headers or preamble."""

    try:
        llm = LLMService()
        content = llm.call(prompt, timeout=60)
    except Exception as e:
        logger.warning(f"LLM summary generation failed: {e}")
        parts = [user_summary] + [v for v in answers.values() if v]
        content = " ".join(p.strip() for p in parts if p.strip()) or "No summary available."

    if priority:
        content = f"[{priority}] {content}"

    return content

# Bug tracker: fixed set of probing questions per category. Static and
# intentionally not LLM-generated -- same question set every time for a
# given category, mirroring STATUS_QUESTION_DEFAULTS above.
BUG_CATEGORY_QUESTIONS = {
    'general': [
        {'key': 'summary', 'label': 'What is the issue?', 'icon': '\u2753',
         'placeholder': 'Briefly describe what you ran into...'},
        {'key': 'when_noticed', 'label': 'When did you notice it?', 'icon': '\U0001f4c5',
         'placeholder': 'e.g. Today while logging work, after the last deploy...'},
        {'key': 'frequency', 'label': 'How often does it happen?', 'icon': '\U0001f501',
         'placeholder': 'Always / sometimes / once so far...'},
        {'key': 'impact', 'label': 'What is the impact?', 'icon': '\u26a0',
         'placeholder': 'Who or what is affected by this?'},
    ],
    'bug': [
        {'key': 'expected_behavior', 'label': 'Expected behavior', 'icon': '\u2705',
         'placeholder': 'What should have happened?'},
        {'key': 'actual_behavior', 'label': 'Actual behavior', 'icon': '\u274c',
         'placeholder': 'What actually happened instead?'},
        {'key': 'environment', 'label': 'Environment / version', 'icon': '\U0001f5a5',
         'placeholder': 'Browser, OS, module/service version, container tag...'},
        {'key': 'error_logs', 'label': 'Error messages / logs', 'icon': '\U0001f4cb',
         'placeholder': 'Paste any relevant error text or stack trace...'},
    ],
    'feature': [
        {'key': 'feature_summary', 'label': 'What feature are you requesting?', 'icon': '\U0001f4a1',
         'placeholder': 'Describe the feature or capability...'},
        {'key': 'problem_solved', 'label': 'What problem does it solve?', 'icon': '\U0001f9e9',
         'placeholder': 'What is difficult or impossible today without it?'},
        {'key': 'who_benefits', 'label': 'Who benefits from this?', 'icon': '\U0001f465',
         'placeholder': 'Which users/teams/workflows would this help?'},
        {'key': 'priority_reason', 'label': 'How urgent is this?', 'icon': '\u23f1',
         'placeholder': 'Nice-to-have, or blocking something important?'},
    ],
    'observation': [
        {'key': 'what_observed', 'label': 'What did you observe?', 'icon': '\U0001f441',
         'placeholder': 'Describe what you noticed...'},
        {'key': 'where_observed', 'label': 'Where (module / page / component)?', 'icon': '\U0001f4cd',
         'placeholder': 'e.g. OSDBcortex dashboard, query planner, ingestion pipeline...'},
        {'key': 'is_risk', 'label': 'Is this a risk if left unaddressed?', 'icon': '\u26a0',
         'placeholder': 'What could happen if this is not looked into?'},
        {'key': 'suggested_action', 'label': 'Suggested next step (optional)', 'icon': '\u27a1',
         'placeholder': 'Anything you think should be done about it?'},
    ],
}

BUG_CATEGORY_LABELS = {
    'general': 'General Issue',
    'bug': 'Code Bug',
    'feature': 'Feature Request',
    'observation': 'Observation',
}


def generate_bug_probing_questions(category):
    """Return the fixed set of probing questions for a bug-tracker category."""
    category = (category or '').strip().lower()
    if category not in BUG_CATEGORY_QUESTIONS:
        category = 'general'
    return [dict(q) for q in BUG_CATEGORY_QUESTIONS[category]]


# Fixed, per-status follow-up fields shown when a bug report's status is
# changed. Mirrors BUG_CATEGORY_QUESTIONS above -- same fields every time for
# a given status, not LLM-generated. 'open' has none: reopening a report
# needs no extra context.
STATUS_UPDATE_FIELDS = {
    'open': [],
    'in_progress': [
        {'key': 'progress_notes', 'label': "What's being worked on?", 'icon': '\U0001f6e0',
         'placeholder': 'Briefly describe the current approach or progress...', 'required': True},
        {'key': 'eta', 'label': 'Estimated completion (optional)', 'icon': '\u23f1',
         'placeholder': 'e.g. End of day, tomorrow, next sprint...', 'required': False},
    ],
    'resolved': [
        {'key': 'resolution_details', 'label': 'Resolution details', 'icon': '\u2705',
         'placeholder': 'What was done to resolve this?', 'required': True},
    ],
    'closed': [
        {'key': 'reason', 'label': 'Reason for closing', 'icon': '\U0001f512',
         'placeholder': "Why is this being closed (e.g. duplicate, won't fix, not reproducible)?",
         'required': True},
    ],
}

STATUS_LABELS = {
    'open': 'Open',
    'in_progress': 'In Progress',
    'resolved': 'Resolved',
    'closed': 'Closed',
}


def generate_status_update_fields(status):
    """Return the fixed set of follow-up fields for a bug-tracker status change."""
    status = (status or '').strip().lower()
    if status not in STATUS_UPDATE_FIELDS:
        return []
    return [dict(f) for f in STATUS_UPDATE_FIELDS[status]]


# Fixed team rosters for the "Assign Task to a Team" section shown below the
# 4 bug-tracker categories. Update the email addresses here to match your
# real company domain/addresses -- these are used as the default recipients
# when a user checks "send email" while assigning a task to a team.
TEAM_DEFINITIONS = {
    'team1': {
        'label': 'Team 1',
        'members': [
            {'name': 'Lahari', 'email': 'lahari@yourcompany.com'},
            {'name': 'Lokesh', 'email': 'lokesh@yourcompany.com'},
            {'name': 'Swarna Teja', 'email': 'swarnateja@yourcompany.com'},
        ],
    },
    'team2': {
        'label': 'Team 2',
        'members': [
            {'name': 'Shameer', 'email': 'shameer@yourcompany.com'},
            {'name': 'Chandini', 'email': 'chandini@yourcompany.com'},
            {'name': 'Venkata Krishna', 'email': 'venkatakrishna@yourcompany.com'},
        ],
    },
    'team3': {
        'label': 'Team 3',
        'members': [
            {'name': 'Keerthi', 'email': 'keerthi@yourcompany.com'},
            {'name': 'Kushwanth', 'email': 'kushwanth@yourcompany.com'},
            {'name': 'Vaishnavi', 'email': 'vaishnavi@yourcompany.com'},
        ],
    },
}


def get_team_definitions():
    """Return the fixed team roster list for the bug-tracker task assignment UI."""
    return [
        {'key': key, 'label': team['label'], 'members': team['members']}
        for key, team in TEAM_DEFINITIONS.items()
    ]


def get_team_member_emails(team_key):
    """Return the list of member email addresses for a given team key."""
    team = TEAM_DEFINITIONS.get(team_key)
    if not team:
        return []
    return [m['email'] for m in team['members']]


class OdooService:
    """Service to interact with Odoo"""
    
    def __init__(self, config_path='config.yaml'):
        """Initialize Odoo connection parameters"""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        self.odoo_url = config.get('odoo', {}).get('url')
        self.odoo_db = config.get('odoo', {}).get('db')
        self.odoo_user = config.get('odoo', {}).get('user')
        self.odoo_pass = config.get('odoo', {}).get('password')
        
        self.llm = LLMService(config_path)
        self.excluded_users = config.get('report', {}).get('excluded_users', [])
        self.shift_hours = float(config.get('report', {}).get('shift_hours', 8.3))
    
    def connect(self):
        """Establish Odoo connection"""
        try:
            common = xmlrpc.client.ServerProxy(f"{self.odoo_url}/xmlrpc/2/common")
            uid = common.authenticate(self.odoo_db, self.odoo_user, self.odoo_pass, {})
            if not uid:
                raise Exception("Odoo authentication failed")
            models = xmlrpc.client.ServerProxy(f"{self.odoo_url}/xmlrpc/2/object")
            return uid, models
        except Exception as e:
            logger.error(f"Error connecting to Odoo: {e}")
            raise
    
    def fetch_users(self, models, uid):
        """Fetch users from Odoo"""
        try:
            user_ids = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "res.users", "search", [[("share", "=", False)]]
            )
            users = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "res.users", "read", [user_ids],
                {"fields": ["id", "name", "email"]}
            )
            return {u["id"]: u for u in users}
        except Exception as e:
            logger.error(f"Error fetching users from Odoo: {e}")
            raise
    
    def fetch_recent_timesheets(self, models, uid, hours=24):
        """Fetch recent timesheet entries"""
        try:
            now = datetime.now()
            since = now - timedelta(hours=hours)
            
            timesheet_ids = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "account.analytic.line", "search", [[
                    ("date", ">=", since.strftime("%Y-%m-%d")),
                    ("date", "<=", now.strftime("%Y-%m-%d")),
                ]]
            )
            timesheets = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "account.analytic.line", "read", [timesheet_ids],
                {"fields": ["id", "name", "unit_amount", "date", "user_id", "project_id", "task_id"]}
            )
            return timesheets
        except Exception as e:
            logger.error(f"Error fetching timesheets: {e}")
            raise
    
    def fetch_tasks(self, models, uid, task_ids):
        """Fetch task details"""
        if not task_ids:
            return []
        try:
            tasks = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "read", [list(set(task_ids))],
                {"fields": ["id", "name", "description", "project_id", "priority", "stage_id"]}
            )
            return tasks
        except Exception as e:
            logger.error(f"Error fetching tasks: {e}")
            raise

    def fetch_all_projects_and_tasks(self, models, uid):
        """Fetch every active project and task directly from Odoo.

        Unlike fetch_tasks()/fetch_recent_timesheets(), this is NOT limited to
        whatever happens to already have a timesheet entry. It's what keeps
        the local Project/Task tables (and therefore the Log Work project ->
        task dropdowns) in sync with Odoo the moment a task is created there,
        even before anyone has logged time against it.
        """
        try:
            project_ids = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.project", "search", [[("active", "=", True)]]
            )
            projects = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.project", "read", [project_ids],
                {"fields": ["id", "name"]}
            )

            task_ids = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "search", [[("active", "=", True), ("project_id", "!=", False)]]
            )
            tasks = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "read", [task_ids],
                {"fields": ["id", "name", "description", "project_id", "priority", "stage_id"]}
            )
            return projects, tasks
        except Exception as e:
            logger.error(f"Error fetching all projects/tasks from Odoo: {e}")
            raise
    
    def search_users(self, query, limit=10):
        """Live-search Odoo res.users by name/email for the 'support required from' typeahead."""
        if not query or len(query.strip()) < 2:
            return []
        try:
            uid, models = self.connect()
            domain = [
                '&', ('share', '=', False),
                '|', ('name', 'ilike', query), ('email', 'ilike', query),
            ]
            user_ids = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "res.users", "search", [domain], {"limit": limit}
            )
            if not user_ids:
                return []
            users = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "res.users", "read", [user_ids],
                {"fields": ["id", "name", "email"]}
            )
            return users
        except Exception as e:
            logger.error(f"Error searching Odoo users: {e}")
            return []

    def mark_task_done(self, odoo_task_id):
        """Move a project.task to its project's 'Done'/'Closed'-like stage in Odoo.
        Returns (success, message_or_stage_name).
        """
        try:
            uid, models = self.connect()
            task_data = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "read", [[odoo_task_id]],
                {"fields": ["id", "project_id", "stage_id"]}
            )
            if not task_data:
                return False, "Task not found in Odoo"
            project_id = task_data[0].get('project_id')
            if not project_id:
                return False, "Task has no project in Odoo"
            project_id = project_id[0] if isinstance(project_id, list) else project_id

            stage_ids = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task.type", "search",
                [[('project_ids', 'in', [project_id])]]
            )
            if not stage_ids:
                return False, "No stages found for project"
            stages = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task.type", "read", [stage_ids],
                {"fields": ["id", "name", "fold", "sequence"]}
            )
            done_stage = None
            for s in sorted(stages, key=lambda x: x.get('sequence', 0)):
                name = (s.get('name') or '').lower()
                if 'done' in name or 'closed' in name or 'complete' in name:
                    done_stage = s
                    break
            if not done_stage:
                # fall back to the last (highest-sequence) folded stage, a common
                # Odoo convention for a "done" kanban column
                folded = [s for s in stages if s.get('fold')]
                if folded:
                    done_stage = sorted(folded, key=lambda x: x.get('sequence', 0))[-1]
            if not done_stage:
                return False, "Could not determine a 'Done' stage for this project"

            models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "write", [[odoo_task_id], {'stage_id': done_stage['id']}]
            )
            logger.info(f"Marked Odoo task {odoo_task_id} as done (stage={done_stage['name']})")
            return True, done_stage['name']
        except Exception as e:
            logger.error(f"Failed to mark task {odoo_task_id} done in Odoo: {e}")
            return False, str(e)

    def summarize_with_llm(self, task_description, log_entries):
        """Generate LLM-based task summary"""
        try:
            combined_logs = "\n".join(log_entries[:10])
            
            prompt = f"""
You are a project management analyst. Summarize the following task.

Task Description:
{task_description or "No description provided"}

Log Entries:
{combined_logs}

Provide a concise 2-3 sentence summary.
"""
            content = self.llm.call(prompt, timeout=120)
            return content
        except Exception as e:
            logger.error(f"LLM summary error: {e}")
            return f"Summary unavailable: {str(e)}"

    def create_timesheet(self, user_id, task_id, hours, description, date, log_note=None):
        """Push a timesheet entry to Odoo and optionally post a verbose log note on the task.
        Returns (success, odoo_ts_id_or_error).
        """
        try:
            uid, models = self.connect()
            odoo_ts_id = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "account.analytic.line", "create", [{
                    'name': description[:200] if description else '',
                    'unit_amount': float(hours),
                    'date': date.isoformat() if hasattr(date, 'isoformat') else str(date),
                    'user_id': user_id,
                    'task_id': task_id,
                }]
            )
            logger.info(f"Created timesheet {odoo_ts_id} in Odoo")

            if log_note:
                try:
                    html_body = log_note.replace('\n', '<br/>')
                    models.execute_kw(
                        self.odoo_db, uid, self.odoo_pass,
                        "project.task", "message_post",
                        [task_id],
                        {'body': html_body, 'message_type': 'comment', 'subtype_id': 1}
                    )
                    logger.info(f"Posted log note on task {task_id}")
                except Exception as note_err:
                    logger.warning(f"Failed to post log note on task {task_id}: {note_err}")

            return True, odoo_ts_id
        except Exception as e:
            logger.error(f"Failed to push timesheet to Odoo: {e}")
            try:
                AlertService().notify(
                    subject="Odoo Automation: Timesheet push failed",
                    message=f"user_id={user_id}, task_id={task_id}, hours={hours}\nError: {e}"
                )
            except Exception as alert_err:
                logger.error(f"Alerting itself failed: {alert_err}")
            return False, str(e)

    def find_or_create_project(self, models, uid, project_name):
        """Find an Odoo project.project by name (case-insensitive substring
        match, including archived projects). Raises a clear error instead of
        attempting to auto-create one, since the service account isn't
        granted Project-creation rights in Odoo -- if this project is
        missing or unreachable, that needs fixing in Odoo (name/visibility/
        archived state), not by silently creating a duplicate."""
        project_ids = models.execute_kw(
            self.odoo_db, uid, self.odoo_pass,
            "project.project", "search",
            [[('name', 'ilike', project_name)]],
            {"limit": 1, "context": {"active_test": False}}
        )
        if project_ids:
            return project_ids[0]
        raise Exception(
            f"No Odoo project found matching '{project_name}'. Check the exact "
            f"name/spelling in Odoo's Project app, that it isn't archived, and "
            f"that the service account has visibility on it (Project > Settings > "
            f"add the service account as a member/follower, or set visibility to "
            f"'All internal users')."
        )

    def create_bug_task(self, project_name, title, description, priority=None, category=None):
        """Create a project.task in Odoo under `project_name` (creating the
        project if needed) to represent a bug-tracker submission.
        Returns (success, odoo_task_id_or_error).
        """
        try:
            uid, models = self.connect()
            project_id = self.find_or_create_project(models, uid, project_name)

            # Odoo project.task priority is a selection: '0' normal, '1' starred/high
            odoo_priority = '1' if (priority or '').lower() in ('critical', 'high') else '0'

            tag_ids = []
            if category:
                tag_ids.append(self._find_or_create_tag(models, uid, BUG_CATEGORY_LABELS.get(category, category)))
            # Every bug task starts life Open -- tag it accordingly so the
            # status is visible directly on the Odoo kanban card, in sync
            # with the local bug tracker.
            tag_ids.append(self._find_or_create_tag(models, uid, f"Status: {STATUS_LABELS['open']}"))

            task_id = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "create", [{
                    'name': title[:255],
                    'description': description or '',
                    'project_id': project_id,
                    'priority': odoo_priority,
                    'tag_ids': [(6, 0, tag_ids)],
                }]
            )
            logger.info(f"Created Odoo bug task {task_id} in project '{project_name}'")
            return True, task_id
        except Exception as e:
            logger.error(f"Failed to create Odoo bug task: {e}")
            return False, str(e)

    def attach_file_to_task(self, task_id, filename, content_b64, mimetype=None):
        """Attach a base64-encoded file to an existing project.task in Odoo
        via ir.attachment. Returns (success, attachment_id_or_error)."""
        try:
            uid, models = self.connect()
            attachment_id = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "ir.attachment", "create", [{
                    'name': filename,
                    'datas': content_b64,
                    'res_model': 'project.task',
                    'res_id': task_id,
                    'mimetype': mimetype or 'application/octet-stream',
                }]
            )
            logger.info(f"Attached '{filename}' to Odoo task {task_id} (attachment_id={attachment_id})")
            return True, attachment_id
        except Exception as e:
            logger.error(f"Failed to attach '{filename}' to Odoo task {task_id}: {e}")
            return False, str(e)

    def fetch_task_attachments(self, task_id):
        """Fetch every ir.attachment linked to a project.task in Odoo,
        including its actual file content, so bug-tracker attachments that
        were pushed to Odoo before this app stored file bytes locally can
        be recovered. Returns a list of dicts (creation order), each with
        odoo_attachment_id, filename, mimetype, content_b64. Returns an
        empty list (rather than raising) on any failure, since this is a
        best-effort recovery path.
        """
        try:
            uid, models = self.connect()
            attachment_ids = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "ir.attachment", "search",
                [[["res_model", "=", "project.task"], ["res_id", "=", task_id]]],
                {"order": "id asc"}
            )
            if not attachment_ids:
                return []
            records = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "ir.attachment", "read", [attachment_ids],
                {"fields": ["name", "datas", "mimetype"]}
            )
            # Odoo doesn't guarantee read() preserves the id order we asked
            # for, so re-sort explicitly to keep "creation order" meaningful
            # for the filename-matching done during backfill.
            records.sort(key=lambda r: r['id'])
            return [
                {
                    'odoo_attachment_id': r['id'],
                    'filename': r.get('name') or 'attachment',
                    'mimetype': r.get('mimetype') or 'application/octet-stream',
                    'content_b64': r.get('datas') or '',
                }
                for r in records
            ]
        except Exception as e:
            logger.error(f"Failed to fetch attachments for Odoo task {task_id}: {e}")
            return []

    def _find_or_create_tag(self, models, uid, tag_name):
        """Find a project.tags record by exact name, creating it if it
        doesn't exist yet. Returns the tag's Odoo id."""
        tag_ids = models.execute_kw(
            self.odoo_db, uid, self.odoo_pass,
            "project.tags", "search", [[('name', '=', tag_name)]], {"limit": 1}
        )
        if tag_ids:
            return tag_ids[0]
        return models.execute_kw(
            self.odoo_db, uid, self.odoo_pass,
            "project.tags", "create", [{'name': tag_name}]
        )

    def _post_note(self, models, uid, task_id, html_body):
        """Post a chatter note on a project.task. Best-effort -- returns
        True/False rather than raising, since a failed note shouldn't block
        the rest of a status sync."""
        try:
            models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "message_post",
                [task_id],
                {'body': html_body, 'message_type': 'comment', 'subtype_id': 1}
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to post note on Odoo task {task_id}: {e}")
            return False

    def sync_bug_status(self, task_id, status, note_html=None):
        """Sync a bug-tracker status change onto its Odoo task: replaces any
        existing 'Status: ...' tag with one matching the new status (leaving
        other tags, like the category tag, untouched) and optionally posts a
        chatter note with the status-specific fields the user filled in.
        Returns (success, message_or_error).
        """
        try:
            uid, models = self.connect()
            task_data = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "read", [[task_id]], {"fields": ["tag_ids"]}
            )
            if not task_data:
                return False, "Task not found in Odoo"

            current_tag_ids = task_data[0].get('tag_ids') or []
            existing_tags = models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.tags", "read", [current_tag_ids], {"fields": ["id", "name"]}
            ) if current_tag_ids else []

            kept_ids = [t['id'] for t in existing_tags if not t['name'].startswith('Status: ')]
            new_tag_name = f"Status: {STATUS_LABELS.get(status, status.title())}"
            new_tag_id = self._find_or_create_tag(models, uid, new_tag_name)

            models.execute_kw(
                self.odoo_db, uid, self.odoo_pass,
                "project.task", "write", [[task_id], {'tag_ids': [(6, 0, kept_ids + [new_tag_id])]}]
            )

            if note_html:
                self._post_note(models, uid, task_id, note_html)

            logger.info(f"Synced status tag '{new_tag_name}' on Odoo task {task_id}")
            return True, new_tag_name
        except Exception as e:
            logger.error(f"Failed to sync bug status on Odoo task {task_id}: {e}")
            return False, str(e)

class ReportGenerationService:
    """Service to generate and store reports"""
    
    @staticmethod
    def sync_odoo_data(hours=24):
        """Sync Odoo data (users, projects, tasks, timesheets) to local database"""
        try:
            odoo_service = OdooService()
            uid, models = odoo_service.connect()

            # ── Sync Users ──
            odoo_users = odoo_service.fetch_users(models, uid)
            user_map = {}  # odoo_user_id -> local User
            for odoo_id, user_data in odoo_users.items():
                if user_data['name'] in odoo_service.excluded_users:
                    continue
                user = User.query.filter_by(odoo_user_id=odoo_id).first()
                if not user:
                    user = User(
                        odoo_user_id=odoo_id,
                        name=user_data['name'],
                        email=user_data.get('email', ''),
                        role='employee',
                    )
                    db.session.add(user)
                    db.session.flush()
                user_map[odoo_id] = user
            db.session.commit()
            logger.info(f"Synced {len(odoo_users)} users from Odoo")

            # ── Sync ALL Projects and Tasks (not just ones that already have
            # a timesheet entry) so newly-created Odoo tasks show up in the
            # Log Work project/task pickers right away. ──
            odoo_projects, odoo_tasks = odoo_service.fetch_all_projects_and_tasks(models, uid)
            logger.info(f"Fetched {len(odoo_projects)} projects and {len(odoo_tasks)} tasks from Odoo")

            # Sync Projects
            project_map = {}  # odoo_project_id -> local Project
            for p in odoo_projects:
                odoo_pid = p['id']
                proj = Project.query.filter_by(odoo_project_id=odoo_pid).first()
                if not proj:
                    proj = Project(
                        odoo_project_id=odoo_pid,
                        name=p.get('name', 'Unknown Project'),
                    )
                    db.session.add(proj)
                    db.session.flush()
                else:
                    proj.name = p.get('name', proj.name)
                project_map[odoo_pid] = proj
            db.session.commit()
            logger.info(f"Synced {len(odoo_projects)} projects from Odoo")

            # Sync Tasks
            task_map = {}  # odoo_task_id -> local Task
            if odoo_tasks:
                stage_ids = set()
                for t in odoo_tasks:
                    if t.get('stage_id'):
                        stage_ids.add(t['stage_id'][0] if isinstance(t['stage_id'], list) else t['stage_id'])
                stage_map = {}
                if stage_ids:
                    stages = models.execute_kw(
                        odoo_service.odoo_db, uid, odoo_service.odoo_pass,
                        "project.task.type", "read", [list(stage_ids)],
                        {"fields": ["id", "name"]}
                    )
                    stage_map = {s['id']: s['name'] for s in stages}

                for t in odoo_tasks:
                    odoo_tid = t['id']
                    project_id = t.get('project_id')
                    if not project_id:
                        continue
                    odoo_pid = project_id[0] if isinstance(project_id, list) else project_id
                    local_project = project_map.get(odoo_pid)
                    if not local_project:
                        # Project wasn't in the active list read above (e.g.
                        # archived project with an active task) - fetch it
                        # on demand rather than silently dropping the task.
                        try:
                            fetched = models.execute_kw(
                                odoo_service.odoo_db, uid, odoo_service.odoo_pass,
                                "project.project", "read", [[odoo_pid]],
                                {"fields": ["id", "name"]}
                            )
                        except Exception:
                            fetched = []
                        if not fetched:
                            continue
                        p = fetched[0]
                        local_project = Project.query.filter_by(odoo_project_id=odoo_pid).first()
                        if not local_project:
                            local_project = Project(odoo_project_id=odoo_pid, name=p.get('name', 'Unknown Project'))
                            db.session.add(local_project)
                            db.session.flush()
                        project_map[odoo_pid] = local_project

                    task = Task.query.filter_by(odoo_task_id=odoo_tid).first()
                    stage_name = 'Unknown'
                    stage_data = t.get('stage_id')
                    if stage_data:
                        sid = stage_data[0] if isinstance(stage_data, list) else stage_data
                        stage_name = stage_map.get(sid, 'Unknown')

                    priority_map = {'0': 'P3', '1': 'P2', '2': 'P1'}
                    priority = priority_map.get(str(t.get('priority', '0')), 'P3')

                    if not task:
                        task = Task(
                            odoo_task_id=odoo_tid,
                            project_id=local_project.id,
                            name=t.get('name', 'Untitled Task'),
                            description=t.get('description', ''),
                            priority=priority,
                            stage=stage_name,
                        )
                        db.session.add(task)
                        db.session.flush()
                    else:
                        task.name = t.get('name', task.name)
                        task.description = t.get('description', task.description)
                        task.priority = priority
                        task.stage = stage_name
                        if task.project_id != local_project.id:
                            task.project_id = local_project.id
                    task_map[odoo_tid] = task
                db.session.commit()
                logger.info(f"Synced {len(odoo_tasks)} tasks from Odoo")

            # ── Timesheets (still windowed by `hours`; project/task rows
            # above are already fully synced regardless of this window) ──
            odoo_timesheets = odoo_service.fetch_recent_timesheets(models, uid, hours)
            logger.info(f"Fetched {len(odoo_timesheets)} timesheet entries from Odoo")

            # Sync Timesheets
            timesheet_count = 0
            for ts in odoo_timesheets:
                odoo_ts_id = ts['id']
                existing = Timesheet.query.filter_by(odoo_timesheet_id=odoo_ts_id).first()
                if existing:
                    continue

                user_id = ts.get('user_id')
                task_id = ts.get('task_id')
                if not user_id or not task_id:
                    continue
                odoo_uid = user_id[0] if isinstance(user_id, list) else user_id
                odoo_tid = task_id[0] if isinstance(task_id, list) else task_id

                local_user = user_map.get(odoo_uid)
                local_task = task_map.get(odoo_tid)
                if not local_user or not local_task:
                    continue

                timesheet = Timesheet(
                    odoo_timesheet_id=odoo_ts_id,
                    user_id=local_user.id,
                    task_id=local_task.id,
                    hours=float(ts.get('unit_amount', 0) or 0),
                    description=ts.get('name', ''),
                    date=datetime.strptime(ts['date'], '%Y-%m-%d').date() if ts.get('date') else datetime.utcnow().date(),
                )
                db.session.add(timesheet)
                timesheet_count += 1

            db.session.commit()
            logger.info(f"Synced {timesheet_count} new timesheet entries from Odoo")
            logger.info(f"Sync complete: {len(user_map)} users, {len(project_map)} projects, {len(task_map)} tasks, {timesheet_count} timesheets")

        except Exception as e:
            logger.error(f"Error syncing Odoo data: {e}")
            db.session.rollback()
            raise
    
    @staticmethod
    def generate_analytics(user_id=None, report_id=None, date=None):
        """Generate analytics data for historical analysis"""
        try:
            target_date = date or datetime.utcnow().date()

            query = Timesheet.query.filter(Timesheet.date == target_date)
            if user_id:
                query = query.filter(Timesheet.user_id == user_id)

            timesheets = query.all()

            total_hours = sum(ts.hours for ts in timesheets)
            project_ids = set()
            task_ids = set()
            task_priority_hours = defaultdict(lambda: {'P1': 0, 'P2': 0, 'P3': 0})
            stage_counts = {'open': 0, 'in_progress': 0, 'done': 0}

            for ts in timesheets:
                if ts.task:
                    project_ids.add(ts.task.project_id)
                    task_ids.add(ts.task_id)
                    priority = ts.task.priority or 'P3'
                    task_priority_hours[ts.task_id][priority] += ts.hours

                    stage = (ts.task.stage or '').lower()
                    if 'done' in stage or 'close' in stage:
                        stage_counts['done'] += 1
                    elif 'progress' in stage or 'review' in stage or 'develop' in stage:
                        stage_counts['in_progress'] += 1
                    else:
                        stage_counts['open'] += 1

            # Upsert analytics
            existing = ReportAnalytics.query.filter_by(
                user_id=user_id, date=target_date
            ).first()

            if existing:
                existing.total_hours = total_hours
                existing.project_count = len(project_ids)
                existing.task_count = len(task_ids)
                existing.p1_hours = sum(h['P1'] for h in task_priority_hours.values())
                existing.p2_hours = sum(h['P2'] for h in task_priority_hours.values())
                existing.p3_hours = sum(h['P3'] for h in task_priority_hours.values())
                existing.open_tasks = stage_counts['open']
                existing.in_progress_tasks = stage_counts['in_progress']
                existing.completed_tasks = stage_counts['done']
            else:
                analytics = ReportAnalytics(
                    user_id=user_id,
                    report_id=report_id,
                    date=target_date,
                    total_hours=total_hours,
                    project_count=len(project_ids),
                    task_count=len(task_ids),
                    p1_hours=sum(h['P1'] for h in task_priority_hours.values()),
                    p2_hours=sum(h['P2'] for h in task_priority_hours.values()),
                    p3_hours=sum(h['P3'] for h in task_priority_hours.values()),
                    open_tasks=stage_counts['open'],
                    in_progress_tasks=stage_counts['in_progress'],
                    completed_tasks=stage_counts['done'],
                )
                db.session.add(analytics)

            db.session.commit()
            logger.info(f"Analytics {'updated' if existing else 'created'} for {'user: ' + str(user_id) if user_id else 'team'} on {target_date}")

        except Exception as e:
            logger.error(f"Error generating analytics: {e}")
            db.session.rollback()

    @staticmethod
    def generate_all_analytics():
        """Generate analytics for all dates that have timesheet data"""
        try:
            dates = db.session.query(Timesheet.date).distinct().all()
            for (d,) in dates:
                ReportGenerationService.generate_analytics(date=d)
            logger.info(f"Analytics generated for {len(dates)} dates")
        except Exception as e:
            logger.error(f"Error generating all analytics: {e}")
    
    @staticmethod
    def generate_report_content(report_id, hours_window=24, report_type='team', user_id=None):
        """Generate rich paginated HTML report with per-user pages and charts"""
        try:
            # ── Load config for shift_hours and excluded_users ──
            shift_hours = 8.3
            excluded_users = []
            try:
                with open('config.yaml', 'r') as f:
                    config = yaml.safe_load(f)
                shift_hours = float(config.get('report', {}).get('shift_hours', 8.3))
                excluded_users = config.get('report', {}).get('excluded_users', [])
            except Exception:
                pass

            since_date = (datetime.utcnow() - timedelta(hours=hours_window)).date()

            # ── Query timesheets for requested period ──
            query = Timesheet.query.filter(Timesheet.date >= since_date)
            if user_id:
                query = query.filter(Timesheet.user_id == user_id)
            timesheets = query.all()

            # ── Query 5-day window for charts ──
            five_days_ago = (datetime.utcnow() - timedelta(days=5)).date()
            ts_5d_query = Timesheet.query.filter(Timesheet.date >= five_days_ago)
            if user_id:
                ts_5d_query = ts_5d_query.filter(Timesheet.user_id == user_id)
            timesheets_5d = ts_5d_query.all()

            total_hours = sum(ts.hours for ts in timesheets)
            if not timesheets:
                logger.warning(f"No timesheet data found for report {report_id} (since {since_date})")

            # ── Generate missing/failed task summaries via LLM ──
            # Note: a task with a previously *failed* summary still has a
            # TaskSummary row (storing the "Summary unavailable: ..." text),
            # so we must explicitly re-include those for retry rather than
            # only picking tasks with no row at all -- otherwise a single
            # transient LLM failure (e.g. host unreachable) gets permanently
            # cached and is never retried on subsequent report generations.
            unique_tasks = set()
            for ts in timesheets:
                if ts.task:
                    unique_tasks.add(ts.task)

            existing_summaries = {
                s.task_id: s
                for s in TaskSummary.query.filter(
                    TaskSummary.task_id.in_([t.id for t in unique_tasks])
                ).all()
            } if unique_tasks else {}

            def _needs_retry(existing):
                return existing is None or (existing.summary or '').startswith('Summary unavailable:')

            tasks_needing_summary = [t for t in unique_tasks if _needs_retry(existing_summaries.get(t.id))]

            if tasks_needing_summary:
                try:
                    llm = LLMService()
                except Exception:
                    llm = None
                for task in tasks_needing_summary:
                    stale_summary = existing_summaries.get(task.id)

                    log_texts = [ts.description for ts in task.timesheets if ts.description]
                    if not log_texts:
                        if stale_summary:
                            stale_summary.summary = "No log entries to summarize."
                            stale_summary.log_entries_count = 0
                        else:
                            db.session.add(TaskSummary(task_id=task.id, summary="No log entries to summarize.", log_entries_count=0))
                        db.session.commit()
                        continue
                    try:
                        prompt = f"You are a project management analyst. Analyze the following task activity.\n\nTask Description:\n{task.description or 'No description provided'}\n\nLog Entries:\n" + "\n".join(log_texts[:10]) + "\n\nProvide a structured analysis covering:\n1. What is happening on this task — current status and activity summary\n2. Technical approach — why specific technical work was performed this way\n3. Timeline — when work started, key milestones reached, deadlines\n4. Bottlenecks — any blockers, dependencies causing delays, or risks\n5. What went well — successes, smooth workflows, good decisions made\n\nLabel each section clearly, e.g. \"[What's Happening]\" with a brief paragraph under each."
                        summary_text = llm.call(prompt, timeout=120) if llm else "Summary unavailable: LLM not configured"
                    except Exception as e:
                        logger.error(f"LLM summary failed for task '{task.name}': {e}")
                        summary_text = f"Summary unavailable: {str(e)}"

                    if stale_summary:
                        stale_summary.summary = summary_text
                        stale_summary.log_entries_count = len(log_texts)
                    else:
                        db.session.add(TaskSummary(task_id=task.id, summary=summary_text, log_entries_count=len(log_texts)))
                    db.session.commit()
                    logger.info(f"Generated LLM summary for task '{task.name}'")

            # ── Build nested user_tasks_data (user -> project -> tasks) ──
            priority_reverse = {'P1': '2', 'P2': '1', 'P3': '0'}
            user_tasks_data = {}

            for ts in timesheets:
                if not ts.user or not ts.task:
                    continue
                user_name = ts.user.name
                project_name = ts.task.project.name if ts.task.project else 'No Project'

                if user_name not in user_tasks_data:
                    user_tasks_data[user_name] = {
                        'name': user_name,
                        'email': ts.user.email or '',
                        'projects': {},
                        'total_hours': 0,
                    }

                if project_name not in user_tasks_data[user_name]['projects']:
                    user_tasks_data[user_name]['projects'][project_name] = {
                        'total_hours': 0,
                        'tasks': {},
                    }

                task_key = ts.task.odoo_task_id
                if task_key not in user_tasks_data[user_name]['projects'][project_name]['tasks']:
                    task_summary_obj = TaskSummary.query.filter_by(task_id=ts.task.id).first()
                    llm_summary = task_summary_obj.summary if task_summary_obj else None

                    user_tasks_data[user_name]['projects'][project_name]['tasks'][task_key] = {
                        'id': ts.task.odoo_task_id,
                        'name': ts.task.name,
                        'description': ts.task.description or '',
                        'hours': 0,
                        'timesheet_entries': [],
                        'llm_summary': llm_summary,
                        'is_subtask': False,
                        'parent_id': None,
                        'create_date': ts.task.created_at.isoformat() if ts.task.created_at else '',
                        'date_deadline': ts.task.deadline.isoformat() if ts.task.deadline else '',
                        'progress': ts.task.progress or 0,
                        'stage': ts.task.stage or 'Unknown',
                        'task_owner': user_name,
                        'priority': priority_reverse.get(ts.task.priority, '0'),
                        'milestone_name': '-',
                        'milestone_deadline': '',
                    }

                entry = {
                    'hours': ts.hours,
                    'description': ts.description or '',
                    'date': ts.date.isoformat(),
                }
                user_tasks_data[user_name]['projects'][project_name]['tasks'][task_key]['timesheet_entries'].append(entry)
                user_tasks_data[user_name]['projects'][project_name]['tasks'][task_key]['hours'] += ts.hours
                user_tasks_data[user_name]['projects'][project_name]['total_hours'] += ts.hours
                user_tasks_data[user_name]['total_hours'] += ts.hours

            # Convert task dicts to sorted lists
            for uname in user_tasks_data:
                for pname in user_tasks_data[uname]['projects']:
                    tasks_list = list(user_tasks_data[uname]['projects'][pname]['tasks'].values())
                    tasks_list.sort(key=lambda x: x['hours'], reverse=True)
                    user_tasks_data[uname]['projects'][pname]['tasks'] = tasks_list

            # ── Build recent_activity_map for Gantt charts ──
            recent_activity_map = {}
            for ts in timesheets_5d:
                if not ts.user or not ts.task:
                    continue
                user_name = ts.user.name
                task_id = ts.task.odoo_task_id
                date_str = ts.date.isoformat()
                stage_bucket = normalize_stage_bucket(ts.task.stage)
                project_name = ts.task.project.name if ts.task.project else 'No Project'

                if user_name not in recent_activity_map:
                    recent_activity_map[user_name] = []

                existing = None
                for row in recent_activity_map[user_name]:
                    if row['task_id'] == task_id and row['date'] == date_str:
                        existing = row
                        break

                if existing:
                    existing['hours'] += ts.hours
                else:
                    task_name = ts.task.name
                    if len(task_name) > 52:
                        task_name = task_name[:49] + '...'
                    recent_activity_map[user_name].append({
                        'task_id': task_id,
                        'task_name': task_name,
                        'date': date_str,
                        'hours': round(ts.hours, 2),
                        'stage': ts.task.stage or 'Unknown',
                        'stage_bucket': stage_bucket,
                        'project_name': project_name,
                    })

            # ── Project hours (5d) for charts ──
            project_hours_5d = defaultdict(float)
            for ts in timesheets_5d:
                if ts.task and ts.task.project:
                    project_hours_5d[ts.task.project.name] += ts.hours

            # ── Generate chart components ──
            top_projects_html = build_top_projects_summary_html(project_hours_5d, user_tasks_data)
            timeline_days = max(5, int(round(hours_window / 24)))
            timeline_label = f'Last {timeline_days} Days'
            projects_bubble_html = generate_project_bubble_chart_html(project_hours_5d, timeline_label)
            projects_tasks_gantt_html = generate_projects_tasks_gantt_html(recent_activity_map)

            # ── Project criticality heatmap ──
            project_effort_by_priority = defaultdict(lambda: {'P1': 0.0, 'P2': 0.0, 'P3': 0.0})
            for ts in timesheets:
                if not ts.task or not ts.task.project:
                    continue
                priority_label = get_priority_label(priority_reverse.get(ts.task.priority, '0'))
                project_effort_by_priority[ts.task.project.name][priority_label] += ts.hours

            project_criticality_rows = []
            for pname, pvals in project_effort_by_priority.items():
                total_effort = pvals['P1'] + pvals['P2'] + pvals['P3']
                if total_effort <= 0:
                    continue
                project_criticality_rows.append({
                    'project_name': pname,
                    'p1': round(pvals['P1'], 2),
                    'p2': round(pvals['P2'], 2),
                    'p3': round(pvals['P3'], 2),
                    'total': round(total_effort, 2),
                })
            project_heatmap_html = generate_project_criticality_heatmap_html(project_criticality_rows)

            # ── Generate project-level report ──
            if report_type == 'project':
                project_data = {}
                for uname, udata in user_tasks_data.items():
                    for pname, pdata in udata.get('projects', {}).items():
                        if pname not in project_data:
                            project_data[pname] = {
                                'name': pname,
                                'total_hours': 0,
                                'tasks': {},
                                'engineers': {},
                                'priority_hours': {'P1': 0.0, 'P2': 0.0, 'P3': 0.0},
                            }
                        pd = project_data[pname]
                        pd['total_hours'] += pdata.get('total_hours', 0)
                        for task in pdata.get('tasks', []):
                            task_key = task['id']
                            if task_key not in pd['tasks']:
                                pd['tasks'][task_key] = {
                                    'id': task_key,
                                    'name': task['name'],
                                    'stage': task['stage'],
                                    'priority': task.get('priority', '0'),
                                    'hours': task.get('hours', 0),
                                    'engineers': set(),
                                    'progress': task.get('progress', 0),
                                    'description': task.get('description', ''),
                                    'llm_summary': task.get('llm_summary', ''),
                                    'create_date': task.get('create_date', '')[:10],
                                    'date_deadline': task.get('date_deadline', '')[:10],
                                    'task_owner': task.get('task_owner', '-'),
                                }
                            else:
                                pd['tasks'][task_key]['hours'] += task.get('hours', 0)
                            pd['tasks'][task_key]['engineers'].add(uname)
                        if uname not in pd['engineers']:
                            pd['engineers'][uname] = 0
                        pd['engineers'][uname] += pdata.get('total_hours', 0)

                projects_list = []
                for pname, pd in project_data.items():
                    pd['engineers'] = sorted(
                        [{'name': n, 'hours': h} for n, h in pd['engineers'].items()],
                        key=lambda x: x['hours'], reverse=True,
                    )
                    pd['tasks'] = sorted(
                        [{
                            **t,
                            'engineers': list(t['engineers']),
                            'priority': get_priority_label(t.get('priority', '0')),
                        } for t in pd['tasks'].values()],
                        key=lambda x: x['hours'], reverse=True,
                    )
                    for task in pd['tasks']:
                        pd['priority_hours'][task['priority']] += task['hours']
                    projects_list.append(pd)

                projects_list.sort(key=lambda x: x['total_hours'], reverse=True)

                generated_date = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                extra_charts = {
                    'bubble_html': projects_bubble_html,
                    'heatmap_html': project_heatmap_html,
                    'gantt_html': projects_tasks_gantt_html,
                }
                html_content = generate_project_html_report(
                    projects_list, generated_date, hours_window, shift_hours, extra_charts,
                )
                report = Report.query.get(report_id)
                if report:
                    report.html_content = html_content
                    report.updated_at = datetime.utcnow()
                    db.session.commit()
                return {'html': html_content, 'json': {}}

            # ── Generate per-user Gantt charts ──
            gantt_charts = generate_per_user_gantt_charts(user_tasks_data, shift_hours, recent_activity_map)

            # ── Build all team members (for sorted listing including inactive) ──
            all_users = User.query.all()
            all_team_members = {}
            for u in all_users:
                if u.name not in excluded_users:
                    all_team_members[u.name] = {'name': u.name, 'active': u.name in user_tasks_data}

            if user_id:
                filtered = {n: m for n, m in all_team_members.items() if m['active']}
                if filtered:
                    all_team_members = filtered

            sorted_names = sorted(all_team_members.keys())
            active_user_names = set(user_tasks_data.keys())

            # ── Utilization rows ──
            utilization_rows = []
            for uname in active_user_names:
                user_data = user_tasks_data[uname]
                shift = calculate_shift_metrics(user_data.get('total_hours', 0), shift_hours)
                utilization_rows.append({
                    'name': uname,
                    'logged': shift['logged'],
                    'utilization': shift['utilization'],
                    'overtime': shift['overtime'],
                    'status': shift['status'],
                    'band': shift['band'],
                })

            total_logged = sum(r['logged'] for r in utilization_rows)
            total_overtime = sum(r['overtime'] for r in utilization_rows)
            avg_utilization = (sum(r['utilization'] for r in utilization_rows) / len(utilization_rows)) if utilization_rows else 0
            under_count = len([r for r in utilization_rows if r['band'] == 'under'])
            healthy_count = len([r for r in utilization_rows if r['band'] == 'healthy'])
            over_count = len([r for r in utilization_rows if r['band'] == 'over'])

            team_summary = {
                'shift_hours': shift_hours,
                'total_members': len(sorted_names),
                'active_members': len(active_user_names),
                'missing_members': len(sorted_names) - len(active_user_names),
                'total_logged': total_logged,
                'total_overtime': total_overtime,
                'avg_utilization': avg_utilization,
                'under_count': under_count,
                'healthy_count': healthy_count,
                'over_count': over_count,
                'utilization_rows': utilization_rows,
                'top_projects_html': top_projects_html,
                'projects_bubble_html': projects_bubble_html,
                'projects_tasks_gantt_html': projects_tasks_gantt_html,
            }

            # ── Build paginated user pages ──
            all_user_pages = []
            total_pages = len(sorted_names) + 1

            overview_page = generate_team_overview_page_html(team_summary, 0, total_pages)
            all_user_pages.append({'html': overview_page, 'name': 'Team Overview'})

            for idx, name in enumerate(sorted_names, start=1):
                member = all_team_members[name]
                is_active = member['active']
                if is_active:
                    data = user_tasks_data[name]
                    page_html = generate_user_page_html(None, data, hours_window, shift_hours, gantt_charts, idx, total_pages, has_activity=True)
                else:
                    dummy_data = {'name': name, 'email': '', 'projects': {}, 'total_hours': 0}
                    page_html = generate_user_page_html(None, dummy_data, hours_window, shift_hours, gantt_charts, idx, total_pages, has_activity=False)
                all_user_pages.append({'html': page_html, 'name': name})

            # ── Build landing_filter_data for drill-down (from available data) ──
            project_map = {}
            for uname, user_data in user_tasks_data.items():
                for pname, proj_data in user_data.get('projects', {}).items():
                    if pname not in project_map:
                        project_map[pname] = {'name': pname, 'engineers': {}}
                    for task in proj_data.get('tasks', []):
                        if uname not in project_map[pname]['engineers']:
                            project_map[pname]['engineers'][uname] = {'name': uname, 'tasks': []}
                        llm_result = task.get('llm_summary')
                        summary_text = "No activity summary in selected period."
                        if isinstance(llm_result, dict):
                            summary_text = llm_result.get('summary', summary_text) or summary_text
                        elif isinstance(llm_result, str) and llm_result.strip():
                            summary_text = llm_result.strip()
                        project_map[pname]['engineers'][uname]['tasks'].append({
                            'id': task['id'],
                            'name': task['name'],
                            'summary': summary_text,
                            'status': task['stage'],
                            'age': calculate_age(task.get('create_date', '')),
                            'priority': get_priority_label(task.get('priority', '0')),
                            'progress': task.get('progress', 0),
                            'logged_hours': task.get('hours', 0),
                            'owner': task.get('task_owner', '-'),
                            'milestone': task.get('milestone_name', '-'),
                            'milestone_deadline': (task.get('milestone_deadline', '') or '')[:10],
                            'deadline': (task.get('date_deadline', '') or '')[:10],
                            'opened_on': (task.get('create_date', '') or '')[:10],
                            'timesheet_entries': len(task.get('timesheet_entries', [])),
                            'description': task.get('description', ''),
                        })

            landing_projects = []
            for pname in sorted(project_map.keys()):
                engineer_rows = []
                for ename in sorted(project_map[pname]['engineers'].keys()):
                    tasks = sorted(
                        project_map[pname]['engineers'][ename]['tasks'],
                        key=lambda x: (x.get('logged_hours', 0), x.get('name', '')),
                        reverse=True,
                    )
                    engineer_rows.append({'name': ename, 'tasks': tasks})
                landing_projects.append({'name': pname, 'engineers': engineer_rows})
            landing_filter_data = {'projects': landing_projects}

            # ── Generate final HTML report ──
            generated_date = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            html_content = generate_html_report(
                all_user_pages,
                generated_date,
                hours_window,
                shift_hours,
                gantt_charts,
                landing_filter_data,
            )

            # ── Build JSON data for API consumers ──
            users_data = defaultdict(lambda: {'hours': 0, 'tasks': set(), 'projects': set()})
            projects_data = defaultdict(lambda: {'hours': 0, 'tasks': 0, 'users': set()})
            priority_data = {'P1': 0, 'P2': 0, 'P3': 0}

            for ts in timesheets:
                if ts.user:
                    users_data[ts.user.name]['hours'] += ts.hours
                if ts.task:
                    user_name = ts.user.name if ts.user else 'Unknown'
                    users_data[user_name]['tasks'].add(ts.task.name)
                    if ts.task.project:
                        users_data[user_name]['projects'].add(ts.task.project.name)
                    priority = ts.task.priority or 'P3'
                    priority_data[priority] += ts.hours
                    if ts.task.project:
                        projects_data[ts.task.project.name]['hours'] += ts.hours
                        projects_data[ts.task.project.name]['tasks'] += 1
                        projects_data[ts.task.project.name]['users'].add(user_name)

            json_data = {
                'hours_window': hours_window,
                'report_type': report_type,
                'generated_at': datetime.utcnow().isoformat(),
                'summary': {
                    'total_hours': float(total_hours),
                    'unique_users': len(users_data),
                    'unique_projects': len(projects_data),
                    'unique_tasks': len(set(ts.task_id for ts in timesheets if ts.task_id)),
                    'period_hours': hours_window,
                },
                'priority_distribution': {
                    'P1': float(priority_data['P1']),
                    'P2': float(priority_data['P2']),
                    'P3': float(priority_data['P3']),
                },
            }

            # ── Persist to DB ──
            report = Report.query.get(report_id)
            if report:
                report.html_content = html_content
                report.json_data = json_data
                report.updated_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"Report {report_id} generated successfully")

            return {'html': html_content, 'json': json_data}

        except Exception as e:
            logger.error(f"Error generating report content: {e}")
            db.session.rollback()
            return None

class ReportCacheService:
    """Service to cache report HTML and data"""
    
    @staticmethod
    def cache_report(report_id, html_content, json_data):
        """Cache report HTML and JSON data"""
        try:
            report = Report.query.get(report_id)
            if not report:
                raise ValueError("Report not found")
            
            report.html_content = html_content
            report.json_data = json_data
            report.updated_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Report {report_id} cached successfully")
        except Exception as e:
            logger.error(f"Error caching report: {e}")
            db.session.rollback()
    
    @staticmethod
    def get_cached_report(report_id):
        """Get cached report"""
        try:
            report = Report.query.get(report_id)
            if not report or not report.html_content:
                return None
            return {
                'html': report.html_content,
                'json': report.json_data,
                'generated_at': report.generated_at
            }
        except Exception as e:
            logger.error(f"Error retrieving cached report: {e}")
            return None

def convert_md_to_xwiki(md_text):
    """Convert Markdown text to XWiki syntax."""
    import re
    text = md_text

    # Code blocks first (so they don't get mangled by other rules)
    text = re.sub(r'```(\w*)\n(.*?)```', lambda m: '{{code language="' + (m.group(1) or 'none') + '"}}\n' + m.group(2) + '\n{{/code}}', text, flags=re.DOTALL)

    # Headings
    text = re.sub(r'^######\s+(.+?)\s*$', r'====== \1 ======', text, flags=re.MULTILINE)
    text = re.sub(r'^#####\s+(.+?)\s*$', r'===== \1 =====', text, flags=re.MULTILINE)
    text = re.sub(r'^####\s+(.+?)\s*$', r'==== \1 ====', text, flags=re.MULTILINE)
    text = re.sub(r'^###\s+(.+?)\s*$', r'=== \1 ===', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.+?)\s*$', r'== \1 ==', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.+?)\s*$', r'= \1 =', text, flags=re.MULTILINE)

    # Bold **text** → *text*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    # Italic *text* → //text// (but not inside **...** already converted)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'//\1//', text)

    # Strikethrough ~~text~~ → --text--
    text = re.sub(r'~~(.+?)~~', r'--\1--', text)

    # Inline code
    text = re.sub(r'`([^`]+)`', r'{{code}}\1{{/code}}', text)

    # Images ![alt](url) → [[image:url]]
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'[[image:\2]]', text)

    # Links [text](url) → [[text>>url]]
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'[[\1>>\2]]', text)

    return text


class XWikiService:
    """Service to interact with XWiki REST API."""

    def __init__(self, config_path='config.yaml'):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        xcfg = config.get('xwiki', {})
        self.base_url = xcfg.get('base_url', '').rstrip('/')
        self.wiki = xcfg.get('wiki', 'xwiki')
        self.space = xcfg.get('space', 'Projects')
        self.username = xcfg.get('user', '')
        self.password = xcfg.get('password', '')
        self.auth = (self.username, self.password) if self.username else None

    def _api_url(self, space, page):
        """Build XWiki REST API URL for a page, supporting dot-separated space hierarchy.
        e.g. space='Parent.Child', page='MyPage' → .../spaces/Parent/spaces/Child/pages/MyPage
        """
        from urllib.parse import quote
        segments = space.split('.')
        space_path = '/spaces/'.join(quote(s) for s in segments)
        return f"{self.base_url}/xwiki/rest/wikis/{self.wiki}/spaces/{space_path}/pages/{quote(page)}"

    def get_page(self, space, page):
        """Fetch current page content from XWiki. Returns dict with title and content, or None."""
        try:
            url = self._api_url(space, page)
            resp = requests.get(url, auth=self.auth, headers={"Accept": "application/json"}, timeout=15)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return {
                'title': data.get('title', ''),
                'content': data.get('content', ''),
                'version': data.get('version', ''),
                'exists': True,
            }
        except requests.exceptions.RequestException as e:
            logger.warning(f"XWiki get_page failed: {e}")
            return None

    def save_page(self, space, page, title, content):
        """Create or update an XWiki page. Returns success bool and message."""
        try:
            url = self._api_url(space, page)
            payload = {'title': title, 'content': content}
            resp = requests.put(url, json=payload, auth=self.auth,
                                headers={"Content-Type": "application/json"}, timeout=15)
            if resp.status_code in (200, 201, 202, 204):
                return True, "Page saved successfully."
            logger.warning(f"XWiki save_page returned {resp.status_code}: {resp.text}")
            return False, f"XWiki returned status {resp.status_code}: {resp.text[:200]}"
        except requests.exceptions.RequestException as e:
            logger.error(f"XWiki save_page failed: {e}")
            return False, str(e)

    def attach_file(self, space, page, filename, content_bytes, content_type='text/markdown'):
        """Upload a file as an attachment on an XWiki page (creates the page
        first if it doesn't exist yet). Sends the raw file bytes as-is --
        unlike save_page, this does NOT convert or reformat the content in
        any way. Returns success bool and message."""
        try:
            from urllib.parse import quote
            url = f"{self._api_url(space, page)}/attachments/{quote(filename)}"
            resp = requests.put(
                url, data=content_bytes, auth=self.auth,
                headers={"Content-Type": content_type}, timeout=30,
            )
            if resp.status_code in (200, 201, 202, 204):
                return True, "File attached successfully."
            logger.warning(f"XWiki attach_file returned {resp.status_code}: {resp.text}")
            return False, f"XWiki returned status {resp.status_code}: {resp.text[:200]}"
        except requests.exceptions.RequestException as e:
            logger.error(f"XWiki attach_file failed: {e}")
            return False, str(e)
