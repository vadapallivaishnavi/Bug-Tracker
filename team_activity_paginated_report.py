import xmlrpc.client
import os
import smtplib
import ssl
import argparse
from email.message import EmailMessage
import requests
import html
import re
import json
import yaml
from datetime import datetime, timedelta
import plotly
import plotly.figure_factory as ff
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from collections import defaultdict

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

ODOO_URL = config["odoo"]["url"]
ODOO_DB = config["odoo"]["db"]
ODOO_USER = config["odoo"]["user"]
ODOO_PASS = config["odoo"]["password"]

provider = config["llm"]["provider"]
llm_cfg = config["llm"]["services"][provider]
LLM_API_URL = llm_cfg["api_url"]
LLM_MODEL = llm_cfg["model"]
LLM_API_KEY = llm_cfg["api_key"]
LLM_MAX_TOKENS = llm_cfg["max_tokens"]

EXCLUDED_USERS = config.get("report", {}).get("excluded_users", [])
SHIFT_HOURS = float(config.get("report", {}).get("shift_hours", 8.3))

SMTP_CONFIG = config.get("smtp", {})
REPORT_RECIPIENTS = ["praveena.s@opensource-db.com", "sivasankar@opensource-db.com"]


def send_email(html_content, recipients, hours):
    msg = EmailMessage()
    msg["Subject"] = f"Team Activity Report - Last {hours} Hours"
    msg["From"] = "admin@localhost"
    msg["To"] = ", ".join(recipients)
    msg.set_content("Please view this HTML report in your email client.")
    msg.add_alternative(html_content, subtype="html")

    eml_file = "team_activity_report.eml"
    with open(eml_file, "w") as f:
        f.write(msg.as_string())
    print(f"Email saved to {eml_file}")

    try:
        import subprocess
        with open(eml_file) as f:
            result = subprocess.run(
                ["/usr/sbin/sendmail", "-t"],
                stdin=f,
                capture_output=True,
                text=True,
                timeout=10
            )
        if result.returncode == 0:
            print(f"Email sent successfully to {recipients}")
        else:
            print(f"sendmail failed: {result.stderr}, email saved to {eml_file}")
    except FileNotFoundError:
        print(f"sendmail not available, email saved to {eml_file}")
    except subprocess.TimeoutExpired:
        print(f"sendmail timed out, email saved to {eml_file}")

def clean_html(value):
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()

def format_log_notes(value):
    if not value:
        return ""
    value = html.unescape(value)
    value = value.replace('\n', '<br>')
    value = value.replace('\t', '&nbsp;&nbsp;&nbsp;&nbsp;')
    value = re.sub(r'(https?://[^\s<]+)', r'<a href="\1" target="_blank">\1</a>', value)
    return value

def calculate_age(create_date):
    if not create_date:
        return ""
    try:
        created = datetime.strptime(create_date[:19], "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        delta = now - created
        days = delta.days
        hours = delta.seconds // 3600
        if days > 30:
            return f"{days // 30}mo"
        elif days > 0:
            return f"{days}d"
        elif hours > 0:
            return f"{hours}h"
        else:
            return "Just now"
    except:
        return ""

def connect_odoo():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASS, {})
    if not uid:
        raise Exception("Odoo authentication failed")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models

def fetch_users(models, uid):
    user_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "res.users", "search", [[("share", "=", False)]]
    )
    users = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "res.users", "read", [user_ids],
        {"fields": ["id", "name", "email"]}
    )
    return {u["id"]: u for u in users}

def fetch_recent_timesheets(models, uid, hours=24):
    now = datetime.now()
    since = now - timedelta(hours=hours)

    timesheet_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "account.analytic.line", "search", [[
            ("date", ">=", since.strftime("%Y-%m-%d")),
            ("date", "<=", now.strftime("%Y-%m-%d")),
        ]]
    )
    timesheets = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "account.analytic.line", "read", [timesheet_ids],
        {"fields": ["id", "name", "unit_amount", "date", "user_id", "project_id", "task_id", "write_date"]}
    )
    return timesheets

def fetch_all_tasks_for_users(models, uid, user_ids):
    if not user_ids:
        return []
    task_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "project.task", "search", [[
            ("user_ids", "in", user_ids),
        ]]
    )
    if not task_ids:
        return []
    tasks = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "project.task", "read", [task_ids],
        {"fields": ["id", "name", "description", "project_id", "user_ids", "create_date", "write_date", "parent_id", "child_ids", "date_deadline", "progress", "stage_id", "priority", "milestone_id"]}
    )
    return tasks

def fetch_projects(models, uid, project_ids):
    if not project_ids:
        return {}
    projects = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "project.project", "read", [project_ids], {"fields": ["id", "name"]}
    )
    return {p['id']: p['name'] for p in projects}

def fetch_milestones(models, uid, milestone_ids):
    if not milestone_ids:
        return {}
    milestones = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "project.milestone", "read", [list(set(milestone_ids))],
        {"fields": ["id", "name", "deadline"]}
    )
    return {m['id']: m for m in milestones}

def get_priority_label(priority):
    priority_map = {
        '0': 'P3',
        '1': 'P2',
        '2': 'P1',
    }
    return priority_map.get(str(priority), 'P3')

def fetch_tasks(models, uid, task_ids):
    if not task_ids:
        return []
    tasks = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "project.task", "read", [list(set(task_ids))],
        {"fields": ["id", "name", "description", "project_id", "user_ids", "create_date", "write_date", "parent_id", "child_ids", "date_deadline", "progress", "stage_id", "create_uid", "priority", "milestone_id"]}
    )
    return tasks

def fetch_task_logs(models, uid, task_ids):
    if not task_ids:
        return []
    log_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "mail.message", "search", [[
            ("model", "=", "project.task"),
            ("res_id", "in", list(set(task_ids))),
            ("message_type", "=", "comment"),
        ]]
    )
    logs = models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        "mail.message", "read", [log_ids],
        {"fields": ["id", "date", "body", "author_id", "res_id"]}
    )
    return logs

def summarize_with_llm(logs, task_description):
    log_texts = []
    authors = set()

    for l in logs:
        body = l.get("body", "")
        if body:
            text = clean_html(body)
            log_texts.append(text)
            author = l.get("author_id")
            if author:
                authors.add(author[1] if isinstance(author, list) else str(author))

    if not log_texts:
        return {"summary": "No log entries to summarize.", "authors": ""}

    combined_logs = "\n\n".join([f"- {text}" for text in log_texts[:10]])
    author_str = ", ".join(list(authors)[:3]) if authors else "Unknown"

    prompt = f"""
You are a project management analyst. Summarize the following task logs and description.

Task Description:
{task_description or "No description provided"}

Log Entries:
{combined_logs}

Provide a concise 2-3 sentence summary of what was accomplished based on the logs.
"""

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": LLM_MAX_TOKENS
    }

    try:
        resp = requests.post(
            LLM_API_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LLM_API_KEY}"
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return {"summary": content.strip(), "authors": author_str}
    except Exception as e:
        return {"summary": f"LLM summary unavailable: {str(e)}", "authors": author_str}

def calculate_shift_metrics(total_hours, shift_hours):
    utilization_pct = (total_hours / shift_hours * 100) if shift_hours else 0
    if utilization_pct < 70:
        band = "under"
        status = "Needs Focus"
    elif utilization_pct <= 100:
        band = "healthy"
        status = "On Track"
    else:
        band = "over"
        status = "Over Shift"

    return {
        "logged": round(total_hours, 2),
        "target": round(shift_hours, 2),
        "remaining": round(max(shift_hours - total_hours, 0), 2),
        "overtime": round(max(total_hours - shift_hours, 0), 2),
        "utilization": round(utilization_pct, 1),
        "status": status,
        "band": band,
    }

def build_user_task_summary(data):
    summary = {
        'total': 0,
        'main': 0,
        'subtasks': 0,
        'open': 0,
        'progress': 0,
        'done': 0,
        'cancel': 0,
        'p1': 0,
        'p2': 0,
        'p3': 0,
        'top_tasks': [],
    }

    all_tasks = []
    for _, project_data in data.get('projects', {}).items():
        all_tasks.extend(project_data.get('tasks', []))

    seen = set()
    deduped = []
    for task in all_tasks:
        tid = task.get('id')
        if tid in seen:
            continue
        seen.add(tid)
        deduped.append(task)

    summary['total'] = len(deduped)
    summary['main'] = len([t for t in deduped if not t.get('is_subtask')])
    summary['subtasks'] = len([t for t in deduped if t.get('is_subtask')])

    for task in deduped:
        stage = (task.get('stage', '') or '').lower()
        if 'done' in stage or 'close' in stage:
            summary['done'] += 1
        elif 'progress' in stage or 'review' in stage or 'develop' in stage:
            summary['progress'] += 1
        elif 'cancel' in stage:
            summary['cancel'] += 1
        else:
            summary['open'] += 1

        p = get_priority_label(task.get('priority', '0')).lower()
        if p == 'p1':
            summary['p1'] += 1
        elif p == 'p2':
            summary['p2'] += 1
        else:
            summary['p3'] += 1

    summary['top_tasks'] = sorted(deduped, key=lambda x: x.get('hours', 0), reverse=True)[:5]
    return summary

def build_task_log_summaries(data):
    rows = []
    seen = set()

    for project_name, project_data in data.get('projects', {}).items():
        for task in project_data.get('tasks', []):
            task_id = task.get('id')
            if task_id in seen:
                continue
            seen.add(task_id)

            llm_result = task.get('llm_summary')
            summary_text = "No log entries to summarize."
            authors = ""

            if isinstance(llm_result, dict):
                summary_text = llm_result.get('summary', summary_text) or summary_text
                authors = llm_result.get('authors', '') or ''
            elif isinstance(llm_result, str) and llm_result.strip():
                summary_text = llm_result.strip()

            rows.append({
                'title': task.get('name', 'Untitled Task'),
                'project': project_name,
                'hours': float(task.get('hours', 0) or 0),
                'summary': summary_text,
                'authors': authors,
            })

    rows.sort(key=lambda x: x['hours'], reverse=True)
    return rows

def normalize_stage_bucket(stage_name):
    stage = (stage_name or '').lower()
    if 'done' in stage or 'close' in stage:
        return 'Done'
    if 'progress' in stage or 'review' in stage or 'develop' in stage:
        return 'In Progress'
    if 'cancel' in stage:
        return 'Cancelled'
    return 'Open'

def build_user_recent_activity_map(timesheets_5d, users, all_task_map, project_names):
    # Aggregate by user + task + day to keep the chart readable.
    aggregate = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    for ts in timesheets_5d:
        user_data = ts.get('user_id')
        task_data = ts.get('task_id')
        if not user_data or not task_data:
            continue

        user_id = user_data[0]
        task_id = task_data[0]
        if user_id not in users:
            continue

        date_str = (ts.get('date', '') or '')[:10]
        if not date_str:
            continue

        user_name = users[user_id]['name']
        aggregate[user_name][task_id][date_str] += float(ts.get('unit_amount', 0) or 0)

    result = {}
    for user_name, task_map in aggregate.items():
        rows = []
        for task_id, date_map in task_map.items():
            task = all_task_map.get(task_id, {})
            stage_name = task.get('stage_id', [None, 'Unknown'])
            stage_name = stage_name[1] if isinstance(stage_name, list) and len(stage_name) > 1 else 'Unknown'
            stage_bucket = normalize_stage_bucket(stage_name)

            task_name = task.get('name', f'Task #{task_id}')
            if len(task_name) > 52:
                task_name = task_name[:49] + '...'

            project_data = task.get('project_id')
            project_name = 'No Project'
            if isinstance(project_data, list) and project_data:
                project_name = project_names.get(project_data[0], project_data[1] if len(project_data) > 1 else 'No Project')

            for date_str, hours in date_map.items():
                rows.append({
                    'task_id': task_id,
                    'task_name': task_name,
                    'date': date_str,
                    'hours': round(hours, 2),
                    'stage': stage_name,
                    'stage_bucket': stage_bucket,
                    'project_name': project_name,
                })
        result[user_name] = rows
    return result

def generate_recent_task_timeline_chart(user_name, activity_rows):
    if not activity_rows:
        return "<div style='padding:14px; color:#64748b;'>No task activity found in the last 5 days.</div>"

    stage_colors = {
        'Open': '#1971c2',
        'In Progress': '#f08c00',
        'Done': '#2b8a3e',
        'Cancelled': '#c92a2a',
    }

    task_date_hours = defaultdict(lambda: defaultdict(float))
    task_status = {}
    for row in activity_rows:
        hours = float(row.get('hours', 0) or 0)
        if hours <= 0:
            continue
        task_date_hours[row['task_name']][row['date']] += hours
        task_status[row['task_name']] = row.get('stage_bucket', 'Open')

    task_totals = sorted(
        [(task_name, sum(date_map.values())) for task_name, date_map in task_date_hours.items()],
        key=lambda x: x[1],
        reverse=True,
    )[:12]

    selected_tasks = [task_name for task_name, _ in task_totals]
    if not selected_tasks:
        return "<div style='padding:14px; color:#64748b;'>No non-zero task activity found in the last 5 days.</div>"

    gantt_rows = []
    for task_name in selected_tasks:
        date_hours = task_date_hours.get(task_name, {})
        if not date_hours:
            continue

        sorted_dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in date_hours.keys())
        segment_start = sorted_dates[0]
        segment_end = sorted_dates[0]
        segment_hours = date_hours.get(segment_start.strftime("%Y-%m-%d"), 0)

        for cur in sorted_dates[1:]:
            prev = segment_end
            if (cur - prev).days == 1:
                segment_end = cur
                segment_hours += date_hours.get(cur.strftime("%Y-%m-%d"), 0)
                continue

            finish_date = segment_end + timedelta(days=1)
            label = task_name if segment_hours <= 0 else f"{task_name} ({segment_hours:.1f}h)"
            gantt_rows.append({
                'Task': label,
                'Start': segment_start.strftime("%Y-%m-%d"),
                'Finish': finish_date.strftime("%Y-%m-%d"),
                'Resource': task_status.get(task_name, 'Open'),
            })

            segment_start = cur
            segment_end = cur
            segment_hours = date_hours.get(cur.strftime("%Y-%m-%d"), 0)

        finish_date = segment_end + timedelta(days=1)
        label = task_name if segment_hours <= 0 else f"{task_name} ({segment_hours:.1f}h)"
        gantt_rows.append({
            'Task': label,
            'Start': segment_start.strftime("%Y-%m-%d"),
            'Finish': finish_date.strftime("%Y-%m-%d"),
            'Resource': task_status.get(task_name, 'Open'),
        })

    if not gantt_rows:
        return "<div style='padding:14px; color:#64748b;'>No activity periods found for Gantt timeline.</div>"

    fig = ff.create_gantt(
        gantt_rows,
        index_col='Resource',
        colors=stage_colors,
        show_colorbar=True,
        group_tasks=True,
        showgrid_x=True,
        showgrid_y=True,
        title='5-Day Activity Periods (Gantt)'
    )

    timeline_height = min(360, max(240, 58 + len(gantt_rows) * 16))
    fig.update_layout(
        height=timeline_height,
        margin=dict(l=18, r=18, t=55, b=16),
        paper_bgcolor='white',
        plot_bgcolor='white',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
    )
    fig.update_xaxes(showgrid=True, gridcolor='#edf2f7', tickformat='%b %d')
    fig.update_yaxes(showgrid=True, gridcolor='#edf2f7')

    return plotly.io.to_html(fig, full_html=False, include_plotlyjs='cdn')

def generate_project_criticality_heatmap_html(project_criticality_rows):
    if not project_criticality_rows:
        return "<div style='padding:14px; color:#64748b;'>No project effort data found in the last 5 days.</div>"

    sorted_rows = sorted(project_criticality_rows, key=lambda x: x['total'], reverse=True)[:18]
    y_projects = [r['project_name'] for r in sorted_rows]
    z_matrix = [[r['p1'], r['p2'], r['p3']] for r in sorted_rows]

    fig = go.Figure(
        data=go.Heatmap(
            z=z_matrix,
            x=['P1 (Critical)', 'P2 (High)', 'P3 (Normal)'],
            y=y_projects,
            colorscale='YlOrRd',
            colorbar=dict(title='Hours'),
            hovertemplate='<b>%{y}</b><br>%{x}<br>Effort: %{z:.2f}h<extra></extra>'
        )
    )
    fig.update_layout(
        title='Project Criticality vs Effort (Last 5 Days)',
        height=max(360, 130 + len(y_projects) * 24),
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor='white',
        plot_bgcolor='white',
    )
    fig.update_xaxes(side='top')

    return plotly.io.to_html(fig, full_html=False, include_plotlyjs='cdn')

def build_top_projects_summary_html(project_hours_5d, user_tasks_data):
    if not project_hours_5d:
        return "<div style='padding:14px; color:#64748b;'>No project data found.</div>"

    summary_pool = defaultdict(list)
    seen_task_ids = set()

    for user_data in user_tasks_data.values():
        for project_name, project_data in user_data.get('projects', {}).items():
            for task in project_data.get('tasks', []):
                task_id = task.get('id')
                if not task_id or task_id in seen_task_ids:
                    continue
                seen_task_ids.add(task_id)

                llm_result = task.get('llm_summary')
                if isinstance(llm_result, dict):
                    summary_text = (llm_result.get('summary') or '').strip()
                else:
                    summary_text = (llm_result or '').strip()

                if not summary_text or summary_text.lower().startswith('no log entries'):
                    continue

                summary_pool[project_name].append({
                    'task_name': task.get('name', 'Task'),
                    'hours': float(task.get('hours', 0) or 0),
                    'summary': summary_text,
                })

    top_projects = sorted(project_hours_5d.items(), key=lambda x: x[1], reverse=True)[:5]

    cards = []
    for project_name, hours in top_projects:
        notes = sorted(summary_pool.get(project_name, []), key=lambda x: x['hours'], reverse=True)[:2]
        if notes:
            note_lines = []
            for note in notes:
                short_summary = note['summary']
                if len(short_summary) > 210:
                    short_summary = short_summary[:207] + '...'
                note_lines.append(f"<li><strong>{html.escape(note['task_name'])}</strong>: {html.escape(short_summary)}</li>")
            notes_html = f"<ul>{''.join(note_lines)}</ul>"
        else:
            notes_html = "<div class='project-note-empty'>No summarized notes available.</div>"

        cards.append(f"""
            <div class='project-summary-card'>
                <div class='project-summary-head'>
                    <span class='project-summary-name'>{html.escape(project_name)}</span>
                    <span class='project-summary-hours'>{hours:.1f}h</span>
                </div>
                <div class='project-summary-notes'>{notes_html}</div>
            </div>
        """)

    return f"<div class='project-summary-grid'>{''.join(cards)}</div>"

def generate_project_bubble_chart_html(project_hours_5d, timeline_label='Last 5 Days'):
    if not project_hours_5d:
        return "<div style='padding:14px; color:#64748b;'>No project effort data found for bubble chart.</div>"

    rows = sorted(project_hours_5d.items(), key=lambda x: x[1], reverse=True)[:12]
    max_hours = max(h for _, h in rows) if rows else 1

    fig = go.Figure()
    for idx, (project_name, hours) in enumerate(rows):
        bubble_size = 16 + (hours / max_hours) * 34
        fig.add_trace(
            go.Scatter(
                x=[hours],
                y=[len(rows) - idx],
                mode='markers',
                name=project_name,
                marker=dict(size=bubble_size, sizemode='diameter', opacity=0.78),
                hovertemplate='<b>%{text}</b><br>Hours: %{x:.2f}h<extra></extra>',
                text=[project_name],
                showlegend=True,
            )
        )

    fig.update_layout(
        title=f'Projects Worked vs Time (Bubble) - {timeline_label}',
        height=360,
        margin=dict(l=20, r=210, t=62, b=20),
        paper_bgcolor='white',
        plot_bgcolor='white',
        xaxis=dict(title=f'Hours Logged ({timeline_label})', gridcolor='#e9ecef'),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        legend=dict(orientation='v', xanchor='left', x=1.02, yanchor='top', y=1.0, font=dict(size=10)),
        annotations=[
            dict(
                x=1.0,
                y=1.13,
                xref='paper',
                yref='paper',
                xanchor='right',
                showarrow=False,
                text=f'<b>Hours Window:</b> {timeline_label}',
                font=dict(size=11, color='#334155'),
            )
        ],
    )

    return plotly.io.to_html(fig, full_html=False, include_plotlyjs='cdn')

def generate_projects_tasks_gantt_html(recent_activity_map):
    if not recent_activity_map:
        return "<div style='padding:14px; color:#64748b;'>No recent activity available for project/task Gantt.</div>"

    project_task_dates = defaultdict(set)
    project_task_hours = defaultdict(float)

    for rows in recent_activity_map.values():
        for row in rows:
            hours = float(row.get('hours', 0) or 0)
            if hours <= 0:
                continue
            project_name = row.get('project_name', 'No Project')
            task_name = row.get('task_name', 'Task')
            date_str = row.get('date', '')
            if not date_str:
                continue
            key = (project_name, task_name)
            project_task_dates[key].add(date_str)
            project_task_hours[key] += hours

    project_grouped = defaultdict(list)
    for (project_name, task_name), hours in project_task_hours.items():
        project_grouped[project_name].append((task_name, hours))

    task_keep_per_project = 4
    selected_keys = []
    grouped_other_dates = defaultdict(set)

    for project_name, task_rows in project_grouped.items():
        sorted_rows = sorted(task_rows, key=lambda x: x[1], reverse=True)
        keep_rows = sorted_rows[:task_keep_per_project]
        other_rows = sorted_rows[task_keep_per_project:]

        for task_name, _ in keep_rows:
            selected_keys.append((project_name, task_name))

        for task_name, _ in other_rows:
            grouped_other_dates[project_name].update(project_task_dates.get((project_name, task_name), set()))

    # Keep the chart concise across all projects.
    selected_keys.sort(key=lambda key: project_task_hours.get(key, 0), reverse=True)
    selected_keys = selected_keys[:48]

    gantt_rows = []
    for project_name, task_name in selected_keys:
        date_set = project_task_dates.get((project_name, task_name), set())
        if not date_set:
            continue

        sorted_dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in date_set)
        segment_start = sorted_dates[0]
        segment_end = sorted_dates[0]

        for cur in sorted_dates[1:]:
            if (cur - segment_end).days == 1:
                segment_end = cur
                continue

            gantt_rows.append({
                'Task': f"{project_name} :: {task_name}",
                'Start': segment_start.strftime("%Y-%m-%d"),
                'Finish': (segment_end + timedelta(days=1)).strftime("%Y-%m-%d"),
                'Resource': project_name,
            })
            segment_start = cur
            segment_end = cur

        gantt_rows.append({
            'Task': f"{project_name} :: {task_name}",
            'Start': segment_start.strftime("%Y-%m-%d"),
            'Finish': (segment_end + timedelta(days=1)).strftime("%Y-%m-%d"),
            'Resource': project_name,
        })

    for project_name, date_set in grouped_other_dates.items():
        if not date_set:
            continue

        sorted_dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in date_set)
        segment_start = sorted_dates[0]
        segment_end = sorted_dates[0]

        for cur in sorted_dates[1:]:
            if (cur - segment_end).days == 1:
                segment_end = cur
                continue

            gantt_rows.append({
                'Task': f"{project_name} :: Others",
                'Start': segment_start.strftime("%Y-%m-%d"),
                'Finish': (segment_end + timedelta(days=1)).strftime("%Y-%m-%d"),
                'Resource': project_name,
            })
            segment_start = cur
            segment_end = cur

        gantt_rows.append({
            'Task': f"{project_name} :: Others",
            'Start': segment_start.strftime("%Y-%m-%d"),
            'Finish': (segment_end + timedelta(days=1)).strftime("%Y-%m-%d"),
            'Resource': project_name,
        })

    if not gantt_rows:
        return "<div style='padding:14px; color:#64748b;'>No contiguous project/task activity found in last 5 days.</div>"

    palette = [
        '#1971c2', '#2b8a3e', '#f08c00', '#c92a2a', '#5f3dc4', '#0b7285',
        '#a61e4d', '#495057', '#1864ab', '#2f9e44', '#d9480f', '#364fc7'
    ]
    projects = sorted({row['Resource'] for row in gantt_rows})
    project_colors = {name: palette[i % len(palette)] for i, name in enumerate(projects)}

    fig = ff.create_gantt(
        gantt_rows,
        index_col='Resource',
        colors=project_colors,
        show_colorbar=True,
        group_tasks=True,
        showgrid_x=True,
        showgrid_y=True,
        title='Projects & Tasks Activity Periods (Last 5 Days)'
    )
    fig.update_layout(
        height=min(620, max(320, 82 + len(gantt_rows) * 12)),
        margin=dict(l=18, r=18, t=55, b=16),
        paper_bgcolor='white',
        plot_bgcolor='white',
    )
    fig.update_xaxes(showgrid=True, gridcolor='#edf2f7', tickformat='%b %d')
    fig.update_yaxes(showgrid=True, gridcolor='#edf2f7')

    return plotly.io.to_html(fig, full_html=False, include_plotlyjs='cdn')

def build_landing_filter_data(user_tasks_data, all_tasks, users, project_names, milestones):
    projects_map = {}

    # Window metrics/summaries keyed by task for enriching the full task list.
    window_task_map = {}

    for user_data in user_tasks_data.values():
        for project_data in user_data.get('projects', {}).values():
            for task in project_data.get('tasks', []):
                task_id = task.get('id')
                if not task_id:
                    continue
                existing = window_task_map.get(task_id)
                if existing and existing.get('logged_hours', 0) >= float(task.get('hours', 0) or 0):
                    continue

                llm_result = task.get('llm_summary')
                summary_text = "No activity summary in selected period."
                if isinstance(llm_result, dict):
                    summary_text = llm_result.get('summary', summary_text) or summary_text
                elif isinstance(llm_result, str) and llm_result.strip():
                    summary_text = llm_result.strip()

                window_task_map[task_id] = {
                    'summary': summary_text,
                    'logged_hours': round(float(task.get('hours', 0) or 0), 2),
                    'timesheet_entries': len(task.get('timesheet_entries', []) or []),
                }

    for task in all_tasks:
        task_id = task.get('id')
        if not task_id:
            continue

        project_data = task.get('project_id')
        if isinstance(project_data, list) and project_data:
            project_name = project_names.get(project_data[0], project_data[1] if len(project_data) > 1 else 'No Project')
        else:
            project_name = 'No Project'

        if project_name not in projects_map:
            projects_map[project_name] = {
                'name': project_name,
                'engineers': {}
            }

        assignees = task.get('user_ids') or []
        if not assignees:
            assignees = [None]

        for assignee_id in assignees:
            if assignee_id is None:
                engineer_name = 'Unassigned'
            else:
                user = users.get(assignee_id)
                if not user:
                    continue
                engineer_name = user.get('name', 'Unknown Engineer')

            engineers_map = projects_map[project_name]['engineers']
            if engineer_name not in engineers_map:
                engineers_map[engineer_name] = {
                    'name': engineer_name,
                    'tasks': []
                }

            stage_data = task.get('stage_id')
            stage = stage_data[1] if isinstance(stage_data, list) and len(stage_data) > 1 else 'Unknown'

            ms_id = task.get('milestone_id')
            milestone_name = '-'
            milestone_deadline = ''
            if ms_id:
                ms_id_val = ms_id[0] if isinstance(ms_id, list) else ms_id
                milestone = milestones.get(ms_id_val, {})
                milestone_name = milestone.get('name', '-')
                milestone_deadline = (milestone.get('deadline', '') or '')[:10]

            task_window = window_task_map.get(task_id, {})
            engineers_map[engineer_name]['tasks'].append({
                'id': task_id,
                'name': task.get('name', 'Untitled Task'),
                'summary': task_window.get('summary', 'No activity summary in selected period.'),
                'status': stage,
                'age': calculate_age(task.get('create_date', '')),
                'priority': get_priority_label(task.get('priority', '0')),
                'progress': float(task.get('progress', 0) or 0),
                'logged_hours': task_window.get('logged_hours', 0.0),
                'owner': (task.get('create_uid')[1] if isinstance(task.get('create_uid'), list) and len(task.get('create_uid')) > 1 else '-') or '-',
                'milestone': milestone_name,
                'milestone_deadline': milestone_deadline,
                'deadline': (task.get('date_deadline', '') or '')[:10],
                'opened_on': (task.get('create_date', '') or '')[:10],
                'timesheet_entries': task_window.get('timesheet_entries', 0),
                'description': clean_html(task.get('description', '') or ''),
            })

    projects = []
    for project_name in sorted(projects_map.keys()):
        engineer_rows = []
        engineers_map = projects_map[project_name]['engineers']
        for engineer_name in sorted(engineers_map.keys()):
            tasks = sorted(
                engineers_map[engineer_name]['tasks'],
                key=lambda x: (x.get('logged_hours', 0), x.get('name', '')),
                reverse=True,
            )
            engineer_rows.append({
                'name': engineer_name,
                'tasks': tasks,
            })
        projects.append({
            'name': project_name,
            'engineers': engineer_rows,
        })

    return {
        'projects': projects,
    }

def generate_per_user_gantt_charts(user_tasks_data, shift_hours, recent_activity_map):
    gantt_charts = {}

    for user_id, data in user_tasks_data.items():
        user_name = data['name']
        shift = calculate_shift_metrics(data.get('total_hours', 0), shift_hours)
        util_color_map = {'under': '#f08c00', 'healthy': '#0b7285', 'over': '#c92a2a'}
        util_color = util_color_map.get(shift['band'], '#0b7285')

        project_totals = sorted(
            [(project_name, project_data.get('total_hours', 0)) for project_name, project_data in data['projects'].items()],
            key=lambda x: x[1],
            reverse=True
        )
        top_projects = project_totals[:5]

        summary_chart_html = ""
        if top_projects:
            project_names = [p[0] if len(p[0]) <= 34 else p[0][:31] + "..." for p in top_projects]
            project_hours = [p[1] for p in top_projects]
            remaining_project_hours = sum(hours for _, hours in project_totals[5:])
            if remaining_project_hours > 0:
                project_names.append('Others')
                project_hours.append(remaining_project_hours)

            task_totals = defaultdict(float)
            task_labels = {}
            for _, project_data in data['projects'].items():
                for task in project_data.get('tasks', []):
                    task_id = task.get('id')
                    if not task_id:
                        continue
                    task_totals[task_id] += float(task.get('hours', 0) or 0)
                    task_name = task.get('name', f'Task #{task_id}')
                    task_labels[task_id] = task_name if len(task_name) <= 38 else task_name[:35] + "..."

            sorted_tasks = sorted(task_totals.items(), key=lambda x: x[1], reverse=True)
            top_task_rows = sorted_tasks[:5]
            remaining_task_hours = sum(h for _, h in sorted_tasks[5:])

            task_names = [task_labels[tid] for tid, _ in top_task_rows]
            task_hours = [hours for _, hours in top_task_rows]
            if remaining_task_hours > 0:
                task_names.append('Others')
                task_hours.append(remaining_task_hours)

            fig_summary = make_subplots(
                rows=1,
                cols=2,
                specs=[[{'type': 'domain'}, {'type': 'domain'}]],
                horizontal_spacing=0.22,
                subplot_titles=('Project Split', 'Task Split')
            )
            fig_summary.add_trace(
                go.Pie(
                    labels=project_names,
                    values=project_hours,
                    hole=0.62,
                    textinfo='label',
                    textposition='outside',
                    automargin=True,
                    hovertemplate='<b>%{label}</b><br>%{value:.2f}h (%{percent})<extra></extra>'
                ),
                row=1,
                col=1,
            )
            fig_summary.add_trace(
                go.Pie(
                    labels=task_names,
                    values=task_hours,
                    hole=0.62,
                    textinfo='label',
                    textposition='outside',
                    automargin=True,
                    hovertemplate='<b>%{label}</b><br>%{value:.2f}h (%{percent})<extra></extra>'
                ),
                row=1,
                col=2,
            )
            fig_summary.data[0].update(domain={'x': [0.02, 0.42], 'y': [0.08, 0.98]})
            fig_summary.data[1].update(domain={'x': [0.58, 0.98], 'y': [0.08, 0.98]})
            fig_summary.update_layout(
                title=f"Workload Snapshot (Donut) - Utilization {shift['utilization']:.1f}%",
                height=255,
                margin=dict(l=10, r=10, t=52, b=10),
                paper_bgcolor='white',
                plot_bgcolor='white',
                font=dict(size=11, color='#1f2937'),
                showlegend=False,
            )

            summary_chart_html = plotly.io.to_html(fig_summary, full_html=False, include_plotlyjs='cdn')

        try:
            recent_rows = recent_activity_map.get(user_name, []) if recent_activity_map else []
            plot_html = generate_recent_task_timeline_chart(user_name, recent_rows)

            gantt_charts[user_name] = {
                'workload_html': summary_chart_html,
                'timeline_html': plot_html,
            }
        except Exception as e:
            gantt_charts[user_name] = {
                'workload_html': f"<p>Could not generate chart: {str(e)}</p>",
                'timeline_html': "",
            }

    return gantt_charts

def generate_detailed_task_view_html(data):
    project_sections_html = ""

    for project_name, project_data in sorted(data.get('projects', {}).items(), key=lambda x: x[1].get('total_hours', 0), reverse=True):
        all_tasks = project_data.get('tasks', [])
        task_ids_in_project = {t['id'] for t in all_tasks}

        main_tasks = []
        standalone_subtasks = []
        for task in all_tasks:
            parent_id = task.get('parent_id')
            is_subtask = task.get('is_subtask', False)
            if is_subtask and parent_id and parent_id in task_ids_in_project:
                continue
            if is_subtask:
                standalone_subtasks.append(task)
            else:
                main_tasks.append(task)

        rows_html = ""
        for task in main_tasks + standalone_subtasks:
            task_id = task['id']
            task_name = task['name']
            priority_label = get_priority_label(task.get('priority', '0'))
            priority_class = f'priority-{priority_label.lower()}'
            milestone_name = task.get('milestone_name', '-')
            milestone_deadline = task.get('milestone_deadline', '')[:10] if task.get('milestone_deadline') else ''
            task_owner = task.get('task_owner', '')
            open_date = task.get('create_date', '')[:10] if task.get('create_date') else '-'
            age = calculate_age(task.get('create_date', ''))
            deadline = task.get('date_deadline', '')[:10] if task.get('date_deadline') else '-'
            logged = f"{task.get('hours', 0):.1f}h"
            progress = f"{task.get('progress', 0):.0f}%"
            stage = task.get('stage', 'Unknown')
            stage_class = 'status-open' if 'Open' in stage else 'status-progress' if 'Progress' in stage else 'status-done' if 'Done' in stage or 'Close' in stage else 'status-cancel' if 'Cancel' in stage else ''
            description_html = format_log_notes(task.get('description', '')) if task.get('description') else ''

            llm_result = task.get('llm_summary')
            if isinstance(llm_result, dict):
                summary_text = llm_result.get('summary', '')
                authors = llm_result.get('authors', '')
            else:
                summary_text = llm_result or ''
                authors = ''

            log_summary_html = ''
            if summary_text:
                author_html = f" by {authors}" if authors else ''
                log_summary_html = f"<div class='summary-box'><strong>Log Notes Summary{author_html}:</strong> {summary_text}</div>"

            rows_html += f"""
                <tr>
                    <td><strong>{task_name}</strong><span class="priority-tag {priority_class}">{priority_label}</span></td>
                    <td><span class="priority-tag {priority_class}">{priority_label}</span></td>
                    <td>{milestone_name}{f' <span class="milestone-deadline">({milestone_deadline})</span>' if milestone_deadline else ''}</td>
                    <td class="{'status-open' if 'Open' in stage else 'status-progress' if 'Progress' in stage else 'status-done' if 'Done' in stage or 'Close' in stage else 'status-cancel' if 'Cancel' in stage else ''}">{stage}</td>
                    <td>{task_owner}</td>
                    <td>{open_date}</td>
                    <td>{age}</td>
                    <td>{deadline}</td>
                    <td><strong>{logged}</strong></td>
                    <td>{progress}</td>
                </tr>
            """
            if description_html:
                rows_html += f"""
                    <tr>
                        <td colspan="10">
                            <div class="task-description">
                                <div class="task-description-title">Description</div>
                                {description_html}
                            </div>
                        </td>
                    </tr>
                """
            if log_summary_html:
                rows_html += f"""
                    <tr>
                        <td colspan="10">
                            {log_summary_html}
                        </td>
                    </tr>
                """

        if not rows_html:
            rows_html = '<tr><td colspan="10"><div class="no-tasks">No task data</div></td></tr>'

        project_sections_html += f"""
            <div class="project-section">
                <div class="project-title">
                    <span>{project_name}</span>
                    <span class="project-hours">{project_data.get('total_hours', 0):.1f}h</span>
                </div>
                <table class="insights-table">
                    <thead>
                        <tr>
                            <th>Task / Work Description</th>
                            <th>Priority</th>
                            <th>Milestone</th>
                            <th>Stage</th>
                            <th>Owner</th>
                            <th>Open Date</th>
                            <th>Age</th>
                            <th>Deadline</th>
                            <th>Logged</th>
                            <th>Progress</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        """

    return f"""
        <div class="project-section">
            <div class="project-title">
                <span>Detailed Task View</span>
            </div>
        </div>
        {project_sections_html}
    """

def generate_team_overview_page_html(team_summary, idx, total):
    page_id = f"page-{idx}"

    utilization_rows = team_summary.get('utilization_rows', [])
    top_projects_html = team_summary.get('top_projects_html', '')
    projects_bubble_html = team_summary.get('projects_bubble_html', '')
    projects_tasks_gantt_html = team_summary.get('projects_tasks_gantt_html', '')

    return f"""
    <div class="user-page status-overview" id="{page_id}" data-index="{idx}">
        <div class="nav-bar">
            <div>
                <span class="nav-arrow" onclick="navigate({idx - 1})" style="visibility:hidden">&#9664; Previous</span>
            </div>
            <div class="page-indicator">
                <span class="status-indicator status-active">&#9679;</span>
                <span class="user-name-nav">Team Overview</span>
                <span class="page-count">{idx + 1} / {total}</span>
            </div>
            <div>
                <span class="nav-arrow" onclick="navigate({idx + 1})" {'style="visibility:hidden"' if idx == total - 1 else ''}>Next &#9654;</span>
            </div>
        </div>

        <div class="user-header">
            <div class="user-header-left">
                <h2>Team Snapshot</h2>
                <div class="user-meta">
                    <span class="hours-badge">Shift baseline {team_summary['shift_hours']:.1f}h</span>
                </div>
            </div>
        </div>

        <div class="project-section" id="landing-drilldown-panel">
            <div class="project-title">
                <span>Task Drilldown Filters</span>
            </div>
            <div class="filter-chain-grid">
                <div class="filter-item">
                    <label for="filter-project">Project</label>
                    <select id="filter-project">
                        <option value="">Select Project</option>
                    </select>
                </div>
                <div class="filter-item">
                    <label for="filter-engineer">Engineer</label>
                    <select id="filter-engineer" disabled>
                        <option value="">Select Engineer</option>
                    </select>
                </div>
                <div class="filter-item">
                    <label for="filter-task">Task</label>
                    <select id="filter-task" disabled>
                        <option value="">Select Task</option>
                    </select>
                </div>
            </div>

            <div id="task-drilldown-empty" class="task-drilldown-empty">
                Select Project -> Engineer -> Task to view summary, status, age, and technical details.
            </div>

            <div id="task-drilldown-details" class="task-drilldown-details" style="display:none;">
                <div class="drilldown-head">
                    <div class="drilldown-title" id="drill-task-title">-</div>
                    <div class="drilldown-badges">
                        <span class="priority-tag priority-p3" id="drill-task-priority">P3</span>
                        <span class="status-pill" id="drill-task-status">Unknown</span>
                    </div>
                </div>
                <div class="drilldown-grid" id="drilldown-grid"></div>
                <div class="drilldown-summary-box">
                    <div class="drilldown-summary-title">Summary</div>
                    <div id="drill-task-summary">-</div>
                </div>
                <div class="drilldown-description-box" id="drill-task-description-wrap" style="display:none;">
                    <div class="drilldown-summary-title">Description</div>
                    <div id="drill-task-description"></div>
                </div>
            </div>
        </div>

        <div class="summary-grid overview-grid">
            <div class="summary-card"><div class="summary-label">Team Members</div><div class="summary-value">{team_summary['total_members']}</div></div>
            <div class="summary-card"><div class="summary-label">Active</div><div class="summary-value">{team_summary['active_members']}</div></div>
            <div class="summary-card"><div class="summary-label">No Update</div><div class="summary-value">{team_summary['missing_members']}</div></div>
            <div class="summary-card"><div class="summary-label">Total Logged</div><div class="summary-value">{team_summary['total_logged']:.1f}h</div></div>
            <div class="summary-card"><div class="summary-label">Total Overtime</div><div class="summary-value">{team_summary['total_overtime']:.1f}h</div></div>
            <div class="summary-card"><div class="summary-label">Avg Utilization</div><div class="summary-value">{team_summary['avg_utilization']:.1f}%</div></div>
            <div class="summary-card"><div class="summary-label">Under 70%</div><div class="summary-value">{team_summary['under_count']}</div></div>
            <div class="summary-card"><div class="summary-label">70-100%</div><div class="summary-value">{team_summary['healthy_count']}</div></div>
            <div class="summary-card"><div class="summary-label">Over 100%</div><div class="summary-value">{team_summary['over_count']}</div></div>
        </div>

        <div class="project-section">
            <div class="project-title">
                <span>Top 5 Projects Summary</span>
            </div>
            {top_projects_html}
        </div>

        <div class="project-section">
            <div class="project-title">
                <span>Projects Worked vs Time (Bubble)</span>
            </div>
            <div style="overflow-x:auto;">{projects_bubble_html}</div>
        </div>

        <div class="project-section">
            <div class="project-title">
                <span>Projects and Tasks Timeline (Last 5 Days)</span>
            </div>
            <div style="overflow-x:auto;">{projects_tasks_gantt_html}</div>
        </div>
    </div>
    """

def generate_user_page_html(user_id, data, hours, shift_hours, gantt_charts, idx, total, has_activity):
    page_id = f"page-{idx}"
    shift = calculate_shift_metrics(data.get('total_hours', 0), shift_hours)
    utilization_width = min(max(shift['utilization'], 0), 100)
    utilization_class = f"utilization-{shift.get('band', 'healthy')}"

    if not has_activity:
        status_class = "status-no-update"
        status_icon = "&#9679;"
        status_label = "No Update"
        activity_html = f"""
            <div style="text-align: center; padding: 80px 20px;">
                <div style="font-size: 48px; color: #dc3545; margin-bottom: 20px;">&#9888;</div>
                <div style="font-size: 24px; font-weight: 700; color: #dc3545; margin-bottom: 15px;">No Update - Move to Next Member</div>
                <div style="font-size: 14px; color: #6c757d;">This team member has no timesheet entries logged in the last {hours} hours.</div>
            </div>
        """
    else:
        status_class = "status-active"
        status_icon = "&#9679;"
        status_label = "Active"
        activity_html = ""
        detailed_html = generate_detailed_task_view_html(data)

        gantt_html = ""
        if gantt_charts and data['name'] in gantt_charts:
            chart_pack = gantt_charts[data['name']]
            task_logs_rows = build_task_log_summaries(data)[:12]

            task_logs_html = ""
            for row in task_logs_rows:
                safe_summary = row['summary']
                if safe_summary and len(safe_summary) > 500:
                    safe_summary = safe_summary[:497] + '...'
                authors_html = f"<div class=\"task-log-meta\">By: {row['authors']}</div>" if row['authors'] else ""
                task_logs_html += f"""
                <div class="task-log-item">
                    <div class="task-log-title">{row['title']}</div>
                    <div class="task-log-project">{row['project']} | {row['hours']:.1f}h</div>
                    <div class="task-log-summary">{safe_summary}</div>
                    {authors_html}
                </div>
                """

            gantt_html = f"""
            <div class="analytics-layout">
                <div class="analytics-top-row">
                    <div class="analytics-panel">
                        <h4>Workload Snapshot</h4>
                        <div class="panel-content chart-content">{chart_pack.get('workload_html', '')}</div>
                    </div>
                    <div class="analytics-panel">
                        <h4>5-Day Task Timeline & Status</h4>
                        <div class="panel-content chart-content">{chart_pack.get('timeline_html', '')}</div>
                    </div>
                </div>
                <div class="analytics-bottom-row">
                    <div class="analytics-panel">
                        <h4>Task Summary</h4>
                        <div class="panel-content summary-content">
                            <div class="task-log-list">
                                {task_logs_html if task_logs_html else '<div class="task-log-empty">No task summaries available.</div>'}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            """

    page_html = f"""
    <div class="user-page {status_class}" id="{page_id}" data-index="{idx}">
        <div class="nav-bar">
            <div>
                <span class="nav-arrow" onclick="navigate({idx - 1})" {'style="visibility:hidden"' if idx == 0 else ''}>&#9664; Previous</span>
            </div>
            <div class="page-indicator">
                <span class="status-indicator {status_class}">{status_icon}</span>
                <span class="user-name-nav">{data['name']}</span>
                <span class="page-count">{idx + 1} / {total}</span>
            </div>
            <div>
                <span class="nav-arrow" onclick="navigate({idx + 1})" {'style="visibility:hidden"' if idx == total - 1 else ''}>Next &#9654;</span>
            </div>
        </div>

        <div class="user-header">
            <div class="user-header-left">
                <h2>{data['name']}</h2>
                <div class="user-meta">
                    <span class="status-badge {status_class}">{status_icon} {status_label}</span>
                    {f'<span class="hours-badge">{data["total_hours"]:.1f}h logged</span>' if has_activity else ''}
                </div>
            </div>
        </div>

        <div class="summary-grid compact-summary-grid">
            <div class="summary-card">
                <div class="summary-label">Logged</div>
                <div class="summary-value">{shift['logged']:.1f}h</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Shift Target</div>
                <div class="summary-value">{shift['target']:.1f}h</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Remaining</div>
                <div class="summary-value">{shift['remaining']:.1f}h</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Overtime</div>
                <div class="summary-value">{shift['overtime']:.1f}h</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Shift Utilization</div>
                <div class="summary-value {utilization_class}">{shift['utilization']:.1f}% <span class="utilization-status {utilization_class}">{shift['status']}</span></div>
            </div>
        </div>

        {gantt_html if has_activity and gantt_charts and data['name'] in gantt_charts else ''}

        {detailed_html if has_activity else ''}
    </div>
    """
    return page_html

def generate_html_report(user_pages_data, generated_date, hours, shift_hours, gantt_charts, landing_filter_data):
    all_pages = [p for p in user_pages_data]

    pages_html = ""
    for p in all_pages:
        pages_html += p['html']

    total_pages = len(all_pages)

    overview_filter_json = json.dumps(landing_filter_data)

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Team Activity Report - Last {hours}h</title>
        <style>
            * {{ box-sizing: border-box; }}
            :root {{
                --bg: #f3f6fa;
                --card: #ffffff;
                --text: #1f2937;
                --muted: #6b7280;
                --brand: #0b7285;
                --brand-soft: #e6fcf5;
                --danger: #c92a2a;
                --ok: #2b8a3e;
                --line: #dbe4ef;
            }}
            body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 0; background: radial-gradient(circle at top right, #e3fafc 0%, var(--bg) 35%, #edf2f7 100%); color: var(--text); }}
            .container {{ width: 100%; max-width: none; margin: 0; padding: 18px 18px 24px; }}
            h1 {{ color: #0f172a; font-size: 28px; margin-bottom: 6px; letter-spacing: 0.2px; }}
            .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
            .report-header {{
                background: var(--card);
                border: 1px solid var(--line);
                border-radius: 12px;
                padding: 16px 18px;
                margin-bottom: 18px;
                box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
            }}

            .nav-bar {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                background: white;
                padding: 12px 20px;
                border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                margin-bottom: 20px;
                position: sticky;
                top: 10px;
                z-index: 100;
            }}
            .nav-arrow {{
                cursor: pointer;
                padding: 8px 18px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 600;
                color: #495057;
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                transition: all 0.2s;
                user-select: none;
            }}
            .nav-arrow:hover {{
                background: #4a90d9;
                color: white;
                border-color: #4a90d9;
            }}
            .page-indicator {{
                display: flex;
                align-items: center;
                gap: 10px;
                font-size: 14px;
                color: #495057;
            }}
            .status-indicator {{
                font-size: 10px;
            }}
            .status-indicator.status-active {{ color: #28a745; }}
            .status-indicator.status-no-update {{ color: #dc3545; }}
            .user-name-nav {{
                font-weight: 600;
                font-size: 15px;
            }}
            .page-count {{
                color: #868e96;
                font-size: 13px;
                background: #f8f9fa;
                padding: 3px 10px;
                border-radius: 12px;
            }}

            .user-page {{
                background: white;
                border-radius: 12px;
                box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
                overflow: hidden;
            }}
            .user-page.status-no-update {{
                border: 2px solid #dc3545;
            }}
            .user-page.status-active {{
                border: 2px solid #28a745;
            }}
            .user-page.status-overview {{
                border: 2px solid #1864ab;
            }}
            .user-page:not(.active) {{
                display: none;
            }}

            .user-header {{
                padding: 20px 20px 8px;
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
            }}
            .user-header h2 {{
                margin: 0;
                color: #2c3e50;
                font-size: 22px;
            }}
            .user-header-left {{
                display: flex;
                flex-direction: column;
                gap: 8px;
            }}
            .user-meta {{
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            .status-badge {{
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 600;
            }}
            .status-badge.status-active {{
                background: #d4edda;
                color: #155724;
            }}
            .status-badge.status-no-update {{
                background: #f8d7da;
                color: #721c24;
            }}
            .hours-badge {{
                background: #e7f5ff;
                color: #1864ab;
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 600;
            }}

            .summary-grid {{
                display: grid;
                grid-template-columns: repeat(5, minmax(120px, 1fr));
                gap: 10px;
                padding: 0 20px 14px;
            }}
            .compact-summary-grid {{
                gap: 8px;
                padding: 0 15px 10px;
            }}
            .compact-summary-grid .summary-card {{
                padding: 7px 10px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
            }}
            .compact-summary-grid .summary-label {{
                margin-bottom: 0;
                font-size: 10px;
                line-height: 1;
            }}
            .compact-summary-grid .summary-value {{
                font-size: 16px;
                line-height: 1;
                white-space: nowrap;
            }}
            .compact-summary-grid .utilization-status {{
                margin-left: 4px;
                font-size: 11px;
            }}
            .overview-grid {{
                grid-template-columns: repeat(9, minmax(110px, 1fr));
            }}
            .summary-card {{
                background: #f8fbff;
                border: 1px solid #e1ecf5;
                border-radius: 10px;
                padding: 10px;
            }}
            .summary-card-wide {{
                grid-column: span 2;
            }}
            .summary-label {{
                font-size: 11px;
                color: #64748b;
                text-transform: uppercase;
                letter-spacing: 0.4px;
                margin-bottom: 5px;
                font-weight: 600;
            }}
            .summary-value {{
                font-size: 20px;
                font-weight: 700;
                color: #0f172a;
            }}
            .utilization-status {{
                font-size: 12px;
                font-weight: 600;
                color: #64748b;
                margin-left: 6px;
            }}
            .utilization-track {{
                margin-top: 8px;
                width: 100%;
                height: 8px;
                border-radius: 999px;
                background: #dfe7ef;
                overflow: hidden;
            }}
            .utilization-fill {{
                height: 100%;
                background: linear-gradient(90deg, #12b886 0%, #0b7285 65%, #1864ab 100%);
            }}
            .summary-value.utilization-under,
            .utilization-status.utilization-under {{
                color: #f08c00;
            }}
            .summary-value.utilization-healthy,
            .utilization-status.utilization-healthy {{
                color: #0b7285;
            }}
            .summary-value.utilization-over,
            .utilization-status.utilization-over {{
                color: #c92a2a;
            }}
            .utilization-fill.utilization-under {{
                background: linear-gradient(90deg, #fab005 0%, #f08c00 100%);
            }}
            .utilization-fill.utilization-healthy {{
                background: linear-gradient(90deg, #12b886 0%, #0b7285 65%, #1864ab 100%);
            }}
            .utilization-fill.utilization-over {{
                background: linear-gradient(90deg, #fa5252 0%, #e03131 100%);
            }}

            .overview-pill {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 999px;
                font-size: 11px;
                font-weight: 700;
            }}
            .overview-pill.under {{
                background: #fff3bf;
                color: #8f5b00;
            }}
            .overview-pill.healthy {{
                background: #d3f9d8;
                color: #1b5e20;
            }}
            .overview-pill.over {{
                background: #ffe3e3;
                color: #a61e4d;
            }}

            .project-section {{
                margin: 15px 15px 18px;
                padding: 15px;
                background: #f8fafc;
                border-radius: 10px;
                border-left: 4px solid #1971c2;
                border: 1px solid #e1e8f0;
            }}

            .analytics-layout {{
                padding: 0 15px 10px;
            }}
            .analytics-top-row {{
                display: grid;
                grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                gap: 8px;
                margin-bottom: 8px;
            }}
            .analytics-bottom-row {{
                display: grid;
                grid-template-columns: minmax(0, 1fr);
            }}
            .analytics-panel {{
                border: 1px solid #dbe4ef;
                border-radius: 10px;
                background: #ffffff;
                min-height: 280px;
                display: flex;
                flex-direction: column;
                min-width: 0;
                overflow: hidden;
            }}
            .analytics-panel h4 {{
                margin: 0;
                padding: 12px 12px 0;
                color: #0f172a;
                font-size: 14px;
            }}
            .panel-content {{
                padding: 6px 8px 8px;
                flex: 1;
                overflow-x: auto;
                min-width: 0;
            }}
            .panel-content .plotly-graph-div {{
                width: 100% !important;
                min-width: 0 !important;
            }}
            .chart-content > div {{
                min-width: 0;
                width: 100%;
            }}

            .task-summary-grid {{
                display: grid;
                grid-template-columns: repeat(2, minmax(90px, 1fr));
                gap: 8px;
                margin-bottom: 12px;
            }}
            .task-summary-item {{
                background: #f8fbff;
                border: 1px solid #dbe7f3;
                border-radius: 8px;
                padding: 8px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 12px;
                color: #334155;
            }}
            .task-summary-item strong {{
                font-size: 15px;
                color: #0f172a;
            }}
            .task-top-list-title {{
                font-size: 12px;
                font-weight: 700;
                color: #334155;
                margin-bottom: 8px;
                text-transform: uppercase;
                letter-spacing: 0.4px;
            }}
            .task-top-list ul {{
                list-style: none;
                padding: 0;
                margin: 0;
            }}
            .task-top-list li {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 6px 8px;
                border-radius: 6px;
                border: 1px solid #e3ebf5;
                margin-bottom: 6px;
                background: #fcfdff;
                font-size: 12px;
                color: #334155;
                gap: 8px;
            }}
            .task-top-list li span {{
                flex: 1;
            }}

            .task-log-list {{
                display: flex;
                flex-direction: column;
                gap: 10px;
            }}
            .task-log-item {{
                border: 1px solid #dbe7f3;
                border-radius: 8px;
                background: #fcfdff;
                padding: 10px;
            }}
            .task-log-title {{
                font-size: 16px;
                font-weight: 700;
                color: #1f2937;
                margin-bottom: 4px;
            }}
            .task-log-project {{
                font-size: 11px;
                font-weight: 600;
                color: #64748b;
                margin-bottom: 7px;
            }}
            .task-log-summary {{
                font-size: 16px;
                color: #334155;
                line-height: 1.5;
            }}
            .task-log-meta {{
                font-size: 11px;
                color: #64748b;
                margin-top: 7px;
            }}
            .task-log-empty {{
                font-size: 12px;
                color: #64748b;
                padding: 10px;
            }}
            .project-title {{
                font-size: 16px;
                font-weight: 600;
                color: #2c3e50;
                margin-bottom: 12px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .project-hours {{
                background: #e3f2fd;
                color: #1976d2;
                padding: 3px 10px;
                border-radius: 10px;
                font-size: 12px;
                font-weight: 500;
            }}

            .project-summary-grid {{
                display: grid;
                grid-template-columns: repeat(5, minmax(200px, 1fr));
                gap: 10px;
            }}
            .filter-chain-grid {{
                display: grid;
                grid-template-columns: repeat(3, minmax(180px, 1fr));
                gap: 10px;
                margin-bottom: 12px;
            }}
            .filter-item {{
                display: flex;
                flex-direction: column;
                gap: 6px;
            }}
            .filter-item label {{
                font-size: 12px;
                font-weight: 700;
                color: #334155;
            }}
            .filter-item select {{
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                background: #ffffff;
                color: #1f2937;
                font-size: 13px;
                padding: 9px 10px;
            }}
            .filter-item select:disabled {{
                background: #f8fafc;
                color: #94a3b8;
            }}
            .task-drilldown-empty {{
                font-size: 13px;
                color: #64748b;
                padding: 10px;
                border: 1px dashed #cbd5e1;
                border-radius: 8px;
                background: #f8fafc;
            }}
            .task-drilldown-details {{
                border: 1px solid #dbe7f3;
                border-radius: 10px;
                background: #ffffff;
                padding: 12px;
            }}
            .drilldown-head {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 8px;
                margin-bottom: 10px;
            }}
            .drilldown-title {{
                font-size: 15px;
                font-weight: 700;
                color: #0f172a;
            }}
            .drilldown-badges {{
                display: flex;
                gap: 8px;
                align-items: center;
            }}
            .status-pill {{
                display: inline-block;
                padding: 3px 10px;
                border-radius: 999px;
                font-size: 11px;
                font-weight: 700;
                background: #e2e8f0;
                color: #334155;
            }}
            .status-pill.status-open {{
                background: #dbeafe;
                color: #1d4ed8;
            }}
            .status-pill.status-progress {{
                background: #fff3bf;
                color: #8f5b00;
            }}
            .status-pill.status-done {{
                background: #d3f9d8;
                color: #1b5e20;
            }}
            .status-pill.status-cancel {{
                background: #ffe3e3;
                color: #a61e4d;
            }}
            .drilldown-grid {{
                display: grid;
                grid-template-columns: repeat(4, minmax(130px, 1fr));
                gap: 8px;
                margin-bottom: 10px;
            }}
            .drilldown-cell {{
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background: #f8fafc;
                padding: 8px;
            }}
            .drilldown-cell-label {{
                font-size: 10px;
                letter-spacing: 0.35px;
                text-transform: uppercase;
                color: #64748b;
                margin-bottom: 4px;
                font-weight: 700;
            }}
            .drilldown-cell-value {{
                font-size: 13px;
                color: #1f2937;
                font-weight: 600;
            }}
            .drilldown-summary-box,
            .drilldown-description-box {{
                border: 1px solid #dbe7f3;
                border-radius: 8px;
                background: #fcfdff;
                padding: 10px;
                font-size: 13px;
                line-height: 1.5;
                color: #334155;
                margin-top: 8px;
            }}
            .drilldown-summary-title {{
                font-size: 11px;
                text-transform: uppercase;
                color: #475569;
                font-weight: 700;
                letter-spacing: 0.4px;
                margin-bottom: 5px;
            }}
            .project-summary-card {{
                border: 1px solid #dbe7f3;
                background: #fcfdff;
                border-radius: 10px;
                padding: 10px;
                min-width: 0;
            }}
            .project-summary-head {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 8px;
                margin-bottom: 8px;
            }}
            .project-summary-name {{
                font-size: 13px;
                font-weight: 700;
                color: #1f2937;
                line-height: 1.3;
            }}
            .project-summary-hours {{
                font-size: 11px;
                font-weight: 700;
                color: #0b7285;
                background: #e6fcf5;
                border-radius: 999px;
                padding: 3px 8px;
                white-space: nowrap;
            }}
            .project-summary-notes ul {{
                margin: 0;
                padding-left: 16px;
                display: flex;
                flex-direction: column;
                gap: 6px;
            }}
            .project-summary-notes li {{
                font-size: 12px;
                color: #334155;
                line-height: 1.35;
            }}
            .project-note-empty {{
                font-size: 12px;
                color: #64748b;
                font-style: italic;
            }}

            .task-card {{
                background: white;
                padding: 15px;
                margin-bottom: 12px;
                border-radius: 6px;
                border: 1px solid #e9ecef;
            }}
            .task-header {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 8px;
            }}
            .task-title {{
                font-size: 15px;
                font-weight: 600;
                color: #2c3e50;
                flex: 1;
            }}
            .task-hours {{
                background: #d4edda;
                color: #155724;
                padding: 3px 10px;
                border-radius: 10px;
                font-size: 12px;
                font-weight: 500;
            }}
            .subtask-nav {{
                margin-left: 15px;
                font-size: 11px;
                color: #6c757d;
                font-weight: normal;
            }}
            .subtask-nav a {{
                color: #4a90d9;
                text-decoration: none;
                margin-left: 8px;
            }}
            .subtask-nav a:hover {{ text-decoration: underline; }}

            .task-details {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                gap: 8px;
                margin: 10px 0;
                padding: 10px;
                background: #f8f9fa;
                border-radius: 4px;
                font-size: 12px;
            }}
            .detail-item {{ display: flex; flex-direction: column; }}
            .detail-label {{ color: #6c757d; font-size: 11px; text-transform: uppercase; margin-bottom: 2px; }}
            .detail-value {{ color: #495057; font-weight: 500; }}
            .detail-value.status-open {{ color: #007bff; }}
            .detail-value.status-progress {{ color: #ffc107; }}
            .detail-value.status-done {{ color: #28a745; }}
            .detail-value.status-cancel {{ color: #dc3545; }}

            .task-description {{
                background: #e3f2fd;
                padding: 12px;
                border-radius: 4px;
                margin: 10px 0;
                font-size: 13px;
                border-left: 3px solid #2196f3;
                color: #0d47a1;
                line-height: 1.6;
            }}
            .task-description-title {{
                font-weight: 600;
                font-size: 12px;
                text-transform: uppercase;
                color: #1565c0;
                margin-bottom: 8px;
                letter-spacing: 0.5px;
            }}

            .log-notes-section {{
                margin-top: 12px;
                padding: 12px;
                background: #fff;
                border-radius: 4px;
                border: 1px solid #e0e0e0;
            }}
            .log-notes-header {{
                font-weight: 600;
                font-size: 12px;
                text-transform: uppercase;
                color: #424242;
                margin-bottom: 10px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding-bottom: 8px;
                border-bottom: 1px solid #e0e0e0;
            }}
            .log-note-item {{
                padding: 10px;
                margin: 8px 0;
                background: #fafafa;
                border-radius: 4px;
                border-left: 3px solid #4caf50;
            }}
            .log-note-meta {{
                font-size: 11px;
                color: #757575;
                margin-bottom: 6px;
                display: flex;
                justify-content: space-between;
            }}
            .log-note-author {{
                font-weight: 600;
                color: #1976d2;
            }}
            .log-note-date {{
                color: #9e9e9e;
            }}
            .log-note-body {{
                font-size: 13px;
                color: #424242;
                line-height: 1.5;
                white-space: pre-wrap;
                word-wrap: break-word;
            }}
            .log-note-body a {{
                color: #1976d2;
                text-decoration: none;
            }}
            .log-note-body a:hover {{
                text-decoration: underline;
            }}

            .summary-box {{
                background: #e7f3ff;
                padding: 12px;
                border-radius: 4px;
                margin-top: 10px;
                font-size: 13px;
                color: #004085;
                border-left: 3px solid #004085;
            }}
            .no-logs {{
                font-size: 12px;
                color: #6c757d;
                font-style: italic;
            }}

            .insights-table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
                font-size: 13px;
            }}
            .insights-table th {{
                background: #e9f2fb;
                color: #334155;
                padding: 10px;
                text-align: left;
                font-weight: 600;
                border-bottom: 2px solid #d5e3f2;
                position: sticky;
                top: 0;
                z-index: 5;
            }}
            .insights-table td {{
                padding: 10px;
                border-bottom: 1px solid #dee2e6;
                color: #495057;
            }}
            .insights-table tr:hover {{ background: #f8f9fa; }}

            .subtask-list {{
                margin: 10px 0 10px 20px;
                padding: 10px;
                background: #f0f4f8;
                border-radius: 4px;
                border-left: 3px solid #6c757d;
            }}
            .subtask-item {{
                padding: 8px;
                margin: 5px 0;
                background: white;
                border-radius: 4px;
                border: 1px solid #dee2e6;
                cursor: pointer;
            }}
            .subtask-item:hover {{ background: #e9ecef; }}

            .no-tasks {{
                text-align: center;
                padding: 40px;
                color: #6c757d;
            }}

            .priority-tag {{
                display: inline-block;
                padding: 2px 8px;
                border-radius: 10px;
                font-size: 11px;
                font-weight: 600;
                margin-left: 8px;
            }}
            .priority-p1 {{
                background: #dc3545;
                color: white;
            }}
            .priority-p2 {{
                background: #ffc107;
                color: #212529;
            }}
            .priority-p3 {{
                background: #28a745;
                color: white;
            }}

            .milestone-info {{
                font-size: 12px;
                color: #6c757d;
                margin-top: 4px;
            }}
            .milestone-name {{
                font-weight: 600;
                color: #495057;
            }}
            .milestone-deadline {{
                color: #dc3545;
            }}

            .keyboard-hint {{
                text-align: center;
                color: #adb5bd;
                font-size: 12px;
                margin-top: 15px;
                padding: 10px;
            }}
            .keyboard-hint kbd {{
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11px;
            }}

            @media (max-width: 980px) {{
                .summary-grid {{
                    grid-template-columns: repeat(2, minmax(120px, 1fr));
                }}
                .overview-grid {{
                    grid-template-columns: repeat(2, minmax(120px, 1fr));
                }}
                .summary-card-wide {{
                    grid-column: span 2;
                }}
                .container {{
                    padding: 12px 12px 18px;
                }}
                .project-section {{
                    margin: 10px;
                    padding: 10px;
                }}
                .analytics-top-row {{
                    grid-template-columns: 1fr;
                }}
                .analytics-layout {{
                    padding: 0 10px 10px;
                }}
                .analytics-panel {{
                    min-height: auto;
                }}
                .chart-content > div {{
                    min-width: 300px;
                }}
                .project-summary-grid {{
                    grid-template-columns: 1fr;
                }}
                .filter-chain-grid {{
                    grid-template-columns: 1fr;
                }}
                .drilldown-grid {{
                    grid-template-columns: repeat(2, minmax(120px, 1fr));
                }}
            }}
        </style>
        <script>
            var currentPage = 0;
            var totalPages = {total_pages};
            var overviewFilterData = {overview_filter_json};

            function stageClassFor(statusText) {{
                var stage = (statusText || '').toLowerCase();
                if (stage.indexOf('done') !== -1 || stage.indexOf('close') !== -1) return 'status-done';
                if (stage.indexOf('progress') !== -1 || stage.indexOf('review') !== -1 || stage.indexOf('develop') !== -1) return 'status-progress';
                if (stage.indexOf('cancel') !== -1) return 'status-cancel';
                return 'status-open';
            }}

            function clearSelect(selectEl, placeholder) {{
                if (!selectEl) return;
                selectEl.innerHTML = '';
                var option = document.createElement('option');
                option.value = '';
                option.textContent = placeholder;
                selectEl.appendChild(option);
            }}

            function fillSelect(selectEl, rows, labelGetter) {{
                rows.forEach(function(row, idx) {{
                    var option = document.createElement('option');
                    option.value = String(idx);
                    option.textContent = labelGetter(row);
                    selectEl.appendChild(option);
                }});
            }}

            function renderDrilldownCells(task) {{
                var grid = document.getElementById('drilldown-grid');
                if (!grid) return;

                var cells = [
                    ['Project', task.project_name || '-'],
                    ['Engineer', task.engineer_name || '-'],
                    ['Age', task.age || '-'],
                    ['Logged', (task.logged_hours || 0).toFixed(1) + 'h'],
                    ['Progress', (task.progress || 0).toFixed(0) + '%'],
                    ['Priority', task.priority || '-'],
                    ['Task Owner', task.owner || '-'],
                    ['Milestone', task.milestone || '-'],
                    ['Milestone Deadline', task.milestone_deadline || '-'],
                    ['Task Deadline', task.deadline || '-'],
                    ['Opened On', task.opened_on || '-'],
                    ['Timesheet Entries', String(task.timesheet_entries || 0)],
                ];

                grid.innerHTML = '';
                cells.forEach(function(row) {{
                    var cell = document.createElement('div');
                    cell.className = 'drilldown-cell';

                    var label = document.createElement('div');
                    label.className = 'drilldown-cell-label';
                    label.textContent = row[0];

                    var value = document.createElement('div');
                    value.className = 'drilldown-cell-value';
                    value.textContent = row[1];

                    cell.appendChild(label);
                    cell.appendChild(value);
                    grid.appendChild(cell);
                }});
            }}

            function renderTaskDetails(task) {{
                var detailsWrap = document.getElementById('task-drilldown-details');
                var emptyWrap = document.getElementById('task-drilldown-empty');
                var titleEl = document.getElementById('drill-task-title');
                var priorityEl = document.getElementById('drill-task-priority');
                var statusEl = document.getElementById('drill-task-status');
                var summaryEl = document.getElementById('drill-task-summary');
                var descWrap = document.getElementById('drill-task-description-wrap');
                var descEl = document.getElementById('drill-task-description');

                if (!task) {{
                    if (detailsWrap) detailsWrap.style.display = 'none';
                    if (emptyWrap) emptyWrap.style.display = 'block';
                    return;
                }}

                if (titleEl) titleEl.textContent = task.name || '-';
                if (priorityEl) {{
                    var p = (task.priority || 'P3').toUpperCase();
                    priorityEl.textContent = p;
                    priorityEl.className = 'priority-tag ' + (p === 'P1' ? 'priority-p1' : p === 'P2' ? 'priority-p2' : 'priority-p3');
                }}
                if (statusEl) {{
                    statusEl.textContent = task.status || 'Unknown';
                    statusEl.className = 'status-pill ' + stageClassFor(task.status);
                }}
                if (summaryEl) summaryEl.textContent = task.summary || 'No summary available.';

                if (descWrap && descEl) {{
                    if (task.description) {{
                        descWrap.style.display = 'block';
                        descEl.textContent = task.description;
                    }} else {{
                        descWrap.style.display = 'none';
                        descEl.textContent = '';
                    }}
                }}

                renderDrilldownCells(task);

                if (emptyWrap) emptyWrap.style.display = 'none';
                if (detailsWrap) detailsWrap.style.display = 'block';
            }}

            function initOverviewFilters() {{
                var projectEl = document.getElementById('filter-project');
                var engineerEl = document.getElementById('filter-engineer');
                var taskEl = document.getElementById('filter-task');

                if (!projectEl || !engineerEl || !taskEl) return;

                clearSelect(projectEl, 'Select Project');
                clearSelect(engineerEl, 'Select Engineer');
                clearSelect(taskEl, 'Select Task');

                var projects = (overviewFilterData && overviewFilterData.projects) ? overviewFilterData.projects : [];
                var currentTaskPool = [];
                fillSelect(projectEl, projects, function(p) {{ return p.name; }});
                engineerEl.disabled = true;
                taskEl.disabled = true;
                renderTaskDetails(null);

                function renderSelectedTask(taskIdx) {{
                    if (taskIdx === '') {{
                        renderTaskDetails(null);
                        return;
                    }}
                    var selectedTask = currentTaskPool[Number(taskIdx)];
                    if (!selectedTask || Number.isNaN(Number(taskIdx))) {{
                        renderTaskDetails(null);
                        return;
                    }}
                    renderTaskDetails(selectedTask);
                }}

                function buildTaskPool(selectedProject, engineerValue) {{
                    if (!selectedProject || !selectedProject.engineers) return [];

                    var pool = [];
                    selectedProject.engineers.forEach(function(engineer, engineerIdx) {{
                        if (engineerValue !== 'all' && String(engineerIdx) !== engineerValue) {{
                            return;
                        }}

                        (engineer.tasks || []).forEach(function(task) {{
                            var taskWithContext = Object.assign({{}}, task, {{
                                project_name: selectedProject.name,
                                engineer_name: engineer.name,
                            }});
                            pool.push(taskWithContext);
                        }});
                    }});

                    pool.sort(function(a, b) {{
                        var diff = (b.logged_hours || 0) - (a.logged_hours || 0);
                        if (diff !== 0) return diff;
                        return (a.name || '').localeCompare(b.name || '');
                    }});

                    return pool;
                }}

                function populateTasksAndRender() {{
                    clearSelect(taskEl, 'Select Task');
                    var projectIdx = projectEl.value;
                    if (projectIdx === '') {{
                        taskEl.disabled = true;
                        currentTaskPool = [];
                        renderTaskDetails(null);
                        return;
                    }}

                    var selectedProject = projects[Number(projectIdx)];
                    var engineerValue = engineerEl.value || 'all';
                    currentTaskPool = buildTaskPool(selectedProject, engineerValue);

                    fillSelect(taskEl, currentTaskPool, function(t) {{
                        return t.name + ' [' + t.engineer_name + '] (' + (t.logged_hours || 0).toFixed(1) + 'h)';
                    }});

                    if (currentTaskPool.length > 0) {{
                        taskEl.disabled = false;
                        taskEl.value = '0';
                        renderSelectedTask('0');
                    }} else {{
                        taskEl.disabled = true;
                        renderTaskDetails(null);
                    }}
                }}

                projectEl.onchange = function() {{
                    clearSelect(engineerEl, 'Select Engineer');
                    clearSelect(taskEl, 'Select Task');
                    taskEl.disabled = true;
                    renderTaskDetails(null);

                    var projectIdx = projectEl.value;
                    if (projectIdx === '') {{
                        engineerEl.disabled = true;
                        return;
                    }}

                    var selectedProject = projects[Number(projectIdx)];
                    var engineers = (selectedProject && selectedProject.engineers) ? selectedProject.engineers : [];

                    var allOption = document.createElement('option');
                    allOption.value = 'all';
                    allOption.textContent = 'All Engineers';
                    engineerEl.appendChild(allOption);

                    fillSelect(engineerEl, engineers, function(e) {{ return e.name; }});
                    if (engineers.length > 0 || selectedProject) {{
                        engineerEl.disabled = false;
                        engineerEl.value = 'all';
                        populateTasksAndRender();
                    }} else {{
                        engineerEl.disabled = true;
                        taskEl.disabled = true;
                        currentTaskPool = [];
                        renderTaskDetails(null);
                    }}
                }};

                engineerEl.onchange = function() {{
                    populateTasksAndRender();
                }};

                taskEl.onchange = function() {{
                    var taskIdx = taskEl.value;
                    renderSelectedTask(taskIdx);
                }};
            }}

            function showPage(idx) {{
                if (idx < 0 || idx >= totalPages) return;
                currentPage = idx;
                for (var i = 0; i < totalPages; i++) {{
                    var el = document.getElementById('page-' + i);
                    if (el) el.classList.remove('active');
                }}
                var target = document.getElementById('page-' + idx);
                if (target) target.classList.add('active');
                if (idx === 0) {{
                    initOverviewFilters();
                }}
                if (window.Plotly && target) {{
                    setTimeout(function() {{
                        var plots = target.querySelectorAll('.plotly-graph-div');
                        plots.forEach(function(plot) {{
                            try {{ Plotly.Plots.resize(plot); }} catch (e) {{}}
                        }});
                    }}, 50);
                }}
                window.scrollTo({{ top: 0, behavior: 'smooth' }});
            }}

            function navigate(idx) {{
                showPage(idx);
            }}

            document.addEventListener('keydown', function(e) {{
                if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {{
                    if (currentPage < totalPages - 1) {{
                        showPage(currentPage + 1);
                    }}
                    e.preventDefault();
                }} else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{
                    if (currentPage > 0) {{
                        showPage(currentPage - 1);
                    }}
                    e.preventDefault();
                }}
            }});

            window.onload = function() {{
                showPage(0);
            }};
        </script>
    </head>
    <body>
        <div class="container">
            <div class="report-header">
                <h1>Team Activity Report - Last {hours} Hours</h1>
                <div class="meta">Generated on {generated_date} | Shift baseline: {shift_hours:.1f}h | Showing team overview + one team member per page</div>
            </div>
            {pages_html}
            <div class="keyboard-hint">Use <kbd>&larr;</kbd> <kbd>&rarr;</kbd> or <kbd>&uarr;</kbd> <kbd>&darr;</kbd> keys to navigate</div>
        </div>
    </body>
    </html>
    """
    return html_content

def main():
    parser = argparse.ArgumentParser(description="Generate paginated team activity report")
    parser.add_argument("--hours", type=int, default=24, help="Number of hours to look back (default: 24)")
    args = parser.parse_args()

    hours = args.hours

    print("Connecting to Odoo...")
    uid, models = connect_odoo()
    print("Connected successfully!")

    now = datetime.now()
    generated_date = now.strftime("%Y-%m-%d %H:%M:%S")
    since = now - timedelta(hours=hours)

    print(f"\nFetching timesheets updated in the last {hours} hours...")
    print(f"Time range: {since.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%Y-%m-%d %H:%M')}")

    users = fetch_users(models, uid)
    print(f"Found {len(users)} users")

    if EXCLUDED_USERS:
        original_count = len(users)
        users = {k: v for k, v in users.items() if v['name'] not in EXCLUDED_USERS}
        print(f"Excluded {original_count - len(users)} users: {EXCLUDED_USERS}")

    timesheets = fetch_recent_timesheets(models, uid, hours)
    print(f"Found {len(timesheets)} timesheet entries")

    five_day_window_hours = max(120, hours)
    timesheets_5d = fetch_recent_timesheets(models, uid, five_day_window_hours)
    print(f"Found {len(timesheets_5d)} timesheet entries in last 5 days")

    user_ids_with_timesheets = set()
    project_ids = set()
    task_ids = set()

    for ts in timesheets:
        if ts.get('user_id'):
            user_ids_with_timesheets.add(ts['user_id'][0])
        if ts.get('project_id'):
            project_ids.add(ts['project_id'][0])
        if ts.get('task_id'):
            task_ids.add(ts['task_id'][0])

    task_ids_5d = set()
    for ts in timesheets_5d:
        if ts.get('project_id'):
            project_ids.add(ts['project_id'][0])
        if ts.get('task_id'):
            task_ids_5d.add(ts['task_id'][0])

    user_ids_with_timesheets = list(user_ids_with_timesheets)
    print(f"Users with timesheets: {len(user_ids_with_timesheets)}")

    all_user_ids = set(users.keys())
    missing_user_ids = all_user_ids - set(user_ids_with_timesheets)
    missing_users = [users[uid] for uid in missing_user_ids]
    print(f"Users missing updates: {len(missing_users)} - {[u['name'] for u in missing_users]}")

    project_ids = list(project_ids)
    project_names = fetch_projects(models, uid, project_ids) if project_ids else {}

    all_user_task_ids = set()
    if user_ids_with_timesheets:
        all_tasks_for_users = fetch_all_tasks_for_users(models, uid, user_ids_with_timesheets)
        print(f"Found {len(all_tasks_for_users)} total tasks for users with timesheets")

        for t in all_tasks_for_users:
            all_user_task_ids.add(t['id'])
            if t.get('child_ids'):
                all_user_task_ids.update(t['child_ids'])

    all_task_ids = list(all_user_task_ids | set(task_ids) | task_ids_5d)
    print(f"Total task IDs to fetch: {len(all_task_ids)}")

    all_tasks = fetch_tasks(models, uid, all_task_ids) if all_task_ids else []
    print(f"Found {len(all_tasks)} tasks (including subtasks)")

    all_task_map = {t['id']: t for t in all_tasks}

    milestone_ids = set()
    for task in all_tasks:
        ms_id = task.get('milestone_id')
        if ms_id:
            milestone_ids.add(ms_id[0] if isinstance(ms_id, list) else ms_id)

    milestones = fetch_milestones(models, uid, list(milestone_ids)) if milestone_ids else {}
    print(f"Found {len(milestones)} milestones")

    logs = fetch_task_logs(models, uid, all_task_ids) if all_task_ids else []
    print(f"Found {len(logs)} log entries")

    task_logs_map = {}
    for log in logs:
        res_id = log.get('res_id')
        if res_id:
            if res_id not in task_logs_map:
                task_logs_map[res_id] = []
            task_logs_map[res_id].append(log)

    user_tasks_data = {}

    for ts in timesheets:
        task_id = ts.get('task_id')
        user_id = ts.get('user_id')

        if not task_id or not user_id:
            continue

        task_id = task_id[0]
        user_id = user_id[0]

        if user_id not in users:
            continue

        if user_id not in user_tasks_data:
            user_tasks_data[user_id] = {
                'name': users[user_id]['name'],
                'email': users[user_id]['email'],
                'projects': {},
                'total_hours': 0,
            }

        task = all_task_map.get(task_id)
        if not task:
            continue

        proj_id = task.get('project_id')
        project_name = project_names.get(proj_id[0], 'No Project') if proj_id else 'No Project'

        if project_name not in user_tasks_data[user_id]['projects']:
            user_tasks_data[user_id]['projects'][project_name] = {
                'total_hours': 0,
                'tasks': {}
            }

        entry_hours = ts.get('unit_amount', 0)
        timesheet_entry = {
            'hours': entry_hours,
            'description': clean_html(ts.get('name', '')),
            'date': ts.get('date', ''),
        }

        if task_id not in user_tasks_data[user_id]['projects'][project_name]['tasks']:
            is_subtask = bool(task.get('parent_id'))
            parent_id = task.get('parent_id')
            parent_id = parent_id[0] if parent_id else None
            stage_data = task.get('stage_id')
            stage = stage_data[1] if stage_data else 'Unknown'

            ms_id = task.get('milestone_id')
            milestone_name = '-'
            milestone_deadline = ''
            if ms_id:
                ms_id_val = ms_id[0] if isinstance(ms_id, list) else ms_id
                milestone = milestones.get(ms_id_val, {})
                milestone_name = milestone.get('name', '-')
                milestone_deadline = milestone.get('deadline', '')

            create_uid = task.get('create_uid')
            task_owner = create_uid[1] if create_uid else ''

            task_logs = task_logs_map.get(task_id, [])

            print(f"\nSummarizing task: {task['name'][:50]}...")
            llm_summary = summarize_with_llm(task_logs, task.get('description', ''))

            user_tasks_data[user_id]['projects'][project_name]['tasks'][task_id] = {
                'id': task['id'],
                'name': task['name'],
                'description': clean_html(task.get('description', '')),
                'hours': 0,
                'timesheet_entries': [],
                'logs': task_logs,
                'llm_summary': llm_summary,
                'is_subtask': is_subtask,
                'parent_id': parent_id,
                'create_date': task.get('create_date', ''),
                'date_deadline': task.get('date_deadline', ''),
                'progress': task.get('progress', 0),
                'stage': stage,
                'task_owner': task_owner,
                'priority': task.get('priority', '0'),
                'milestone_name': milestone_name,
                'milestone_deadline': milestone_deadline,
            }

        user_tasks_data[user_id]['projects'][project_name]['tasks'][task_id]['timesheet_entries'].append(timesheet_entry)
        user_tasks_data[user_id]['projects'][project_name]['tasks'][task_id]['hours'] += entry_hours
        user_tasks_data[user_id]['projects'][project_name]['total_hours'] += entry_hours
        user_tasks_data[user_id]['total_hours'] += entry_hours

    for user_id in user_tasks_data:
        for project_name in user_tasks_data[user_id]['projects']:
            tasks_list = list(user_tasks_data[user_id]['projects'][project_name]['tasks'].values())
            tasks_list.sort(key=lambda x: x['hours'], reverse=True)
            user_tasks_data[user_id]['projects'][project_name]['tasks'] = tasks_list

    recent_activity_map = build_user_recent_activity_map(timesheets_5d, users, all_task_map, project_names)

    project_hours_5d = defaultdict(float)
    for ts in timesheets_5d:
        project_data = ts.get('project_id')
        if not project_data:
            continue
        project_id = project_data[0]
        project_name = project_names.get(
            project_id,
            project_data[1] if isinstance(project_data, list) and len(project_data) > 1 else 'No Project'
        )
        project_hours_5d[project_name] += float(ts.get('unit_amount', 0) or 0)

    top_projects_html = build_top_projects_summary_html(project_hours_5d, user_tasks_data)
    timeline_days = max(5, int(round(five_day_window_hours / 24)))
    timeline_label = f'Last {timeline_days} Days'
    projects_bubble_html = generate_project_bubble_chart_html(project_hours_5d, timeline_label)
    projects_tasks_gantt_html = generate_projects_tasks_gantt_html(recent_activity_map)

    project_effort_by_priority = defaultdict(lambda: {'P1': 0.0, 'P2': 0.0, 'P3': 0.0})
    for ts in timesheets_5d:
        task_data = ts.get('task_id')
        project_data = ts.get('project_id')
        if not task_data or not project_data:
            continue

        task_id = task_data[0]
        project_id = project_data[0]
        task = all_task_map.get(task_id, {})
        priority_label = get_priority_label(task.get('priority', '0'))
        project_name = project_names.get(project_id, project_data[1] if isinstance(project_data, list) and len(project_data) > 1 else 'No Project')
        project_effort_by_priority[project_name][priority_label] += float(ts.get('unit_amount', 0) or 0)

    project_criticality_rows = []
    for project_name, pvals in project_effort_by_priority.items():
        total_effort = pvals['P1'] + pvals['P2'] + pvals['P3']
        if total_effort <= 0:
            continue
        project_criticality_rows.append({
            'project_name': project_name,
            'p1': round(pvals['P1'], 2),
            'p2': round(pvals['P2'], 2),
            'p3': round(pvals['P3'], 2),
            'total': round(total_effort, 2),
        })

    project_heatmap_html = generate_project_criticality_heatmap_html(project_criticality_rows)

    print(f"\n\nGenerating user activity charts...")
    gantt_charts = generate_per_user_gantt_charts(user_tasks_data, SHIFT_HOURS, recent_activity_map)

    print("Building paginated report pages...")

    all_user_pages = []
    active_user_ids = set(user_tasks_data.keys())

    all_team_members = {}
    for uid, u in users.items():
        all_team_members[u['name']] = {'id': uid, 'name': u['name'], 'active': uid in active_user_ids}

    sorted_names = sorted(all_team_members.keys())

    utilization_rows = []
    for uid in active_user_ids:
        user_data = user_tasks_data[uid]
        shift_data = calculate_shift_metrics(user_data.get('total_hours', 0), SHIFT_HOURS)
        utilization_rows.append({
            'name': user_data.get('name', 'Unknown'),
            'logged': shift_data['logged'],
            'utilization': shift_data['utilization'],
            'overtime': shift_data['overtime'],
            'status': shift_data['status'],
            'band': shift_data['band'],
        })

    total_logged = sum(r['logged'] for r in utilization_rows)
    total_overtime = sum(r['overtime'] for r in utilization_rows)
    avg_utilization = (sum(r['utilization'] for r in utilization_rows) / len(utilization_rows)) if utilization_rows else 0
    under_count = len([r for r in utilization_rows if r['band'] == 'under'])
    healthy_count = len([r for r in utilization_rows if r['band'] == 'healthy'])
    over_count = len([r for r in utilization_rows if r['band'] == 'over'])

    team_summary = {
        'shift_hours': SHIFT_HOURS,
        'total_members': len(sorted_names),
        'active_members': len(active_user_ids),
        'missing_members': len(sorted_names) - len(active_user_ids),
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

    total_pages = len(sorted_names) + 1
    overview_page = generate_team_overview_page_html(team_summary, 0, total_pages)
    all_user_pages.append({
        'html': overview_page,
        'name': 'Team Overview',
    })

    for idx, name in enumerate(sorted_names, start=1):
        member = all_team_members[name]
        is_active = member['active']

        if is_active:
            user_id = member['id']
            data = user_tasks_data[user_id]
            page_html = generate_user_page_html(user_id, data, hours, SHIFT_HOURS, gantt_charts, idx, total_pages, has_activity=True)
        else:
            dummy_data = {
                'name': name,
                'email': '',
                'projects': {},
                'total_hours': 0,
            }
            page_html = generate_user_page_html(None, dummy_data, hours, SHIFT_HOURS, gantt_charts, idx, total_pages, has_activity=False)

        all_user_pages.append({
            'html': page_html,
            'name': name,
        })

    landing_filter_data = build_landing_filter_data(
        user_tasks_data,
        all_tasks,
        users,
        project_names,
        milestones,
    )

    html_report = generate_html_report(
        all_user_pages,
        generated_date,
        hours,
        SHIFT_HOURS,
        gantt_charts,
        landing_filter_data,
    )

    html_output = f"team_activity_paginated_report_{hours}h.html"
    with open(html_output, "w", encoding="utf-8") as f:
        f.write(html_report)
    print(f"Paginated HTML report saved to: {html_output}")

    send_email(html_report, REPORT_RECIPIENTS, hours)

    print(f"\nTotal team members: {len(sorted_names)}")
    print(f"  - Active: {len(active_user_ids)}")
    print(f"  - No update: {len(sorted_names) - len(active_user_ids)}")
    print("\n✅ Paginated report generation complete!")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        error_details = traceback.format_exc()
        print(f"Report generation failed: {exc}\n{error_details}")
        try:
            import sys
            sys.path.insert(0, "backend")
            from alerting import AlertService
            AlertService(config_path="config.yaml").notify(
                subject="Odoo Automation: Report generation failed",
                message=f"team_activity_paginated_report.py crashed:\n{exc}"
            )
        except Exception as alert_err:
            print(f"Alerting itself failed: {alert_err}")
        raise
