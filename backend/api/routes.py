"""
API Routes - Main endpoints
"""
from flask import Blueprint, jsonify, request, send_file
from app import db, jwt
from models import User, Project, Task, Timesheet, Report, TaskSummary, ReportAnalytics, BugReport, BugAttachment, TeamTask, TeamUpdate, TeamUpdateImage, TeamUpdateAttachment, WelcomePopup
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import logging
import random
import xmlrpc.client
import yaml
import base64
import binascii

logger = logging.getLogger(__name__)

# ============== RBAC ==============
# Two kinds of account:
#  - 'admin' / 'employee': synced from Odoo, authenticate with Odoo creds,
#    full navbar access.
#  - 'reporter': self-registered (no Odoo account at all), bug-tracker-only
#    access, and only ever see their own bug reports.
# The role travels in the JWT (set at login) so every request can be
# checked without a DB hit.

def require_role(*roles):
    """Route decorator: 401 if not logged in, 403 if role isn't allowed.
    Use in addition to @jwt_required() is not necessary -- this implies it."""
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            if get_jwt().get('role') not in roles:
                return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# Blueprints
main_bp = Blueprint('main', __name__, url_prefix='/api')
report_bp = Blueprint('reports', __name__, url_prefix='/api/reports')
analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
bugtracker_bp = Blueprint('bugtracker', __name__, url_prefix='/api/bugtracker')


@report_bp.before_request
@require_role('admin', 'employee')
def _guard_report_bp():
    return None


@analytics_bp.before_request
@require_role('admin', 'employee')
def _guard_analytics_bp():
    return None


# ============== Sync Routes ==============

@main_bp.route('/sync', methods=['POST'])
@require_role('admin', 'employee')
def sync_data():
    """Trigger Odoo data sync"""
    try:
        data = request.get_json() or {}
        hours = data.get('hours', 24)
        from services import ReportGenerationService

        ReportGenerationService.sync_odoo_data(hours=hours)
        ReportGenerationService.generate_all_analytics()

        return jsonify({
            'status': 'success',
            'message': f'Odoo data synced successfully (last {hours}h)',
        }), 200
    except Exception as e:
        logger.error(f"Error during sync: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============== Main Routes ==============

@main_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        db.session.execute('SELECT 1')
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'connected'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


# ============== Welcome popup ("what's new" after sign-in/sign-up) ==============
# A single admin-editable image + optional caption shown once right after any
# user logs in or registers. "Dynamic" means an admin can swap the image or
# switch it off from Settings at any time -- no code change or redeploy.

@main_bp.route('/welcome-popup', methods=['GET'])
@jwt_required()
def welcome_popup_get():
    """Any logged-in user (any role) can fetch the current popup config --
    this is what the frontend checks right after login/registration."""
    try:
        popup = WelcomePopup.query.get('default')
        if not popup:
            return jsonify({'status': 'success', 'data': {'enabled': False, 'has_image': False}}), 200
        return jsonify({'status': 'success', 'data': popup.to_dict()}), 200
    except Exception as e:
        logger.error(f"Error fetching welcome popup: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/welcome-popup', methods=['POST'])
@require_role('admin')
def welcome_popup_update():
    """Admin-only. Replace the popup image and/or its enabled state, title,
    caption. Expected JSON body (all fields optional, send just what's
    changing):
      {
        enabled: bool,
        title: string,
        caption: string,
        image: { filename, content_type, content_b64 }
      }
    Turning `enabled` off just hides the popup -- the saved image stays put
    so it can be switched back on later without re-uploading it.
    """
    try:
        data = request.get_json() or {}
        popup = WelcomePopup.query.get('default')
        if not popup:
            popup = WelcomePopup(id='default')
            db.session.add(popup)

        if 'enabled' in data:
            popup.enabled = bool(data['enabled'])
        if 'title' in data:
            popup.title = (data.get('title') or '').strip()[:255]
        if 'caption' in data:
            popup.caption = (data.get('caption') or '').strip()[:2000]

        image = data.get('image')
        if image and image.get('content_b64'):
            try:
                raw_bytes = base64.b64decode(image['content_b64'], validate=False)
            except (binascii.Error, ValueError):
                return jsonify({'status': 'error', 'message': 'Invalid image data'}), 400
            if len(raw_bytes) > 8 * 1024 * 1024:
                return jsonify({'status': 'error', 'message': 'Image is too large (max 8MB)'}), 400
            popup.image_filename = image.get('filename', 'welcome.png')
            popup.image_content_type = image.get('content_type') or 'image/png'
            popup.image_data = raw_bytes

        popup.updated_by = get_jwt_identity()
        db.session.commit()
        return jsonify({'status': 'success', 'data': popup.to_dict(), 'message': 'Welcome popup updated.'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating welcome popup: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/welcome-popup/image', methods=['GET'])
@jwt_required()
def welcome_popup_image():
    """Stream the popup image back inline. Used as an <img src>, so the
    token is accepted via ?token=... too (see JWT_TOKEN_LOCATION in app.py)."""
    try:
        popup = WelcomePopup.query.get('default')
        if not popup or popup.image_data is None:
            return jsonify({'status': 'error', 'message': 'No image set'}), 404

        from io import BytesIO
        return send_file(
            BytesIO(popup.image_data),
            mimetype=popup.image_content_type or 'application/octet-stream',
            as_attachment=False,
            download_name=popup.image_filename or 'welcome.png',
        )
    except Exception as e:
        logger.error(f"Error viewing welcome popup image: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/users', methods=['GET'])
@require_role('admin', 'employee')
def get_users():
    """Get all team members"""
    try:
        users = User.query.filter_by(active=True).all()
        return jsonify({
            'status': 'success',
            'count': len(users),
            'data': [u.to_dict() for u in users]
        }), 200
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/users/<user_id>', methods=['GET'])
@require_role('admin', 'employee')
def get_user(user_id):
    """Get specific user details"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
        return jsonify({
            'status': 'success',
            'data': user.to_dict()
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/projects', methods=['GET'])
@require_role('admin', 'employee')
def get_projects():
    """Get all projects"""
    try:
        projects = Project.query.all()
        return jsonify({
            'status': 'success',
            'count': len(projects),
            'data': [p.to_dict() for p in projects]
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/tasks', methods=['GET'])
@require_role('admin', 'employee')
def get_tasks():
    """List tasks, optionally filtered by project_id"""
    try:
        project_id = request.args.get('project_id')
        query = Task.query
        if project_id:
            query = query.filter_by(project_id=project_id)
        tasks = query.order_by(Task.name).all()
        return jsonify({
            'status': 'success',
            'count': len(tasks),
            'data': [t.to_dict() for t in tasks]
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/tasks/<task_id>/context', methods=['GET'])
@require_role('admin', 'employee')
def get_task_context(task_id):
    """Return task details, recent timesheets, and LLM-generated what/how/why/when questions"""
    try:
        task = Task.query.get(task_id)
        if not task:
            return jsonify({'status': 'error', 'message': 'Task not found'}), 404

        recent_entries = Timesheet.query.filter_by(task_id=task_id)\
            .order_by(Timesheet.date.desc(), Timesheet.created_at.desc()).limit(10).all()

        existing_summary = TaskSummary.query.filter_by(task_id=task_id).first()

        status = request.args.get('status', '')

        # Questions are a fixed, basic set based only on the chosen status --
        # they are intentionally not generated from recent activity.
        from services import generate_task_context_questions
        questions = generate_task_context_questions(status=status)

        return jsonify({
            'status': 'success',
            'data': {
                'task': task.to_dict(),
                'recent_timesheets': [{
                    'id': ts.id,
                    'user_name': ts.user.name if ts.user else 'Unknown',
                    'hours': ts.hours,
                    'description': ts.description,
                    'date': ts.date.isoformat(),
                } for ts in recent_entries],
                'existing_summary': existing_summary.to_dict() if existing_summary else None,
                'questions': questions,
            }
        }), 200
    except Exception as e:
        logger.error(f"Error fetching task context: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/timesheets/log', methods=['POST'])
@require_role('admin', 'employee')
def log_timesheet():
    """Create a timesheet entry locally and push to Odoo"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        task_id = data.get('task_id')
        hours = data.get('hours')
        description = data.get('description', '')
        # The summary text (already priority-tagged by the client) is what
        # actually gets written into the Odoo log note -- the log note is
        # intentionally just the summary, not a dump of every field.
        log_summary = data.get('log_summary', '') or description
        date_str = data.get('date')
        priority = data.get('priority')  # P1 / P2 / P3, optional
        status = data.get('status', '')  # completed / in_progress / blocker
        support_required = data.get('support_required')  # True/False
        support_person = data.get('support_person', '')
        mark_complete = bool(data.get('mark_complete'))

        if not task_id or hours is None:
            return jsonify({'status': 'error', 'message': 'task_id and hours are required'}), 400

        user = User.query.get(user_id)
        task = Task.query.get(task_id)
        if not user:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
        if not task:
            return jsonify({'status': 'error', 'message': 'Task not found'}), 404

        log_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.utcnow().date()

        if priority:
            task.priority = priority

        local_id = -random.randint(1, 2147483647)
        timesheet = Timesheet(
            odoo_timesheet_id=local_id,
            user_id=user_id,
            task_id=task_id,
            hours=float(hours),
            description=description,
            date=log_date,
        )
        db.session.add(timesheet)
        db.session.commit()

        odoo_result = None
        try:
            from services import OdooService
            odoo_svc = OdooService()
            odoo_user_id = user.odoo_user_id
            odoo_task_id = task.odoo_task_id
            priority_tag = f"[{priority}] " if priority else ''
            short_summary = log_summary.split('\n')[0][:150] if log_summary else ''
            timesheet_desc = f"{priority_tag}[{user.name}] {short_summary}".strip()

            # The log note itself only ever contains the summary, tagged
            # with priority -- status/support are tracked as separate
            # structured fields, not inlined into the note text.
            note_body = (log_summary or 'No summary provided.').strip()
            if priority and not note_body.startswith(priority_tag.strip()):
                note_body = f"{priority_tag}{note_body}"
            full_note = (
                f"<b>Work Log – {user.name}</b><br/><br/>"
                f"{note_body.replace(chr(10), '<br/>')}"
            )
            ok, result = odoo_svc.create_timesheet(
                user_id=odoo_user_id,
                task_id=odoo_task_id,
                hours=hours,
                description=timesheet_desc,
                date=log_date,
                log_note=full_note,
            )
            if ok:
                odoo_result = {'odoo_timesheet_id': result}
                timesheet.odoo_timesheet_id = result
                db.session.commit()
                logger.info(f"Pushed timesheet to Odoo (id={result})")
            else:
                odoo_result = {'error': result}
                logger.warning(f"Odoo push skipped: {result}")

            if mark_complete:
                try:
                    done_ok, done_result = odoo_svc.mark_task_done(odoo_task_id)
                    if done_ok:
                        task.stage = 'Done'
                        db.session.commit()
                        odoo_result = odoo_result or {}
                        odoo_result['task_marked_done'] = True
                        odoo_result['odoo_stage'] = done_result
                    else:
                        odoo_result = odoo_result or {}
                        odoo_result['task_marked_done'] = False
                        odoo_result['mark_done_error'] = done_result
                except Exception as done_err:
                    logger.warning(f"Failed to mark task complete in Odoo: {done_err}")
                    odoo_result = odoo_result or {}
                    odoo_result['task_marked_done'] = False
                    odoo_result['mark_done_error'] = str(done_err)
        except Exception as e:
            odoo_result = {'error': str(e)}
            logger.warning(f"Odoo push failed: {e}")

        data = timesheet.to_dict()
        if odoo_result:
            data['odoo_sync'] = odoo_result
        data['task'] = task.to_dict()

        return jsonify({
            'status': 'success',
            'message': 'Timesheet entry logged successfully',
            'data': data,
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error logging timesheet: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============== Task Summary / Support / Email Routes ==============

@main_bp.route('/tasks/<task_id>/summary', methods=['POST'])
@require_role('admin', 'employee')
def generate_task_log_summary(task_id):
    """Generate (or regenerate, with an optional custom prompt) an AI summary
    of today's work on a task, based on recent activity + the engineer's answers."""
    try:
        task = Task.query.get(task_id)
        if not task:
            return jsonify({'status': 'error', 'message': 'Task not found'}), 404

        data = request.get_json() or {}
        status = data.get('status', '')
        user_summary = data.get('user_summary', '')
        answers = data.get('answers', {}) or {}
        custom_prompt = data.get('custom_prompt', '')
        priority = data.get('priority')

        recent_entries = Timesheet.query.filter_by(task_id=task_id)\
            .order_by(Timesheet.date.desc(), Timesheet.created_at.desc()).limit(10).all()

        from services import generate_task_summary
        summary = generate_task_summary(
            task_name=task.name,
            task_description=task.description or '',
            status=status,
            log_entries=[ts.description for ts in recent_entries if ts.description],
            user_summary=user_summary,
            answers=answers,
            custom_prompt=custom_prompt,
            priority=priority,
        )

        return jsonify({'status': 'success', 'data': {'summary': summary}}), 200
    except Exception as e:
        logger.error(f"Error generating task summary: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/odoo/users/search', methods=['GET'])
@require_role('admin', 'employee')
def odoo_users_search():
    """Live-search Odoo users by name/email, for the 'support required from' typeahead."""
    try:
        query = request.args.get('q', '')
        from services import OdooService
        odoo_svc = OdooService()
        results = odoo_svc.search_users(query, limit=10)
        return jsonify({
            'status': 'success',
            'data': [{'id': u['id'], 'name': u['name'], 'email': u.get('email', '')} for u in results],
        }), 200
    except Exception as e:
        logger.error(f"Error searching Odoo users: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/email/send', methods=['POST'])
@require_role('admin', 'employee')
def send_summary_email():
    """Send a work-log summary email to arbitrary recipients."""
    try:
        data = request.get_json() or {}
        to = data.get('to', [])
        if isinstance(to, str):
            to = [addr.strip() for addr in to.split(',') if addr.strip()]
        subject = data.get('subject', 'Task Log Summary')
        body = data.get('body', '')

        if not to:
            return jsonify({'status': 'error', 'message': 'At least one recipient is required'}), 400
        if not body:
            return jsonify({'status': 'error', 'message': 'Email body is required'}), 400

        from alerting import AlertService
        ok, message = AlertService().send_custom_email(to, subject, body)
        if ok:
            return jsonify({'status': 'success', 'message': message}), 200
        return jsonify({'status': 'error', 'message': message}), 500
    except Exception as e:
        logger.error(f"Error sending summary email: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============== Report Routes ==============

@report_bp.route('', methods=['POST'])
def create_report():
    """Generate new report (auto-syncs Odoo data first)"""
    try:
        data = request.get_json()
        report_type = data.get('report_type', 'team')  # team, personal, project
        hours_window = data.get('hours_window', 24)
        user_id = data.get('user_id')  # Optional, for personal reports

        title = f"{report_type.capitalize()} Report - Last {hours_window}h"

        from services import ReportGenerationService

        # Sync Odoo data first so local DB has fresh data
        ReportGenerationService.sync_odoo_data(hours=hours_window)

        # Create initial report record
        report = Report(
            user_id=user_id,
            report_type=report_type,
            title=title,
            hours_window=hours_window,
            json_data={}
        )

        db.session.add(report)
        db.session.commit()

        # Generate report content from synced local data
        content_result = ReportGenerationService.generate_report_content(
            report.id,
            hours_window=hours_window,
            report_type=report_type,
            user_id=user_id
        )

        if not content_result:
            # generate_report_content logs the underlying exception itself;
            # the report row exists but has no html_content/json_data, so
            # don't report success -- the previous behavior here ignored
            # this failure entirely and told the user the report was ready
            # when there was nothing to view or download.
            logger.error(f"Report {report.id} content generation failed; leaving report without html_content")
            return jsonify({
                'status': 'error',
                'message': 'Report generation failed while building the report content. Check the backend logs for details.',
                'data': report.to_dict()
            }), 500

        # Generate analytics for trend data
        ReportGenerationService.generate_analytics(
            user_id=user_id,
            report_id=report.id,
        )

        # Refresh report from database to get updated content
        db.session.refresh(report)

        return jsonify({
            'status': 'success',
            'message': 'Report generated successfully',
            'data': report.to_dict()
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating report: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@report_bp.route('', methods=['GET'])
def list_reports():
    """List reports with pagination.

    Unfiltered by design: every admin/employee account sees every report
    here (team, personal, and project alike), regardless of who generated
    it -- there's no implicit "only my reports" scoping. The optional
    `user_id` query param lets a caller narrow to one person's reports if
    it wants that (e.g. a per-user view elsewhere), but the default "All
    Reports" listing is intentionally shared across the whole team.
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        report_type = request.args.get('report_type')
        user_id = request.args.get('user_id')
        
        query = (
            Report.query
            .options(joinedload(Report.user))  # avoid N+1 lookups for created_by
            .filter_by(is_archived=False)
            .order_by(Report.generated_at.desc())
        )
        
        if report_type:
            query = query.filter_by(report_type=report_type)
        if user_id:
            query = query.filter_by(user_id=user_id)
        
        pagination = query.paginate(page=page, per_page=per_page)
        
        return jsonify({
            'status': 'success',
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page,
            'data': [r.to_dict() for r in pagination.items]
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@report_bp.route('/<report_id>', methods=['GET'])
def get_report(report_id):
    """Get specific report"""
    try:
        include_html = request.args.get('include_html', 'false').lower() == 'true'
        report = Report.query.get(report_id)
        
        if not report:
            return jsonify({'status': 'error', 'message': 'Report not found'}), 404
        
        return jsonify({
            'status': 'success',
            'data': report.to_dict(include_html=include_html)
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@report_bp.route('/<report_id>/html', methods=['GET'])
def download_report_html(report_id):
    """Download report as HTML"""
    try:
        report = Report.query.get(report_id)
        
        if not report:
            return jsonify({'status': 'error', 'message': 'Report not found'}), 404
        
        if not report.html_content:
            return jsonify({'status': 'error', 'message': 'Report HTML not available'}), 404
        
        # Return as file download
        from io import BytesIO
        
        html_bytes = BytesIO(report.html_content.encode('utf-8'))
        filename = f"report_{report.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
        
        return send_file(
            html_bytes,
            mimetype='text/html',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@report_bp.route('/<report_id>/regenerate', methods=['POST'])
def regenerate_report(report_id):
    """Retry content generation for an existing report -- most useful for
    reports stuck with no html_content because generation previously
    failed silently (e.g. LLM host unreachable) and returned a false
    'success' to the client. Reuses the report's original parameters and
    updates the row in place rather than creating a new report."""
    try:
        report = Report.query.get(report_id)
        if not report:
            return jsonify({'status': 'error', 'message': 'Report not found'}), 404

        from services import ReportGenerationService

        ReportGenerationService.sync_odoo_data(hours=report.hours_window)

        content_result = ReportGenerationService.generate_report_content(
            report.id,
            hours_window=report.hours_window,
            report_type=report.report_type,
            user_id=report.user_id
        )

        if not content_result:
            logger.error(f"Regeneration failed for report {report.id}; still no html_content")
            return jsonify({
                'status': 'error',
                'message': 'Report regeneration failed. Check the backend logs for details.',
                'data': report.to_dict()
            }), 500

        ReportGenerationService.generate_analytics(
            user_id=report.user_id,
            report_id=report.id,
        )

        db.session.refresh(report)

        return jsonify({
            'status': 'success',
            'message': 'Report regenerated successfully',
            'data': report.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error regenerating report {report_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@report_bp.route('/<report_id>/delete', methods=['DELETE'])
def delete_report(report_id):
    """Delete/archive report"""
    try:
        report = Report.query.get(report_id)
        
        if not report:
            return jsonify({'status': 'error', 'message': 'Report not found'}), 404
        
        report.is_archived = True
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Report archived'
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============== Analytics Routes ==============

@analytics_bp.route('/user/<user_id>/summary', methods=['GET'])
def user_analytics_summary(user_id):
    """Get user analytics summary"""
    try:
        days = request.args.get('days', 30, type=int)
        since = datetime.utcnow().date() - timedelta(days=days)
        
        analytics = ReportAnalytics.query.filter(
            and_(
                ReportAnalytics.user_id == user_id,
                ReportAnalytics.date >= since
            )
        ).order_by(ReportAnalytics.date).all()
        
        if not analytics:
            return jsonify({
                'status': 'success',
                'message': f'No analytics data for past {days} days',
                'data': []
            }), 200
        
        return jsonify({
            'status': 'success',
            'days': days,
            'records': len(analytics),
            'data': [a.to_dict() for a in analytics]
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@analytics_bp.route('/team/summary', methods=['GET'])
def team_analytics_summary():
    """Get team-wide analytics"""
    try:
        days = request.args.get('days', 7, type=int)
        since = datetime.utcnow().date() - timedelta(days=days)
        
        # Aggregate analytics across all users
        analytics = db.session.query(
            ReportAnalytics.date,
            func.sum(ReportAnalytics.total_hours).label('total_hours'),
            func.sum(ReportAnalytics.project_count).label('project_count'),
            func.sum(ReportAnalytics.task_count).label('task_count'),
            func.avg(ReportAnalytics.average_utilization).label('avg_utilization'),
            func.sum(ReportAnalytics.p1_hours).label('p1_hours'),
            func.sum(ReportAnalytics.p2_hours).label('p2_hours'),
            func.sum(ReportAnalytics.p3_hours).label('p3_hours'),
        ).filter(
            ReportAnalytics.date >= since
        ).group_by(ReportAnalytics.date).order_by(ReportAnalytics.date).all()
        
        if not analytics:
            return jsonify({
                'status': 'success',
                'message': f'No analytics data for past {days} days',
                'data': []
            }), 200
        
        data = [{
            'date': str(row[0]),
            'total_hours': float(row[1] or 0),
            'project_count': int(row[2] or 0),
            'task_count': int(row[3] or 0),
            'avg_utilization': float(row[4] or 0),
            'p1_hours': float(row[5] or 0),
            'p2_hours': float(row[6] or 0),
            'p3_hours': float(row[7] or 0),
        } for row in analytics]
        
        return jsonify({
            'status': 'success',
            'days': days,
            'records': len(data),
            'data': data
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@analytics_bp.route('/trends', methods=['GET'])
def trends():
    """Get historical trends and patterns"""
    try:
        days = request.args.get('days', 90, type=int)
        metric = request.args.get('metric', 'total_hours')  # total_hours, utilization, etc.
        
        since = datetime.utcnow().date() - timedelta(days=days)
        
        analytics = db.session.query(
            ReportAnalytics.date,
            getattr(ReportAnalytics, metric)
        ).filter(
            ReportAnalytics.date >= since
        ).order_by(ReportAnalytics.date).all()
        
        data = [{
            'date': str(row[0]),
            metric: float(row[1] or 0)
        } for row in analytics]
        
        # Calculate trend
        if len(data) >= 2:
            first_val = float(data[0][metric])
            last_val = float(data[-1][metric])
            trend = ((last_val - first_val) / first_val * 100) if first_val != 0 else 0
        else:
            trend = 0
        
        return jsonify({
            'status': 'success',
            'metric': metric,
            'days': days,
            'records': len(data),
            'trend_percent': round(trend, 2),
            'data': data
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============== XWiki Routes ==============

@main_bp.route('/xwiki/config', methods=['GET'])
@require_role('admin', 'employee')
def xwiki_config():
    """Return XWiki configuration (safe fields only)"""
    try:
        from services import XWikiService
        xwiki = XWikiService()
        return jsonify({
            'status': 'success',
            'data': {
                'base_url': xwiki.base_url,
                'wiki': xwiki.wiki,
                'default_space': xwiki.space,
            }
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/xwiki/page', methods=['GET'])
@require_role('admin', 'employee')
def xwiki_get_page():
    """Fetch an XWiki page content"""
    try:
        space = request.args.get('space', '')
        page = request.args.get('page', '')
        if not space or not page:
            return jsonify({'status': 'error', 'message': 'space and page query params required'}), 400
        from services import XWikiService
        xwiki = XWikiService()
        result = xwiki.get_page(space, page)
        if result is None:
            return jsonify({'status': 'success', 'data': {'exists': False, 'title': page, 'content': ''}}), 200
        return jsonify({'status': 'success', 'data': result}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/xwiki/page', methods=['POST'])
@require_role('admin', 'employee')
def xwiki_save_page():
    """Create or update an XWiki page"""
    try:
        data = request.get_json()
        space = data.get('space', '')
        page = data.get('page', '')
        title = data.get('title', page)
        content = data.get('content', '')
        if not space or not page:
            return jsonify({'status': 'error', 'message': 'space and page are required'}), 400
        from services import XWikiService
        xwiki = XWikiService()
        ok, msg = xwiki.save_page(space, page, title, content)
        return jsonify({'status': 'success' if ok else 'error', 'message': msg}), 200 if ok else 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/xwiki/convert', methods=['POST'])
@require_role('admin', 'employee')
def xwiki_convert():
    """Convert markdown text to XWiki syntax"""
    try:
        data = request.get_json()
        md_text = data.get('markdown', '')
        from services import convert_md_to_xwiki
        xwiki_text = convert_md_to_xwiki(md_text)
        return jsonify({'status': 'success', 'data': {'xwiki': xwiki_text}}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/xwiki/attachment', methods=['POST'])
@require_role('admin', 'employee')
def xwiki_save_attachment():
    """Upload the original .md file as an attachment on an XWiki page, as-is
    (no markdown -> XWiki syntax conversion). XWiki will create the page
    first if it doesn't already exist."""
    try:
        data = request.get_json() or {}
        space = data.get('space', '')
        page = data.get('page', '')
        filename = data.get('filename', '')
        content = data.get('content', '')
        if not space or not page or not filename:
            return jsonify({'status': 'error', 'message': 'space, page, and filename are required'}), 400
        if not filename.endswith('.md'):
            return jsonify({'status': 'error', 'message': 'Only .md files are supported for attachment.'}), 400

        from services import XWikiService
        xwiki = XWikiService()
        ok, msg = xwiki.attach_file(space, page, filename, content.encode('utf-8'), content_type='text/markdown')
        return jsonify({'status': 'success' if ok else 'error', 'message': msg}), 200 if ok else 502
    except Exception as e:
        logger.error(f"Error saving XWiki attachment: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/kb/save', methods=['POST'])
@require_role('admin', 'employee')
def kb_save_local():
    """Save a .md Knowledge Base file to a local folder on the backend,
    organized as kb_storage/<project>/<task>/. The folder is created
    automatically the first time it's needed -- this is independent of
    (and in addition to) the XWiki integration above."""
    try:
        data = request.get_json() or {}
        project_name = data.get('project_name', '')
        task_name = data.get('task_name', '')
        filename = data.get('filename', '')
        content = data.get('content', '')
        if not filename or not content:
            return jsonify({'status': 'error', 'message': 'filename and content are required'}), 400

        from kb_storage import save_kb_file
        filepath = save_kb_file(project_name, task_name, filename, content)
        return jsonify({'status': 'success', 'data': {'path': filepath}}), 200
    except Exception as e:
        logger.error(f"Error saving KB file locally: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============== Auth Routes ==============

def _load_odoo_config():
    with open('config.yaml', 'r') as f:
        cfg = yaml.safe_load(f)
    odoo = cfg.get('odoo', {})
    return odoo.get('url'), odoo.get('db')

def _issue_token(user):
    token = create_access_token(
        identity=str(user.id),
        additional_claims={
            'odoo_user_id': user.odoo_user_id,
            'name': user.name,
            'email': user.email,
            'role': user.role,
            'bug_tracker_only': user.bug_tracker_only,
        }
    )
    return token


@auth_bp.route('/register', methods=['POST'])
def auth_register():
    """Self-registration for users with no Odoo account at all.

    Always creates a 'reporter' role account -- bug-tracker-only access,
    enforced both by the frontend navbar and by require_role()/the
    reporter-scoped query in bug_list() below. This never talks to Odoo.
    """
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not name or not email or not password:
        return jsonify({'status': 'error', 'message': 'Name, email and password are required'}), 400
    if len(password) < 8:
        return jsonify({'status': 'error', 'message': 'Password must be at least 8 characters'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'status': 'error', 'message': 'An account with this email already exists'}), 409

    user = User(
        name=name,
        email=email,
        role='reporter',
        password_hash=generate_password_hash(password),
        odoo_user_id=None,
    )
    db.session.add(user)
    db.session.commit()

    token = _issue_token(user)
    return jsonify({
        'status': 'success',
        'token': token,
        'user': {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role, 'bug_tracker_only': user.bug_tracker_only},
    }), 201


@auth_bp.route('/login', methods=['POST'])
def auth_login():
    """Authenticate a user and return a JWT token.

    Two paths:
      - Self-registered 'reporter' accounts: checked against the local
        password_hash, no Odoo involved.
      - Odoo-synced 'employee'/'admin' accounts: checked against Odoo via
        XML-RPC, same as before.
    """
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'status': 'error', 'message': 'Email and password are required'}), 400

    existing = User.query.filter_by(email=email).first()

    # Local ('reporter') account path -- no Odoo call at all.
    if existing and existing.password_hash:
        if not check_password_hash(existing.password_hash, password):
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401
        token = _issue_token(existing)
        return jsonify({
            'status': 'success',
            'token': token,
            'user': {'id': existing.id, 'name': existing.name, 'email': existing.email, 'role': existing.role, 'bug_tracker_only': existing.bug_tracker_only},
        }), 200

    # Odoo-employee account path (unchanged behavior).
    odoo_url, odoo_db = _load_odoo_config()
    if not odoo_url or not odoo_db:
        return jsonify({'status': 'error', 'message': 'Odoo not configured on server'}), 500

    try:
        common = xmlrpc.client.ServerProxy(f"{odoo_url}/xmlrpc/2/common")
        uid = common.authenticate(odoo_db, email, password, {})
        if not uid:
            return jsonify({'status': 'error', 'message': 'Invalid Odoo credentials'}), 401

        user = User.query.filter_by(odoo_user_id=uid).first()
        if not user:
            return jsonify({'status': 'error', 'message': 'User not found. Run sync first or contact admin.'}), 404

        token = _issue_token(user)
        return jsonify({
            'status': 'success',
            'token': token,
            'user': {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role, 'bug_tracker_only': user.bug_tracker_only},
        }), 200

    except Exception as e:
        logger.error(f"Auth login error: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to authenticate against Odoo'}), 500


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def auth_me():
    """Return current authenticated user info from JWT."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    return jsonify({
        'status': 'success',
        'user': {'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role, 'bug_tracker_only': user.bug_tracker_only},
    }), 200

# ============== Bug Tracker Routes (OSDBcortex) ==============
#
# Access model:
#  - Any logged-in user (admin/employee/reporter) can use the bug tracker.
#  - 'reporter' accounts (self-registered, no Odoo access) can only submit
#    reports and see/view their OWN reports -- see bug_list()/bug_detail()/
#    bug_submit() below for the actual scoping.
#  - Sprint planning, team-task assignment, and status/edit updates stay
#    admin/employee-only -- these are internal triage tools, not something
#    a self-registered reporter should be able to touch.

@bugtracker_bp.before_request
@jwt_required()
def _guard_bugtracker_bp():
    return None


def _current_user():
    return User.query.get(get_jwt_identity())


BUG_PROJECT_NAME = 'OSDBcortex'
ALLOWED_BUG_CATEGORIES = ('bug', 'feature', 'general', 'observation')
ALLOWED_BUG_STATUSES = ('open', 'in_progress', 'resolved', 'closed')

# Sprint planning for the bug tracker: a single active sprint that can hold
# at most MAX_ITEMS_PER_SPRINT reports -- once it's full, anything else
# assigned to it falls back to the Backlog (sprint=NULL) instead of being
# rejected outright.
MAX_SPRINTS = 1
MAX_ITEMS_PER_SPRINT = 8

# Odoo-style progress a report has made through the workflow, used for the
# progress bar on sprint board cards (mirrors how Odoo's kanban stage-bar /
# % complete works for a task).
STATUS_PROGRESS = {'open': 0, 'in_progress': 50, 'resolved': 90, 'closed': 100}


def _save_bug_attachments(bug_id, raw_attachments, stage='initial'):
    """Persist the actual bytes of each uploaded attachment (not just its
    filename/size) so it can be opened/viewed and downloaded later, and
    return the metadata list to store on BugReport.attachments / a status
    update entry. Silently skips any attachment with unreadable base64
    content rather than failing the whole request.
    """
    saved_meta = []
    for a in raw_attachments:
        filename = a.get('filename', 'attachment')
        content_type = a.get('content_type') or 'application/octet-stream'
        content_b64 = a.get('content_b64', '') or ''
        try:
            raw_bytes = base64.b64decode(content_b64, validate=False)
        except (binascii.Error, ValueError):
            logger.warning(f"Skipping attachment '{filename}' for bug {bug_id}: invalid base64 content")
            continue

        attachment = BugAttachment(
            bug_id=bug_id,
            filename=filename,
            content_type=content_type,
            size=len(raw_bytes),
            stage=stage,
            data=raw_bytes,
        )
        db.session.add(attachment)
        db.session.flush()  # populate attachment.id before we reference it
        saved_meta.append(attachment.to_meta_dict())
    return saved_meta


def _backfill_attachments_from_odoo(bug):
    """Recover local file content for a bug report's attachments (both the
    top-level ones and any on its status_updates) that were saved before
    this app persisted attachment bytes locally -- i.e. entries with a
    filename but no 'id'.

    Those files were still pushed to Odoo at the time (via
    OdooService.attach_file_to_task against bug.odoo_task_id), so we pull
    them back from the linked Odoo task's ir.attachment records, match them
    to the metadata-only entries by filename (consumed in creation order so
    repeated filenames -- e.g. multiple "Screenshot ...png" -- line up with
    the right upload), and store the real bytes as BugAttachment rows so
    they become viewable/downloadable like any other attachment.

    Returns the number of attachments recovered.
    """
    if not bug.odoo_task_id:
        return 0

    from services import OdooService
    odoo = OdooService()
    odoo_attachments = odoo.fetch_task_attachments(bug.odoo_task_id)
    if not odoo_attachments:
        return 0

    used = [False] * len(odoo_attachments)

    def _claim(filename):
        for i, oa in enumerate(odoo_attachments):
            if not used[i] and oa['filename'] == filename:
                used[i] = True
                return oa
        return None

    recovered = 0

    def _recover_list(att_list):
        nonlocal recovered
        if not att_list:
            return att_list
        changed = False
        new_list = []
        for a in att_list:
            if a.get('id'):
                new_list.append(a)
                continue
            match = _claim(a.get('filename'))
            if not match:
                new_list.append(a)
                continue
            try:
                raw_bytes = base64.b64decode(match['content_b64'], validate=False)
            except (binascii.Error, ValueError):
                logger.warning(
                    f"Odoo attachment '{match['filename']}' for task "
                    f"{bug.odoo_task_id} had unreadable base64 content; skipping"
                )
                new_list.append(a)
                continue
            attachment = BugAttachment(
                bug_id=bug.id,
                filename=match['filename'],
                content_type=match['mimetype'],
                size=len(raw_bytes),
                stage=a.get('stage', 'initial'),
                data=raw_bytes,
            )
            db.session.add(attachment)
            db.session.flush()
            new_list.append(attachment.to_meta_dict())
            recovered += 1
            changed = True
        return new_list if changed else att_list

    bug.attachments = _recover_list(bug.attachments)
    if bug.status_updates:
        new_updates = []
        for u in bug.status_updates:
            u = dict(u)
            u['attachments'] = _recover_list(u.get('attachments'))
            new_updates.append(u)
        bug.status_updates = new_updates

    if recovered:
        db.session.commit()
    return recovered


@bugtracker_bp.route('/<bug_id>/backfill-attachments', methods=['POST'])
@require_role('admin', 'employee')
def bug_backfill_attachments(bug_id):
    """Attempt to recover missing attachment content for one bug report
    from its linked Odoo task (for attachments saved before this app
    stored file bytes locally)."""
    try:
        bug = BugReport.query.get(bug_id)
        if not bug:
            return jsonify({'status': 'error', 'message': 'Bug report not found'}), 404
        recovered = _backfill_attachments_from_odoo(bug)
        return jsonify({
            'status': 'success',
            'data': bug.to_dict(),
            'recovered': recovered,
        }), 200
    except Exception as e:
        logger.error(f"Error backfilling attachments for bug {bug_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/backfill-attachments', methods=['POST'])
@require_role('admin', 'employee')
def bug_backfill_attachments_all():
    """Bulk-run the Odoo attachment recovery across every bug report that
    has attachment metadata without locally stored file content."""
    try:
        candidates = BugReport.query.filter(BugReport.odoo_task_id.isnot(None)).all()
        total_recovered = 0
        reports_updated = 0
        for bug in candidates:
            has_missing = any(not a.get('id') for a in (bug.attachments or []))
            if not has_missing:
                for u in (bug.status_updates or []):
                    if any(not a.get('id') for a in (u.get('attachments') or [])):
                        has_missing = True
                        break
            if not has_missing:
                continue
            n = _backfill_attachments_from_odoo(bug)
            if n:
                total_recovered += n
                reports_updated += 1
        return jsonify({
            'status': 'success',
            'recovered': total_recovered,
            'reports_updated': reports_updated,
        }), 200
    except Exception as e:
        logger.error(f"Error running bulk Odoo attachment backfill: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/categories', methods=['GET'])
def bug_categories():
    """Return the 4 bug-tracker categories with their fixed probing questions."""
    try:
        from services import generate_bug_probing_questions, BUG_CATEGORY_LABELS
        data = [
            {
                'key': key,
                'label': BUG_CATEGORY_LABELS[key],
                'questions': generate_bug_probing_questions(key),
            }
            for key in ALLOWED_BUG_CATEGORIES
        ]
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e:
        logger.error(f"Error fetching bug categories: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/statuses', methods=['GET'])
def bug_statuses():
    """Return the 4 bug-tracker statuses with their fixed follow-up fields,
    e.g. 'Resolution details' for Resolved, 'Reason' for Closed."""
    try:
        from services import generate_status_update_fields, STATUS_LABELS
        data = [
            {
                'key': key,
                'label': STATUS_LABELS[key],
                'fields': generate_status_update_fields(key),
            }
            for key in ALLOWED_BUG_STATUSES
        ]
        return jsonify({'status': 'success', 'data': data}), 200
    except Exception as e:
        logger.error(f"Error fetching bug statuses: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


ALLOWED_BUG_SEVERITIES = ('critical', 'high', 'medium', 'low')


@bugtracker_bp.route('/reporters', methods=['GET'])
def bug_reporters():
    """Return the distinct list of reporter names that have submitted a
    report, alphabetically, for the 'Engineer' filter dropdown on the
    All Reports list."""
    try:
        if get_jwt().get('role') == 'reporter':
            # A reporter only ever sees their own reports, so this dropdown
            # is meaningless -- and would otherwise leak other users' names.
            return jsonify({'status': 'success', 'data': []}), 200
        rows = (
            db.session.query(BugReport.reporter_name)
            .filter(BugReport.reporter_name.isnot(None))
            .filter(BugReport.reporter_name != '')
            .distinct()
            .order_by(BugReport.reporter_name.asc())
            .all()
        )
        names = [r[0] for r in rows]
        return jsonify({'status': 'success', 'data': names}), 200
    except Exception as e:
        logger.error(f"Error fetching bug reporters: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('', methods=['GET'])
def bug_list():
    """List bug reports, optionally filtered by category/status/severity/
    reporter/roadmap, newest first."""
    try:
        category = request.args.get('category', '')
        status = request.args.get('status', '')
        severity = request.args.get('severity', '')
        reporter = request.args.get('reporter', '')
        roadmap_only = request.args.get('roadmap', '').lower() in ('true', '1', 'yes')
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 20)), 100)

        query = BugReport.query
        if category in ALLOWED_BUG_CATEGORIES:
            query = query.filter_by(category=category)
        if status in ALLOWED_BUG_STATUSES:
            query = query.filter_by(status=status)
        if severity in ALLOWED_BUG_SEVERITIES:
            query = query.filter_by(severity=severity)
        if reporter:
            query = query.filter_by(reporter_name=reporter)
        if roadmap_only:
            query = query.filter_by(roadmap=True)

        # Reporters (self-registered, no Odoo account) only ever see their
        # own submissions in "All Reports" -- this is enforced here, not
        # just hidden in the UI, since the API is what actually matters.
        if get_jwt().get('role') == 'reporter':
            query = query.filter_by(user_id=get_jwt_identity())

        query = query.order_by(BugReport.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'status': 'success',
            'data': [b.to_dict() for b in pagination.items],
            'page': page,
            'pages': pagination.pages,
            'total': pagination.total,
        }), 200
    except Exception as e:
        logger.error(f"Error listing bug reports: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/<bug_id>', methods=['GET'])
def bug_detail(bug_id):
    """Get a single bug report."""
    try:
        bug = BugReport.query.get(bug_id)
        if not bug:
            return jsonify({'status': 'error', 'message': 'Bug report not found'}), 404
        if get_jwt().get('role') == 'reporter' and bug.user_id != get_jwt_identity():
            return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
        return jsonify({'status': 'success', 'data': bug.to_dict()}), 200
    except Exception as e:
        logger.error(f"Error fetching bug report {bug_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


def _esc(value):
    """Minimal HTML-escape for safely inlining stored text into the report."""
    if value is None:
        return ''
    return (
        str(value)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def _build_bug_report_html(bug):
    """Render a single bug/report entry as a standalone, readable HTML document."""
    from services import BUG_CATEGORY_LABELS, STATUS_LABELS

    category_label = BUG_CATEGORY_LABELS.get(bug.category, bug.category)
    status_label = STATUS_LABELS.get(bug.status, bug.status)

    # Reports are downloaded as a single, fully self-contained HTML file --
    # screenshots and files below are embedded directly (base64 data URIs),
    # so nothing here depends on the live app/auth once it's saved.

    def _attachment_fragment(attachment_metas):
        """Render a report's attachments as content that works fully offline:
        screenshots are embedded inline as base64 data URIs (so they just
        display, no click/login required), everything else becomes a
        data-URI download link (still no server round-trip needed)."""
        if not attachment_metas:
            return ''
        image_tiles = []
        file_items = []
        for a in attachment_metas:
            att_id = a.get('id')
            filename = _esc(a.get('filename', 'attachment'))
            if not att_id:
                file_items.append(
                    f'<li>{filename} <span style="color:#adb5bd;">(no file saved for this older report)</span></li>'
                )
                continue
            attachment = BugAttachment.query.get(att_id)
            if not attachment or attachment.data is None:
                file_items.append(
                    f'<li>{filename} <span style="color:#adb5bd;">(file no longer available)</span></li>'
                )
                continue
            content_type = attachment.content_type or 'application/octet-stream'
            b64 = base64.b64encode(attachment.data).decode('ascii')
            data_uri = f'data:{content_type};base64,{b64}'
            if content_type.startswith('image/'):
                image_tiles.append(
                    f'<figure class="attachment-image">'
                    f'<img src="{data_uri}" alt="{filename}">'
                    f'<figcaption>{filename}</figcaption>'
                    f'</figure>'
                )
            else:
                file_items.append(
                    f'<li><a class="attachment-file" href="{data_uri}" download="{_esc(attachment.filename or "attachment")}">'
                    f'{filename} (download)</a></li>'
                )
        parts = []
        if image_tiles:
            parts.append(f'<div class="attachment-gallery">{"".join(image_tiles)}</div>')
        if file_items:
            parts.append(f'<ul class="attachment-files">{"".join(file_items)}</ul>')
        return ''.join(parts)

    answers_html = ''.join(
        f'<div class="row"><strong>{_esc(k.replace("_", " ").title())}:</strong> {_esc(v)}</div>'
        for k, v in (bug.answers or {}).items() if v
    )

    attachments_fragment = _attachment_fragment(bug.attachments)
    attachments_html = (
        f'<div class="section"><h2>Attachments</h2>{attachments_fragment}</div>'
        if attachments_fragment else ''
    )

    history_html = ''
    if bug.status_updates:
        entries = ''
        for u in bug.status_updates:
            fields_html = ''.join(
                f'<div class="row"><strong>{_esc(k.replace("_", " ").title())}:</strong> {_esc(v)}</div>'
                for k, v in (u.get('fields') or {}).items() if v
            )
            atts_fragment = _attachment_fragment(u.get('attachments') or [])
            atts_html = (
                f'<div class="row"><strong>Attachments:</strong></div>{atts_fragment}'
                if atts_fragment else ''
            )
            entries += f'''
            <div class="history-entry">
                <div class="history-head">
                    <span class="badge">{_esc(STATUS_LABELS.get(u.get("status"), u.get("status")))}</span>
                    <span class="timestamp">{_esc(u.get("created_at", ""))}</span>
                </div>
                {fields_html}
                {atts_html}
            </div>'''
        history_html = f'<div class="section"><h2>Status History</h2>{entries}</div>'

    odoo_html = ''
    if bug.odoo_task_id:
        odoo_html = f'<div class="row"><strong>Odoo Task:</strong> #{bug.odoo_task_id} in {_esc(bug.project_name)}</div>'
    if bug.odoo_sync_error:
        odoo_html += f'<div class="row error"><strong>Odoo Sync Error:</strong> {_esc(bug.odoo_sync_error)}</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{_esc(bug.title)}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #f4f5f7; color: #1f2933; margin: 0; padding: 2rem; }}
  .container {{ max-width: 800px; margin: 0 auto; background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 2rem; }}
  h1 {{ margin-top: 0; font-size: 1.5rem; }}
  .meta {{ color: #667; font-size: 0.9rem; margin-bottom: 1.5rem; }}
  .badge {{ display: inline-block; padding: 0.2rem 0.7rem; border-radius: 12px; background: #1971c2; color: #fff; font-size: 0.8rem; font-weight: 600; }}
  .section {{ margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid #eee; }}
  .section h2 {{ font-size: 1.05rem; margin-bottom: 0.6rem; color: #364150; }}
  .row {{ margin: 0.35rem 0; line-height: 1.5; }}
  .row.error {{ color: #c92a2a; }}
  .description {{ white-space: pre-wrap; line-height: 1.6; }}
  .history-entry {{ background: #f8f9fa; border-radius: 6px; padding: 0.8rem 1rem; margin-bottom: 0.8rem; }}
  .history-head {{ display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0.4rem; }}
  .timestamp {{ color: #868e96; font-size: 0.85rem; }}
  .attachment-gallery {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 0.5rem; }}
  .attachment-image {{ margin: 0; width: 220px; }}
  .attachment-image img {{ width: 100%; border-radius: 6px; border: 1px solid #e0e0e0; display: block; }}
  .attachment-image figcaption {{ font-size: 0.78rem; color: #667; margin-top: 0.25rem; word-break: break-all; }}
  .attachment-files {{ list-style: none; padding: 0; margin: 0.5rem 0 0; }}
  .attachment-files li {{ margin: 0.3rem 0; }}
  .attachment-file {{ color: #1971c2; text-decoration: none; font-weight: 500; }}
  .attachment-file:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <div class="container">
    <div class="badge">{_esc(status_label)}</div>
    <h1>{_esc(bug.title)}</h1>
    <div class="meta">
      Category: {_esc(category_label)} &nbsp;|&nbsp;
      Severity: {_esc((bug.severity or '').title())} &nbsp;|&nbsp;
      Reported: {_esc(bug.created_at.isoformat() if bug.created_at else '')}
    </div>

    <div class="description">{_esc(bug.description)}</div>

    <div class="section">
      <h2>Reporter</h2>
      <div class="row">{_esc(bug.reporter_name)} ({_esc(bug.reporter_email)})</div>
      {odoo_html}
    </div>

    {f'<div class="section"><h2>Details</h2>{answers_html}</div>' if answers_html else ''}
    {attachments_html}
    {history_html}
  </div>
</body>
</html>"""


@bugtracker_bp.route('/attachments/<attachment_id>', methods=['GET'])
def bug_attachment_view(attachment_id):
    """Stream an attachment's real content back inline, so it opens/previews
    directly in the browser tab (images, PDFs, text, etc.)."""
    try:
        attachment = BugAttachment.query.get(attachment_id)
        if not attachment or attachment.data is None:
            return jsonify({'status': 'error', 'message': 'Attachment not found'}), 404
        if get_jwt().get('role') == 'reporter':
            bug = BugReport.query.get(attachment.bug_id)
            if not bug or bug.user_id != get_jwt_identity():
                return jsonify({'status': 'error', 'message': 'Forbidden'}), 403

        from io import BytesIO
        return send_file(
            BytesIO(attachment.data),
            mimetype=attachment.content_type or 'application/octet-stream',
            as_attachment=False,
            download_name=attachment.filename or 'attachment',
        )
    except Exception as e:
        logger.error(f"Error viewing attachment {attachment_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/attachments/<attachment_id>/download', methods=['GET'])
def bug_attachment_download(attachment_id):
    """Force-download an attachment with its real content and original
    filename, rather than opening it inline."""
    try:
        attachment = BugAttachment.query.get(attachment_id)
        if not attachment or attachment.data is None:
            return jsonify({'status': 'error', 'message': 'Attachment not found'}), 404
        if get_jwt().get('role') == 'reporter':
            bug = BugReport.query.get(attachment.bug_id)
            if not bug or bug.user_id != get_jwt_identity():
                return jsonify({'status': 'error', 'message': 'Forbidden'}), 403

        from io import BytesIO
        return send_file(
            BytesIO(attachment.data),
            mimetype=attachment.content_type or 'application/octet-stream',
            as_attachment=True,
            download_name=attachment.filename or 'attachment',
        )
    except Exception as e:
        logger.error(f"Error downloading attachment {attachment_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/download-all', methods=['GET'])
@require_role('admin', 'employee')
def bug_download_all():
    """Download every (optionally filtered) bug report as one combined, readable HTML file."""
    try:
        category = request.args.get('category', '')
        status = request.args.get('status', '')
        severity = request.args.get('severity', '')
        reporter = request.args.get('reporter', '')
        roadmap_only = request.args.get('roadmap', '').lower() in ('true', '1', 'yes')

        query = BugReport.query
        if category in ALLOWED_BUG_CATEGORIES:
            query = query.filter_by(category=category)
        if status in ALLOWED_BUG_STATUSES:
            query = query.filter_by(status=status)
        if severity in ALLOWED_BUG_SEVERITIES:
            query = query.filter_by(severity=severity)
        if reporter:
            query = query.filter_by(reporter_name=reporter)
        if roadmap_only:
            query = query.filter_by(roadmap=True)

        bugs = query.order_by(BugReport.created_at.desc()).all()

        sections = []
        for bug in bugs:
            single = _build_bug_report_html(bug)
            # Pull just the inner container body out of each individual report so we can
            # stack many of them inside one shared page shell, each in its own bordered card.
            start = single.find('<div class="container">')
            end = single.rfind('</div>\n</body>')
            inner = single[start:end] if start != -1 and end != -1 else single
            sections.append(f'<div class="report-card">{inner}</div>')

        generated_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        filters_desc = []
        if category in ALLOWED_BUG_CATEGORIES:
            filters_desc.append(f"category = {category}")
        if status in ALLOWED_BUG_STATUSES:
            filters_desc.append(f"status = {status}")
        if severity in ALLOWED_BUG_SEVERITIES:
            filters_desc.append(f"priority = {severity}")
        if reporter:
            filters_desc.append(f"engineer = {reporter}")
        if roadmap_only:
            filters_desc.append("roadmap only")
        filters_line = f" (filtered by {', '.join(filters_desc)})" if filters_desc else ""

        combined_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>All Bug Reports</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background: #f4f5f7; color: #1f2933; margin: 0; padding: 2rem; }}
  .page-header {{ max-width: 800px; margin: 0 auto 1.5rem auto; }}
  .page-header h1 {{ margin-bottom: 0.2rem; }}
  .page-header p {{ color: #667; font-size: 0.9rem; margin-top: 0; }}
  .report-card {{ max-width: 800px; margin: 0 auto 1.5rem auto; }}
  .container {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 2rem; }}
  h1 {{ margin-top: 0; font-size: 1.5rem; }}
  .meta {{ color: #667; font-size: 0.9rem; margin-bottom: 1.5rem; }}
  .badge {{ display: inline-block; padding: 0.2rem 0.7rem; border-radius: 12px; background: #1971c2; color: #fff; font-size: 0.8rem; font-weight: 600; }}
  .section {{ margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid #eee; }}
  .section h2 {{ font-size: 1.05rem; margin-bottom: 0.6rem; color: #364150; }}
  .row {{ margin: 0.35rem 0; line-height: 1.5; }}
  .row.error {{ color: #c92a2a; }}
  .description {{ white-space: pre-wrap; line-height: 1.6; }}
  .history-entry {{ background: #f8f9fa; border-radius: 6px; padding: 0.8rem 1rem; margin-bottom: 0.8rem; }}
  .history-head {{ display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0.4rem; }}
  .timestamp {{ color: #868e96; font-size: 0.85rem; }}
  .attachment-gallery {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 0.5rem; }}
  .attachment-image {{ margin: 0; width: 220px; }}
  .attachment-image img {{ width: 100%; border-radius: 6px; border: 1px solid #e0e0e0; display: block; }}
  .attachment-image figcaption {{ font-size: 0.78rem; color: #667; margin-top: 0.25rem; word-break: break-all; }}
  .attachment-files {{ list-style: none; padding: 0; margin: 0.5rem 0 0; }}
  .attachment-files li {{ margin: 0.3rem 0; }}
  .attachment-file {{ color: #1971c2; text-decoration: none; font-weight: 500; }}
  .attachment-file:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <div class="page-header">
    <h1>All Bug Reports</h1>
    <p>{len(bugs)} report(s){filters_line} &middot; generated {generated_at}</p>
  </div>
  {''.join(sections)}
</body>
</html>"""

        from io import BytesIO
        html_bytes = BytesIO(combined_html.encode('utf-8'))
        filename = f"all_bug_reports_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"

        return send_file(
            html_bytes,
            mimetype='text/html',
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.error(f"Error downloading all bug reports: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/<bug_id>/download', methods=['GET'])
def bug_download(bug_id):
    """Download a single bug/report entry as a self-contained, readable HTML file."""
    try:
        bug = BugReport.query.get(bug_id)
        if not bug:
            return jsonify({'status': 'error', 'message': 'Bug report not found'}), 404
        if get_jwt().get('role') == 'reporter' and bug.user_id != get_jwt_identity():
            return jsonify({'status': 'error', 'message': 'Forbidden'}), 403

        html_content = _build_bug_report_html(bug)

        from io import BytesIO
        html_bytes = BytesIO(html_content.encode('utf-8'))
        safe_title = ''.join(c if c.isalnum() else '_' for c in (bug.title or 'report')).strip('_').lower()
        filename = f"{safe_title}_{bug.id[:8]}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"

        return send_file(
            html_bytes,
            mimetype='text/html',
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.error(f"Error downloading bug report {bug_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/<bug_id>', methods=['PATCH'])
@require_role('admin', 'employee')
def bug_update(bug_id):
    """Update the status of a bug report.

    When moving to a status that has follow-up fields (In Progress /
    Resolved / Closed), those answers are required and get stored, posted to
    the Odoo task's chatter, and the task's 'Status: ...' tag is updated to
    match. Optional file attachments are stored locally and pushed to the
    Odoo task as well. All Odoo actions are best-effort: a sync failure is
    reported back but never blocks the local status update.

    Expected JSON body:
      status: one of open/in_progress/resolved/closed
      fields: { <field_key>: <answer text>, ... }   (per-status, see
              GET /bugtracker/statuses for what's required per status)
      attachments: [{ filename, content_type, content_b64 }, ...]  (optional)
    """
    try:
        from services import generate_status_update_fields, STATUS_LABELS, BUG_CATEGORY_LABELS

        bug = BugReport.query.get(bug_id)
        if not bug:
            return jsonify({'status': 'error', 'message': 'Bug report not found'}), 404
        data = request.get_json() or {}
        new_status = data.get('status')
        fields = data.get('fields', {}) or {}
        raw_attachments = data.get('attachments', []) or []

        if not new_status:
            return jsonify({'status': 'error', 'message': 'status is required'}), 400
        if new_status not in ALLOWED_BUG_STATUSES:
            return jsonify({'status': 'error', 'message': f'Invalid status. Must be one of {ALLOWED_BUG_STATUSES}'}), 400

        # Validate the status-specific required fields (e.g. Resolution
        # details for Resolved, Reason for Closed).
        field_defs = generate_status_update_fields(new_status)
        missing = [f['label'] for f in field_defs if f.get('required') and not (fields.get(f['key']) or '').strip()]
        if missing:
            return jsonify({
                'status': 'error',
                'message': f"Missing required field(s): {', '.join(missing)}",
            }), 400

        new_attachments_meta = _save_bug_attachments(bug.id, raw_attachments, stage=new_status)

        bug.status = new_status
        bug.attachments = (bug.attachments or []) + new_attachments_meta

        update_entry = {
            'status': new_status,
            'fields': {f['key']: fields.get(f['key'], '') for f in field_defs if fields.get(f['key'])},
            'attachments': new_attachments_meta,
            'odoo_synced': False,
            'odoo_sync_error': None,
            'created_at': datetime.utcnow().isoformat(),
        }

        # Sync the status change to Odoo: retag the task and drop a chatter
        # note summarizing what changed, then attach any new files.
        if bug.odoo_task_id:
            try:
                from services import OdooService
                odoo = OdooService()

                field_lines = "\n".join(
                    f"- {next((fd['label'] for fd in field_defs if fd['key'] == k), k)}: {v}"
                    for k, v in update_entry['fields'].items() if v
                )
                note_html = (
                    f"<b>Status changed to {STATUS_LABELS.get(new_status, new_status)}</b><br/>"
                    + (field_lines.replace('\n', '<br/>') if field_lines else '')
                )

                ok, result = odoo.sync_bug_status(bug.odoo_task_id, new_status, note_html=note_html)
                if ok:
                    update_entry['odoo_synced'] = True
                else:
                    update_entry['odoo_sync_error'] = str(result)
                    bug.odoo_sync_error = str(result)

                for att in raw_attachments:
                    odoo.attach_file_to_task(
                        bug.odoo_task_id,
                        att.get('filename', 'attachment'),
                        att.get('content_b64', ''),
                        att.get('content_type'),
                    )
            except Exception as odoo_err:
                logger.error(f"Odoo status sync failed for bug {bug.id}: {odoo_err}")
                update_entry['odoo_sync_error'] = str(odoo_err)
                bug.odoo_sync_error = str(odoo_err)

        bug.status_updates = (bug.status_updates or []) + [update_entry]

        db.session.commit()
        return jsonify({'status': 'success', 'data': bug.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating bug report {bug_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/<bug_id>/edit', methods=['PATCH'])
@require_role('admin', 'employee')
def bug_edit(bug_id):
    """Let the original reporter revise the content of their own report
    (title, description, severity, category-specific answers). This is
    separate from PATCH /<bug_id>, which is for status-change workflow
    updates, not editing what was originally reported.

    Expected JSON body (all optional, only provided fields are changed):
      title, description, severity, answers,
      attachments: [{ filename, content_type, content_b64 }, ...]  (appended)
    """
    try:
        bug = BugReport.query.get(bug_id)
        if not bug:
            return jsonify({'status': 'error', 'message': 'Bug report not found'}), 404

        data = request.get_json() or {}

        if 'title' in data:
            title = (data.get('title') or '').strip()
            if not title:
                return jsonify({'status': 'error', 'message': 'title cannot be empty'}), 400
            bug.title = title

        if 'description' in data:
            bug.description = data.get('description') or ''

        if 'severity' in data:
            severity = (data.get('severity') or '').lower()
            if severity not in ('critical', 'high', 'medium', 'low'):
                return jsonify({'status': 'error', 'message': 'Invalid severity'}), 400
            bug.severity = severity

        if 'answers' in data:
            bug.answers = data.get('answers') or {}

        raw_attachments = data.get('attachments', []) or []
        if raw_attachments:
            new_attachments_meta = _save_bug_attachments(bug.id, raw_attachments, stage='edit')
            bug.attachments = (bug.attachments or []) + new_attachments_meta

            if bug.odoo_task_id:
                try:
                    from services import OdooService
                    odoo = OdooService()
                    for att in raw_attachments:
                        odoo.attach_file_to_task(
                            bug.odoo_task_id,
                            att.get('filename', 'attachment'),
                            att.get('content_b64', ''),
                            att.get('content_type'),
                        )
                except Exception as odoo_err:
                    logger.error(f"Failed to attach edit files to Odoo task for bug {bug.id}: {odoo_err}")

        db.session.commit()
        return jsonify({'status': 'success', 'data': bug.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error editing bug report {bug_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/sprints', methods=['GET'])
@require_role('admin', 'employee')
def bug_sprint_board():
    """Return the sprint board: sprints 1..MAX_SPRINTS each with their
    assigned reports (up to MAX_ITEMS_PER_SPRINT), plus the Backlog."""
    try:
        reports = BugReport.query.order_by(BugReport.created_at.desc()).all()
        by_sprint = {n: [] for n in range(1, MAX_SPRINTS + 1)}
        backlog = []
        for b in reports:
            if b.sprint and 1 <= b.sprint <= MAX_SPRINTS:
                by_sprint[b.sprint].append(b.to_dict())
            else:
                backlog.append(b.to_dict())

        sprints = [{
            'number': n,
            'items': by_sprint[n],
            'count': len(by_sprint[n]),
            'capacity': MAX_ITEMS_PER_SPRINT,
            'full': len(by_sprint[n]) >= MAX_ITEMS_PER_SPRINT,
        } for n in range(1, MAX_SPRINTS + 1)]

        return jsonify({
            'status': 'success',
            'data': {
                'sprints': sprints,
                'backlog': backlog,
                'max_sprints': MAX_SPRINTS,
                'max_items_per_sprint': MAX_ITEMS_PER_SPRINT,
            },
        }), 200
    except Exception as e:
        logger.error(f"Error building sprint board: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/<bug_id>/sprint', methods=['PATCH'])
@require_role('admin', 'employee')
def bug_assign_sprint(bug_id):
    """Assign (or unassign) a report to the sprint.

    Expected JSON body: { sprint: 1 or null }
    The sprint can hold at most MAX_ITEMS_PER_SPRINT reports. If it's
    already full, the report is placed in the Backlog instead of the
    update being rejected, and the response says so.
    """
    try:
        bug = BugReport.query.get(bug_id)
        if not bug:
            return jsonify({'status': 'error', 'message': 'Bug report not found'}), 404

        data = request.get_json() or {}
        requested = data.get('sprint', None)

        if requested is None:
            bug.sprint = None
            db.session.commit()
            return jsonify({'status': 'success', 'data': bug.to_dict(), 'message': 'Moved to Backlog.'}), 200

        try:
            requested = int(requested)
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'sprint must be an integer 1-{} or null'.format(MAX_SPRINTS)}), 400

        if requested < 1 or requested > MAX_SPRINTS:
            return jsonify({'status': 'error', 'message': f'sprint must be between 1 and {MAX_SPRINTS}'}), 400

        current_count = BugReport.query.filter(
            BugReport.sprint == requested, BugReport.id != bug.id
        ).count()

        if current_count >= MAX_ITEMS_PER_SPRINT:
            bug.sprint = None
            db.session.commit()
            return jsonify({
                'status': 'success',
                'data': bug.to_dict(),
                'message': f'Sprint is full ({MAX_ITEMS_PER_SPRINT} items max) -- moved to Backlog instead.',
            }), 200

        bug.sprint = requested
        db.session.commit()
        return jsonify({'status': 'success', 'data': bug.to_dict(), 'message': 'Assigned to Sprint.'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error assigning sprint for bug {bug_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/<bug_id>/roadmap', methods=['PATCH'])
@require_role('admin', 'employee')
def bug_assign_roadmap(bug_id):
    """Flag (or unflag) a report as planned for the Future Roadmap.

    Expected JSON body: { roadmap: true or false, note: optional string }
    This is just a tag carried on the report itself -- it doesn't move the
    report anywhere. It's meant to be set right on a sprint card ("is this
    also something we want to carry onto the future roadmap?"), so a report
    can be in the active Sprint (or Backlog) *and* flagged for the roadmap
    at the same time. The optional note (e.g. "Target: Q3", "Blocked on
    infra migration") explains why/when; it's cleared whenever the flag is
    turned back off since a stale note on an unflagged report is just noise.
    """
    try:
        bug = BugReport.query.get(bug_id)
        if not bug:
            return jsonify({'status': 'error', 'message': 'Bug report not found'}), 404

        data = request.get_json() or {}
        requested = bool(data.get('roadmap', False))
        note = (data.get('note') or '').strip()[:280]

        bug.roadmap = requested
        bug.roadmap_note = note if requested and note else None
        db.session.commit()

        message = 'Flagged for the Future Roadmap.' if requested else 'Removed from the Future Roadmap.'
        return jsonify({'status': 'success', 'data': bug.to_dict(), 'message': message}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating roadmap flag for bug {bug_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============== Team Updates ("+ Post Update") ==============
# Lightweight posts -- a description plus optional images and file
# attachments -- created from the Sprints toolbar by admin/employee
# accounts, visible to every logged-in user (including reporters) so the
# whole team can see announcements/progress shots. Only the description is
# required; a post with no images or files at all is allowed.

MAX_UPDATE_IMAGES = 10
MAX_UPDATE_ATTACHMENTS = 5
MAX_UPDATE_FILE_SIZE = 8 * 1024 * 1024  # 8MB per image/attachment


def _decode_update_file(item):
    """Decode a {filename, content_type, content_b64} dict into raw bytes,
    or raise ValueError with a user-facing message on bad input."""
    b64 = item.get('content_b64')
    if not b64:
        raise ValueError('Missing file data')
    try:
        raw_bytes = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        raise ValueError(f"Invalid file data for \"{item.get('filename', 'file')}\"")
    if len(raw_bytes) > MAX_UPDATE_FILE_SIZE:
        raise ValueError(f"\"{item.get('filename', 'file')}\" exceeds the 8MB limit")
    return raw_bytes


@bugtracker_bp.route('/updates', methods=['GET'])
def team_updates_list():
    """List posts, newest first. Any logged-in user can view these."""
    try:
        updates = TeamUpdate.query.order_by(TeamUpdate.created_at.desc()).limit(100).all()
        return jsonify({'status': 'success', 'data': [u.to_dict() for u in updates]}), 200
    except Exception as e:
        logger.error(f"Error listing team updates: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/updates', methods=['POST'])
@require_role('admin', 'employee')
def team_updates_create():
    """Create a post. Expected JSON body:
      {
        description: string (required),
        images: [{ filename, content_type, content_b64 }, ...] (optional, up to 10),
        attachments: [{ filename, content_type, content_b64 }, ...] (optional, up to 5)
      }
    A description with no images and no attachments is a valid post.
    """
    try:
        data = request.get_json() or {}
        description = (data.get('description') or '').strip()
        if not description:
            return jsonify({'status': 'error', 'message': 'Description is required'}), 400
        if len(description) > 2000:
            return jsonify({'status': 'error', 'message': 'Description is too long (max 2000 characters)'}), 400

        raw_images = data.get('images') or []
        raw_attachments = data.get('attachments') or []

        if len(raw_images) > MAX_UPDATE_IMAGES:
            return jsonify({'status': 'error', 'message': f'You can attach up to {MAX_UPDATE_IMAGES} images'}), 400
        if len(raw_attachments) > MAX_UPDATE_ATTACHMENTS:
            return jsonify({'status': 'error', 'message': f'You can attach up to {MAX_UPDATE_ATTACHMENTS} files'}), 400

        author = _current_user()

        update = TeamUpdate(
            user_id=author.id if author else None,
            author_name=(author.name if author else 'Unknown'),
            description=description,
        )
        db.session.add(update)

        try:
            for idx, image in enumerate(raw_images):
                raw_bytes = _decode_update_file(image)
                db.session.add(TeamUpdateImage(
                    update=update,
                    filename=image.get('filename', 'image'),
                    content_type=image.get('content_type') or 'application/octet-stream',
                    size=len(raw_bytes),
                    data=raw_bytes,
                    position=idx,
                ))
            for attachment in raw_attachments:
                raw_bytes = _decode_update_file(attachment)
                db.session.add(TeamUpdateAttachment(
                    update=update,
                    filename=attachment.get('filename', 'attachment'),
                    content_type=attachment.get('content_type') or 'application/octet-stream',
                    size=len(raw_bytes),
                    data=raw_bytes,
                ))
        except ValueError as ve:
            db.session.rollback()
            return jsonify({'status': 'error', 'message': str(ve)}), 400

        db.session.commit()
        return jsonify({'status': 'success', 'data': update.to_dict(), 'message': 'Update posted.'}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating team update: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/updates/<update_id>/image', methods=['GET'])
def team_updates_image(update_id):
    """Legacy: stream a pre-multi-image post's single image back inline."""
    try:
        update = TeamUpdate.query.get(update_id)
        if not update or update.image_data is None:
            return jsonify({'status': 'error', 'message': 'Image not found'}), 404

        from io import BytesIO
        return send_file(
            BytesIO(update.image_data),
            mimetype=update.image_content_type or 'application/octet-stream',
            as_attachment=False,
            download_name=update.image_filename or 'image',
        )
    except Exception as e:
        logger.error(f"Error viewing update image {update_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/updates/images/<image_id>', methods=['GET'])
def team_update_image_view(image_id):
    """Stream one image from a post's gallery back inline."""
    try:
        image = TeamUpdateImage.query.get(image_id)
        if not image or image.data is None:
            return jsonify({'status': 'error', 'message': 'Image not found'}), 404

        from io import BytesIO
        return send_file(
            BytesIO(image.data),
            mimetype=image.content_type or 'application/octet-stream',
            as_attachment=False,
            download_name=image.filename or 'image',
        )
    except Exception as e:
        logger.error(f"Error viewing update image {image_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/updates/attachments/<attachment_id>', methods=['GET'])
def team_update_attachment_view(attachment_id):
    """Open an update's file attachment inline (in a new tab)."""
    try:
        attachment = TeamUpdateAttachment.query.get(attachment_id)
        if not attachment or attachment.data is None:
            return jsonify({'status': 'error', 'message': 'Attachment not found'}), 404

        from io import BytesIO
        return send_file(
            BytesIO(attachment.data),
            mimetype=attachment.content_type or 'application/octet-stream',
            as_attachment=False,
            download_name=attachment.filename or 'attachment',
        )
    except Exception as e:
        logger.error(f"Error viewing update attachment {attachment_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/updates/attachments/<attachment_id>/download', methods=['GET'])
def team_update_attachment_download(attachment_id):
    """Force-download an update's file attachment with its original filename."""
    try:
        attachment = TeamUpdateAttachment.query.get(attachment_id)
        if not attachment or attachment.data is None:
            return jsonify({'status': 'error', 'message': 'Attachment not found'}), 404

        from io import BytesIO
        return send_file(
            BytesIO(attachment.data),
            mimetype=attachment.content_type or 'application/octet-stream',
            as_attachment=True,
            download_name=attachment.filename or 'attachment',
        )
    except Exception as e:
        logger.error(f"Error downloading update attachment {attachment_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/updates/<update_id>', methods=['DELETE'])
def team_updates_delete(update_id):
    """Delete a post. Allowed for the original poster or any admin/employee."""
    try:
        update = TeamUpdate.query.get(update_id)
        if not update:
            return jsonify({'status': 'error', 'message': 'Update not found'}), 404

        role = get_jwt().get('role')
        if role == 'reporter' and update.user_id != get_jwt_identity():
            return jsonify({'status': 'error', 'message': 'Forbidden'}), 403

        db.session.delete(update)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Update deleted.'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting team update {update_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/submit', methods=['POST'])
def bug_submit():
    """Submit a new bug-tracker entry.

    Creates a local BugReport row and optionally sends a notification email
    with the attachments included. Email failures are reported back but
    never block the local record from being saved.

    Expected JSON body:
      category: one of general/bug/feature/observation
      title: string
      description: string (free-form problem statement)
      severity: critical/high/medium/low
      reporter_name, reporter_email
      answers: { <question_key>: <answer text>, ... }
      attachments: [{ filename, content_type, content_b64 }, ...]   (optional)
      send_email: bool
      email_recipients: "a@x.com, b@y.com"                          (if send_email)
    """
    try:
        data = request.get_json() or {}
        category = (data.get('category') or '').strip().lower()
        if category not in ALLOWED_BUG_CATEGORIES:
            return jsonify({'status': 'error', 'message': f'category must be one of {ALLOWED_BUG_CATEGORIES}'}), 400

        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'status': 'error', 'message': 'title is required'}), 400

        description = data.get('description', '')
        severity = (data.get('severity') or 'medium').lower()
        reporter_name = data.get('reporter_name', '')
        reporter_email = data.get('reporter_email', '')
        answers = data.get('answers', {}) or {}
        raw_attachments = data.get('attachments', []) or []
        send_email = bool(data.get('send_email'))
        email_recipients_raw = data.get('email_recipients', '')

        current_user = _current_user()
        # For self-registered reporters, always use the account's own
        # name/email -- never trust client input here, since it's exactly
        # what "All Reports" ownership scoping (bug_list/bug_detail) keys
        # off of.
        if current_user and current_user.role == 'reporter':
            reporter_name = current_user.name
            reporter_email = current_user.email

        bug = BugReport(
            category=category,
            title=title,
            description=description,
            severity=severity,
            status='open',
            user_id=current_user.id if current_user else None,
            reporter_name=reporter_name,
            reporter_email=reporter_email,
            answers=answers,
            attachments=[],
            project_name=BUG_PROJECT_NAME,
        )
        db.session.add(bug)
        db.session.commit()

        attachments_meta = _save_bug_attachments(bug.id, raw_attachments, stage='initial')
        bug.attachments = attachments_meta
        db.session.commit()

        # Build a consolidated description for the notification email from the answers
        answer_lines = "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in answers.items() if v)
        from services import BUG_CATEGORY_LABELS
        full_description = (
            f"Category: {BUG_CATEGORY_LABELS.get(category, category)}\n"
            f"Severity: {severity.title()}\n"
            f"Reporter: {reporter_name or 'Unknown'} ({reporter_email or 'no email'})\n\n"
            f"{description}\n\n"
            f"{answer_lines}"
        ).strip()

        # Optional email notification (best-effort)
        if send_email:
            recipients = [r.strip() for r in email_recipients_raw.split(',') if r.strip()] \
                if isinstance(email_recipients_raw, str) else list(email_recipients_raw or [])
            if recipients:
                from alerting import AlertService
                email_attachments = [{
                    'filename': a.get('filename', 'attachment'),
                    'content_b64': a.get('content_b64', ''),
                    'mimetype': a.get('content_type'),
                } for a in raw_attachments]
                ok, msg = AlertService().send_email_with_attachments(
                    recipients,
                    subject=f"[OSDBcortex Bug Tracker] {BUG_CATEGORY_LABELS.get(category, category)}: {title}",
                    body=full_description,
                    attachments=email_attachments,
                )
                bug.email_sent = ok
                bug.email_recipients = ", ".join(recipients)
                if not ok:
                    logger.warning(f"Bug tracker email failed for bug {bug.id}: {msg}")
                db.session.commit()

        return jsonify({'status': 'success', 'data': bug.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting bug report: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============== Team Task Assignment Routes (OSDBcortex) ==============
# Shown below the 4 bug-tracker categories: assign a task directly to one of
# the 3 fixed teams, optionally emailing that team's members by default.

ALLOWED_TEAM_KEYS = ('team1', 'team2', 'team3')


@bugtracker_bp.route('/teams', methods=['GET'])
@require_role('admin', 'employee')
def bug_teams():
    """Return the 3 fixed teams and their members."""
    try:
        from services import get_team_definitions
        return jsonify({'status': 'success', 'data': get_team_definitions()}), 200
    except Exception as e:
        logger.error(f"Error fetching teams: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/team-tasks', methods=['GET'])
@require_role('admin', 'employee')
def team_task_list():
    """List team-assigned tasks, optionally filtered by team, newest first."""
    try:
        team_key = request.args.get('team_key', '')
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 20)), 100)

        query = TeamTask.query
        if team_key in ALLOWED_TEAM_KEYS:
            query = query.filter_by(team_key=team_key)
        query = query.order_by(TeamTask.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'status': 'success',
            'data': [t.to_dict() for t in pagination.items],
            'page': page,
            'pages': pagination.pages,
            'total': pagination.total,
        }), 200
    except Exception as e:
        logger.error(f"Error listing team tasks: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bugtracker_bp.route('/team-tasks/submit', methods=['POST'])
@require_role('admin', 'employee')
def team_task_submit():
    """Assign a task to one of the 3 fixed teams.

    Expected JSON body:
      team_key: one of team1/team2/team3
      description: string (required)
      attachments: [{ filename, content_type, content_b64 }, ...]  (optional)
      send_email: bool
      email_recipients: "a@x.com, b@y.com"  (optional override; defaults to
                        the team's member emails when send_email is true and
                        this is left blank)
      assigned_by_name, assigned_by_email: optional, who created the task
    """
    try:
        from services import get_team_member_emails, TEAM_DEFINITIONS

        data = request.get_json() or {}
        team_key = (data.get('team_key') or '').strip().lower()
        if team_key not in ALLOWED_TEAM_KEYS:
            return jsonify({'status': 'error', 'message': f'team_key must be one of {ALLOWED_TEAM_KEYS}'}), 400

        description = (data.get('description') or '').strip()
        if not description:
            return jsonify({'status': 'error', 'message': 'description is required'}), 400

        raw_attachments = data.get('attachments', []) or []
        send_email = bool(data.get('send_email'))
        email_recipients_raw = data.get('email_recipients', '')
        assigned_by_name = data.get('assigned_by_name', '')
        assigned_by_email = data.get('assigned_by_email', '')

        attachments_meta = [{
            'filename': a.get('filename', 'attachment'),
            'content_type': a.get('content_type', 'application/octet-stream'),
            'size': len(a.get('content_b64', '') or '') * 3 // 4,
        } for a in raw_attachments]

        task = TeamTask(
            team_key=team_key,
            description=description,
            attachments=attachments_meta,
            assigned_by_name=assigned_by_name,
            assigned_by_email=assigned_by_email,
            send_email=send_email,
        )
        db.session.add(task)
        db.session.commit()

        if send_email:
            # Default recipients are the team's own members; an explicit
            # email_recipients value (if provided) overrides that default.
            if isinstance(email_recipients_raw, str) and email_recipients_raw.strip():
                recipients = [r.strip() for r in email_recipients_raw.split(',') if r.strip()]
            elif isinstance(email_recipients_raw, (list, tuple)) and email_recipients_raw:
                recipients = list(email_recipients_raw)
            else:
                recipients = get_team_member_emails(team_key)

            if recipients:
                from alerting import AlertService
                team_label = TEAM_DEFINITIONS.get(team_key, {}).get('label', team_key)
                body = (
                    f"Team: {team_label}\n"
                    f"Assigned by: {assigned_by_name or 'Unknown'} ({assigned_by_email or 'no email'})\n\n"
                    f"{description}"
                )
                email_attachments = [{
                    'filename': a.get('filename', 'attachment'),
                    'content_b64': a.get('content_b64', ''),
                    'mimetype': a.get('content_type'),
                } for a in raw_attachments]
                ok, msg = AlertService().send_email_with_attachments(
                    recipients,
                    subject=f"[OSDBcortex Task Assignment] {team_label}",
                    body=body,
                    attachments=email_attachments,
                )
                task.email_sent = ok
                task.email_recipients = ", ".join(recipients)
                if not ok:
                    task.email_error = msg
                    logger.warning(f"Team task email failed for task {task.id}: {msg}")
                db.session.commit()

        return jsonify({'status': 'success', 'data': task.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting team task: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
