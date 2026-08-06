"""
Database models for Team Activity Reports
"""
from app import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSON, ARRAY
import uuid

class User(db.Model):
    """Team member user"""
    __tablename__ = 'users'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Nullable now: self-registered accounts (role='reporter') have no Odoo
    # employee behind them at all. Postgres allows multiple NULLs under a
    # unique constraint, so this stays safe for the Odoo-synced 'employee'/
    # 'admin' accounts, which still get a real odoo_user_id.
    odoo_user_id = db.Column(db.Integer, unique=True, nullable=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True)

    # RBAC: 'admin' / 'employee' (synced from Odoo, full navbar access) or
    # 'reporter' (self-registered, bug-tracker-only access, see
    # require_role() and the bug_list()/bug_submit() reporter scoping in
    # api/routes.py).
    role = db.Column(db.String(20), default='reporter', nullable=False)
    # Only set for self-registered ('reporter') accounts; Odoo-synced users
    # authenticate against Odoo itself and never have a local password.
    password_hash = db.Column(db.String(255), nullable=True)

    # Independent of role: when true, the navbar/routes only show Bug
    # Tracker (same restricted UI a 'reporter' gets) -- but unlike
    # role='reporter', bug_list()/bug_detail() do NOT scope this account to
    # its own reports, since that scoping only checks for role=='reporter'.
    # Used for admin/employee accounts that should see every report in All
    # Reports without getting the rest of the internal dashboard. Set via
    # `flask create-admin`.
    bug_tracker_only = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    reports = db.relationship('Report', backref='user', lazy=True, cascade='all, delete-orphan')
    timesheets = db.relationship('Timesheet', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'odoo_user_id': self.odoo_user_id,
            'name': self.name,
            'email': self.email,
            'active': self.active,
            'role': self.role,
            'bug_tracker_only': self.bug_tracker_only,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

class Project(db.Model):
    """Project"""
    __tablename__ = 'projects'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    odoo_project_id = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    tasks = db.relationship('Task', backref='project', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'odoo_project_id': self.odoo_project_id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
        }

class Task(db.Model):
    """Project Task"""
    __tablename__ = 'tasks'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    odoo_task_id = db.Column(db.Integer, unique=True, nullable=False)
    project_id = db.Column(db.String(36), db.ForeignKey('projects.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(10))  # P1, P2, P3
    stage = db.Column(db.String(100))
    progress = db.Column(db.Float, default=0.0)
    deadline = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    timesheets = db.relationship('Timesheet', backref='task', lazy=True, cascade='all, delete-orphan')
    task_summaries = db.relationship('TaskSummary', backref='task', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'odoo_task_id': self.odoo_task_id,
            'project_id': self.project_id,
            'name': self.name,
            'description': self.description,
            'priority': self.priority,
            'stage': self.stage,
            'progress': self.progress,
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'created_at': self.created_at.isoformat(),
        }

class Timesheet(db.Model):
    """Timesheet Entry"""
    __tablename__ = 'timesheets'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    odoo_timesheet_id = db.Column(db.Integer, unique=True, nullable=False)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    task_id = db.Column(db.String(36), db.ForeignKey('tasks.id'), nullable=False)
    hours = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'task_id': self.task_id,
            'hours': self.hours,
            'description': self.description,
            'date': self.date.isoformat(),
            'created_at': self.created_at.isoformat(),
        }

class Report(db.Model):
    """Generated Report (stores metadata and HTML snapshot)"""
    __tablename__ = 'reports'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)  # NULL for team reports
    report_type = db.Column(db.String(50), nullable=False)  # 'team', 'personal', 'project'
    title = db.Column(db.String(255), nullable=False)
    hours_window = db.Column(db.Integer, default=24)  # Hours covered in report
    html_content = db.Column(db.Text)  # Cached HTML
    json_data = db.Column(JSON)  # Structured data for historical analysis
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self, include_html=False):
        # user_id is NULL for team-wide reports (see column comment above),
        # so those show as "Team" rather than a blank/missing creator.
        # self.user relies on the backref declared on User.reports.
        created_by = self.user.name if (self.user_id and self.user) else 'Team'
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'created_by': created_by,
            'report_type': self.report_type,
            'title': self.title,
            'hours_window': self.hours_window,
            'generated_at': self.generated_at.isoformat(),
            'is_archived': self.is_archived,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat() if self.updated_at else self.created_at.isoformat(),
        }
        if include_html:
            data['html_content'] = self.html_content
        if self.json_data:
            data['json_data'] = self.json_data
        return data

class TaskSummary(db.Model):
    """LLM-generated task summary (cached)"""
    __tablename__ = 'task_summaries'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = db.Column(db.String(36), db.ForeignKey('tasks.id'), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    authors = db.Column(db.String(255))
    log_entries_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'summary': self.summary,
            'authors': self.authors,
            'log_entries_count': self.log_entries_count,
            'created_at': self.created_at.isoformat(),
        }

class BugAttachment(db.Model):
    """Actual file content for a bug-tracker attachment.

    Previously, BugReport.attachments only stored {filename, content_type,
    size} -- the uploaded bytes were sent on to Odoo (best-effort) and then
    discarded, so there was nothing local to view or download. This table
    holds the real bytes so attachments can be opened/viewed and downloaded
    straight from this app regardless of Odoo sync status.
    """
    __tablename__ = 'bug_attachments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bug_id = db.Column(db.String(36), db.ForeignKey('bug_reports.id'), nullable=False, index=True)
    filename = db.Column(db.String(500))
    content_type = db.Column(db.String(255))
    size = db.Column(db.Integer, default=0)
    # 'initial' (submitted with the report), 'edit' (added via Edit), or a
    # status key (e.g. 'in_progress') if added during a status update.
    stage = db.Column(db.String(50), default='initial')
    data = db.Column(db.LargeBinary)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_meta_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'content_type': self.content_type,
            'size': self.size,
            'stage': self.stage,
        }


class BugReport(db.Model):
    """Bug tracker entry for the OSDBcortex project.

    category is one of: 'general', 'bug', 'feature', 'observation'
    status is one of: 'open', 'in_progress', 'resolved', 'closed'
    """
    __tablename__ = 'bug_reports'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    category = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), default='medium')  # critical, high, medium, low
    status = db.Column(db.String(20), default='open')  # open, in_progress, resolved, closed

    reporter_name = db.Column(db.String(255))
    reporter_email = db.Column(db.String(255))
    # Which logged-in account submitted this report. NULL for older rows
    # created before this column existed. Set server-side from the JWT on
    # submit (see bug_submit() in api/routes.py) -- never trust a client-
    # supplied user id -- and used to scope the 'reporter' role to only
    # their own reports in bug_list().
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True, index=True)

    answers = db.Column(JSON)  # category-specific probing question answers
    attachments = db.Column(JSON)  # list of {filename, content_type, size, stage}
    status_updates = db.Column(JSON)  # list of {status, fields, attachments, odoo_synced, odoo_sync_error, created_at}

    project_name = db.Column(db.String(255), default='OSDBcortex')
    odoo_task_id = db.Column(db.Integer, nullable=True)
    odoo_sync_error = db.Column(db.Text, nullable=True)

    email_sent = db.Column(db.Boolean, default=False)
    email_recipients = db.Column(db.String(500))

    # Sprint the report is scheduled into. 1-8, or NULL which means it sits
    # in the Backlog (either never assigned, or a sprint was already full --
    # see MAX_SPRINT_NUMBER / MAX_ITEMS_PER_SPRINT in services.py).
    sprint = db.Column(db.Integer, nullable=True)

    # Marks a report as also planned for the future roadmap. This is a tag,
    # not a separate bucket -- it's set right on a sprint card (see the
    # sprint board in api/routes.py) and coexists with whatever `sprint`
    # value the report has.
    roadmap = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'title': self.title,
            'description': self.description,
            'severity': self.severity,
            'status': self.status,
            'reporter_name': self.reporter_name,
            'reporter_email': self.reporter_email,
            'user_id': self.user_id,
            'answers': self.answers or {},
            'attachments': self.attachments or [],
            'status_updates': self.status_updates or [],
            'project_name': self.project_name,
            'odoo_task_id': self.odoo_task_id,
            'odoo_sync_error': self.odoo_sync_error,
            'email_sent': self.email_sent,
            'email_recipients': self.email_recipients,
            'sprint': self.sprint,
            'roadmap': bool(self.roadmap),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

class TeamTask(db.Model):
    """A task assigned to one of the fixed bug-tracker teams.

    team_key is one of: 'team1', 'team2', 'team3' (see TEAM_DEFINITIONS in
    services.py for the member rosters). This lives alongside BugReport on
    the OSDBcortex bug tracker page, shown below the 4 report categories.
    """
    __tablename__ = 'team_tasks'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_key = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=False)
    attachments = db.Column(JSON)  # list of {filename, content_type, size}

    assigned_by_name = db.Column(db.String(255))
    assigned_by_email = db.Column(db.String(255))

    send_email = db.Column(db.Boolean, default=False)
    email_recipients = db.Column(db.String(500))
    email_sent = db.Column(db.Boolean, default=False)
    email_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'team_key': self.team_key,
            'description': self.description,
            'attachments': self.attachments or [],
            'assigned_by_name': self.assigned_by_name,
            'assigned_by_email': self.assigned_by_email,
            'send_email': self.send_email,
            'email_recipients': self.email_recipients,
            'email_sent': self.email_sent,
            'email_error': self.email_error,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class ReportAnalytics(db.Model):
    """Pre-computed analytics for quick historical retrieval"""
    __tablename__ = 'report_analytics'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    report_id = db.Column(db.String(36), db.ForeignKey('reports.id'), nullable=True)
    
    # Daily metrics
    date = db.Column(db.Date, nullable=False)
    total_hours = db.Column(db.Float, default=0.0)
    project_count = db.Column(db.Integer, default=0)
    task_count = db.Column(db.Integer, default=0)
    average_utilization = db.Column(db.Float, default=0.0)
    
    # Priority distribution
    p1_hours = db.Column(db.Float, default=0.0)
    p2_hours = db.Column(db.Float, default=0.0)
    p3_hours = db.Column(db.Float, default=0.0)
    
    # Status distribution
    open_tasks = db.Column(db.Integer, default=0)
    in_progress_tasks = db.Column(db.Integer, default=0)
    completed_tasks = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'date': self.date.isoformat(),
            'total_hours': self.total_hours,
            'project_count': self.project_count,
            'task_count': self.task_count,
            'average_utilization': self.average_utilization,
            'p1_hours': self.p1_hours,
            'p2_hours': self.p2_hours,
            'p3_hours': self.p3_hours,
            'open_tasks': self.open_tasks,
            'in_progress_tasks': self.in_progress_tasks,
            'completed_tasks': self.completed_tasks,
        }


class TeamUpdateImage(db.Model):
    """One image belonging to a TeamUpdate post. A post can carry several of
    these, shown as a horizontally-scrollable gallery when viewing the post.
    """
    __tablename__ = 'team_update_images'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    update_id = db.Column(db.String(36), db.ForeignKey('team_updates.id'), nullable=False, index=True)
    filename = db.Column(db.String(500))
    content_type = db.Column(db.String(255))
    size = db.Column(db.Integer, default=0)
    data = db.Column(db.LargeBinary)
    position = db.Column(db.Integer, default=0)  # display order within the post

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_meta_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'content_type': self.content_type,
            'size': self.size,
        }


class TeamUpdateAttachment(db.Model):
    """A non-image file attached to a TeamUpdate post (docs, logs, etc.),
    separate from the image gallery so the two can be shown differently.
    """
    __tablename__ = 'team_update_attachments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    update_id = db.Column(db.String(36), db.ForeignKey('team_updates.id'), nullable=False, index=True)
    filename = db.Column(db.String(500))
    content_type = db.Column(db.String(255))
    size = db.Column(db.Integer, default=0)
    data = db.Column(db.LargeBinary)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_meta_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'content_type': self.content_type,
            'size': self.size,
        }


class TeamUpdate(db.Model):
    """A short 'post' -- optional images/files plus a description -- shared
    from the Bug Tracker's Sprints toolbar ('+ Post Update'). Posted by an
    admin/employee account, visible to everyone who can open the bug
    tracker, including reporters. A post needs only a description; images
    and file attachments are both optional.
    """
    __tablename__ = 'team_updates'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True, index=True)
    author_name = db.Column(db.String(255))
    description = db.Column(db.Text, nullable=False)

    # Legacy single-image columns, kept so posts created before multi-image
    # support still render. New posts leave these null and use `images`.
    image_filename = db.Column(db.String(500))
    image_content_type = db.Column(db.String(255))
    image_data = db.Column(db.LargeBinary)

    images = db.relationship(
        'TeamUpdateImage', backref='update', order_by='TeamUpdateImage.position',
        cascade='all, delete-orphan',
    )
    attachments = db.relationship(
        'TeamUpdateAttachment', backref='update',
        cascade='all, delete-orphan',
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        images = [img.to_meta_dict() for img in self.images]
        if not images and self.image_data is not None:
            # Legacy post -- surface the old single image through the same
            # `images` list shape via the legacy endpoint below.
            images = [{
                'id': None,
                'filename': self.image_filename,
                'content_type': self.image_content_type,
                'size': len(self.image_data) if self.image_data else 0,
                'legacy': True,
            }]
        return {
            'id': self.id,
            'user_id': self.user_id,
            'author_name': self.author_name,
            'description': self.description,
            'has_image': bool(images),
            'images': images,
            'attachments': [a.to_meta_dict() for a in self.attachments],
            'created_at': self.created_at.isoformat(),
        }

class WelcomePopup(db.Model):
    """Site-wide 'what's new' popup shown once right after any user signs in
    or creates an account. Single row (id='default'); an admin can swap the
    image, caption, or turn it off entirely from Settings, any time, with no
    redeploy needed -- that's what makes it "dynamic".
    """
    __tablename__ = 'welcome_popup'

    id = db.Column(db.String(20), primary_key=True, default='default')
    enabled = db.Column(db.Boolean, default=True)
    title = db.Column(db.String(255))
    caption = db.Column(db.Text)

    image_filename = db.Column(db.String(500))
    image_content_type = db.Column(db.String(255))
    image_data = db.Column(db.LargeBinary)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)

    def to_dict(self):
        return {
            'enabled': bool(self.enabled) and self.image_data is not None,
            'title': self.title,
            'caption': self.caption,
            'has_image': self.image_data is not None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
