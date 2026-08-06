"""
Ported report generation from team_activity_paginated_report.py
Produces a paginated HTML report with per-user pages, charts, and drill-down filters.
"""
import re
import html as html_mod
import json
from datetime import datetime, timedelta
from collections import defaultdict
import plotly
import plotly.figure_factory as ff
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Helpers ──

def clean_html(value):
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", "", value)
    return html_mod.unescape(value).strip()

def format_log_notes(value):
    if not value:
        return ""
    value = html_mod.unescape(value)
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

def get_priority_label(priority):
    return {'0': 'P3', '1': 'P2', '2': 'P1'}.get(str(priority), 'P3')

def normalize_stage_bucket(stage_name):
    stage = (stage_name or '').lower()
    if 'done' in stage or 'close' in stage:
        return 'Done'
    if 'progress' in stage or 'review' in stage or 'develop' in stage:
        return 'In Progress'
    if 'cancel' in stage:
        return 'Cancelled'
    return 'Open'

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

# ── Data builders ──

def build_user_task_summary(data):
    summary = {'total': 0, 'main': 0, 'subtasks': 0, 'open': 0, 'progress': 0, 'done': 0, 'cancel': 0, 'p1': 0, 'p2': 0, 'p3': 0, 'top_tasks': []}
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

def build_landing_filter_data(user_tasks_data, all_tasks, users, project_names, milestones):
    projects_map = {}
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
            projects_map[project_name] = {'name': project_name, 'engineers': {}}
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
                engineers_map[engineer_name] = {'name': engineer_name, 'tasks': []}
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
            engineer_rows.append({'name': engineer_name, 'tasks': tasks})
        projects.append({'name': project_name, 'engineers': engineer_rows})
    return {'projects': projects}

# ── Chart generators ──

def generate_recent_task_timeline_chart(user_name, activity_rows):
    if not activity_rows:
        return "<div style='padding:14px; color:#64748b;'>No task activity found in the last 5 days.</div>"
    stage_colors = {'Open': '#1971c2', 'In Progress': '#f08c00', 'Done': '#2b8a3e', 'Cancelled': '#c92a2a'}
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
        key=lambda x: x[1], reverse=True)[:12]
    selected_tasks = [task_name for task_name, _ in task_totals]
    if not selected_tasks:
        return "<div style='padding:14px; color:#64748b;'>No non-zero task activity found.</div>"
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
            gantt_rows.append({'Task': label, 'Start': segment_start.strftime("%Y-%m-%d"), 'Finish': finish_date.strftime("%Y-%m-%d"), 'Resource': task_status.get(task_name, 'Open')})
            segment_start = cur
            segment_end = cur
            segment_hours = date_hours.get(cur.strftime("%Y-%m-%d"), 0)
        finish_date = segment_end + timedelta(days=1)
        label = task_name if segment_hours <= 0 else f"{task_name} ({segment_hours:.1f}h)"
        gantt_rows.append({'Task': label, 'Start': segment_start.strftime("%Y-%m-%d"), 'Finish': finish_date.strftime("%Y-%m-%d"), 'Resource': task_status.get(task_name, 'Open')})
    if not gantt_rows:
        return "<div style='padding:14px; color:#64748b;'>No activity periods found for Gantt timeline.</div>"
    fig = ff.create_gantt(gantt_rows, index_col='Resource', colors=stage_colors, show_colorbar=True, group_tasks=True, showgrid_x=True, showgrid_y=True, title='5-Day Activity Periods (Gantt)')
    timeline_height = min(360, max(240, 58 + len(gantt_rows) * 16))
    fig.update_layout(height=timeline_height, margin=dict(l=18, r=18, t=55, b=16), paper_bgcolor='white', plot_bgcolor='white', legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0))
    fig.update_xaxes(showgrid=True, gridcolor='#edf2f7', tickformat='%b %d')
    fig.update_yaxes(showgrid=True, gridcolor='#edf2f7')
    return plotly.io.to_html(fig, full_html=False, include_plotlyjs='cdn')

def build_user_recent_activity_map(timesheets, task_map=None):
    aggregate = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    task_info = {}
    for ts in timesheets:
        user_name = ts.get('user_name')
        task_id = ts.get('task_id')
        if not user_name or not task_id:
            continue
        date_str = (ts.get('date', '') or '')[:10]
        if not date_str:
            continue
        aggregate[user_name][task_id][date_str] += float(ts.get('hours', 0) or 0)
        if task_id not in task_info:
            task_name = ts.get('task_name', f'Task #{task_id}')
            if len(task_name) > 52:
                task_name = task_name[:49] + '...'
            task_info[task_id] = {
                'task_name': task_name,
                'stage': ts.get('stage', 'Unknown'),
                'project_name': ts.get('project_name', 'No Project'),
            }
    result = {}
    for user_name, task_map in aggregate.items():
        rows = []
        for task_id, date_map in task_map.items():
            info = task_info.get(task_id, {})
            task_name = info.get('task_name', f'Task #{task_id}')
            stage_name = info.get('stage', 'Unknown')
            stage_bucket = normalize_stage_bucket(stage_name)
            project_name = info.get('project_name', 'No Project')
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
                note_lines.append(f"<li><strong>{html_mod.escape(note['task_name'])}</strong>: {html_mod.escape(short_summary)}</li>")
            notes_html = f"<ul>{''.join(note_lines)}</ul>"
        else:
            notes_html = "<div class='project-note-empty'>No summarized notes available.</div>"
        cards.append(f"""
            <div class='project-summary-card'>
                <div class='project-summary-head'>
                    <span class='project-summary-name'>{html_mod.escape(project_name)}</span>
                    <span class='project-summary-hours'>{hours:.1f}h</span>
                </div>
                <div class='project-summary-notes'>{notes_html}</div>
            </div>""")
    return f"<div class='project-summary-grid'>{''.join(cards)}</div>"

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
    palette = ['#1971c2', '#2b8a3e', '#f08c00', '#c92a2a', '#5f3dc4', '#0b7285', '#a61e4d', '#495057', '#1864ab', '#2f9e44', '#d9480f', '#364fc7']
    projects = sorted({row['Resource'] for row in gantt_rows})
    project_colors = {name: palette[i % len(palette)] for i, name in enumerate(projects)}
    fig = ff.create_gantt(gantt_rows, index_col='Resource', colors=project_colors, show_colorbar=True, group_tasks=True, showgrid_x=True, showgrid_y=True, title='Projects & Tasks Activity Periods (Last 5 Days)')
    fig.update_layout(height=min(620, max(320, 82 + len(gantt_rows) * 12)), margin=dict(l=18, r=18, t=55, b=16), paper_bgcolor='white', plot_bgcolor='white')
    fig.update_xaxes(showgrid=True, gridcolor='#edf2f7', tickformat='%b %d')
    fig.update_yaxes(showgrid=True, gridcolor='#edf2f7')
    return plotly.io.to_html(fig, full_html=False, include_plotlyjs='cdn')

def generate_project_criticality_heatmap_html(project_criticality_rows):
    if not project_criticality_rows:
        return "<div style='padding:14px; color:#64748b;'>No project effort data found in the last 5 days.</div>"
    sorted_rows = sorted(project_criticality_rows, key=lambda x: x['total'], reverse=True)[:18]
    y_projects = [r['project_name'] for r in sorted_rows]
    z_matrix = [[r['p1'], r['p2'], r['p3']] for r in sorted_rows]
    fig = go.Figure(data=go.Heatmap(z=z_matrix, x=['P1 (Critical)', 'P2 (High)', 'P3 (Normal)'], y=y_projects, colorscale='YlOrRd', colorbar=dict(title='Hours'), hovertemplate='<b>%{y}</b><br>%{x}<br>Effort: %{z:.2f}h<extra></extra>'))
    fig.update_layout(title='Project Criticality vs Effort (Last 5 Days)', height=max(360, 130 + len(y_projects) * 24), margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor='white', plot_bgcolor='white')
    fig.update_xaxes(side='top')
    return plotly.io.to_html(fig, full_html=False, include_plotlyjs='cdn')

def generate_project_bubble_chart_html(project_hours_5d, timeline_label='Last 5 Days'):
    if not project_hours_5d:
        return "<div style='padding:14px; color:#64748b;'>No project effort data found for bubble chart.</div>"
    rows = sorted(project_hours_5d.items(), key=lambda x: x[1], reverse=True)[:12]
    max_hours = max(h for _, h in rows) if rows else 1
    fig = go.Figure()
    for idx, (project_name, hours) in enumerate(rows):
        bubble_size = 16 + (hours / max_hours) * 34
        fig.add_trace(go.Scatter(x=[hours], y=[len(rows) - idx], mode='markers', name=project_name, marker=dict(size=bubble_size, sizemode='diameter', opacity=0.78), hovertemplate='<b>%{text}</b><br>Hours: %{x:.2f}h<extra></extra>', text=[project_name], showlegend=True))
    fig.update_layout(title=f'Projects Worked vs Time (Bubble) - {timeline_label}', height=360, margin=dict(l=20, r=210, t=62, b=20), paper_bgcolor='white', plot_bgcolor='white', xaxis=dict(title=f'Hours Logged ({timeline_label})', gridcolor='#e9ecef'), yaxis=dict(showticklabels=False, showgrid=False, zeroline=False), legend=dict(orientation='v', xanchor='left', x=1.02, yanchor='top', y=1.0, font=dict(size=10)))
    return plotly.io.to_html(fig, full_html=False, include_plotlyjs='cdn')

def generate_per_user_gantt_charts(user_tasks_data, shift_hours, recent_activity_map):
    gantt_charts = {}
    for user_id, data in user_tasks_data.items():
        user_name = data['name']
        shift = calculate_shift_metrics(data.get('total_hours', 0), shift_hours)
        util_color_map = {'under': '#f08c00', 'healthy': '#0b7285', 'over': '#c92a2a'}
        project_totals = sorted(
            [(project_name, project_data.get('total_hours', 0)) for project_name, project_data in data['projects'].items()],
            key=lambda x: x[1], reverse=True)
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
            fig_summary = make_subplots(rows=1, cols=2, specs=[[{'type': 'domain'}, {'type': 'domain'}]], horizontal_spacing=0.22, subplot_titles=('Project Split', 'Task Split'))
            fig_summary.add_trace(go.Pie(labels=project_names, values=project_hours, hole=0.62, textinfo='label', textposition='outside', automargin=True, hovertemplate='<b>%{label}</b><br>%{value:.2f}h (%{percent})<extra></extra>'), row=1, col=1)
            fig_summary.add_trace(go.Pie(labels=task_names, values=task_hours, hole=0.62, textinfo='label', textposition='outside', automargin=True, hovertemplate='<b>%{label}</b><br>%{value:.2f}h (%{percent})<extra></extra>'), row=1, col=2)
            fig_summary.data[0].update(domain={'x': [0.02, 0.42], 'y': [0.08, 0.98]})
            fig_summary.data[1].update(domain={'x': [0.58, 0.98], 'y': [0.08, 0.98]})
            fig_summary.update_layout(title=f"Workload Snapshot (Donut) - Utilization {shift['utilization']:.1f}%", height=255, margin=dict(l=10, r=10, t=52, b=10), paper_bgcolor='white', plot_bgcolor='white', font=dict(size=11, color='#1f2937'), showlegend=False)
            summary_chart_html = plotly.io.to_html(fig_summary, full_html=False, include_plotlyjs='cdn')
        try:
            recent_rows = recent_activity_map.get(user_name, []) if recent_activity_map else []
            plot_html = generate_recent_task_timeline_chart(user_name, recent_rows)
            gantt_charts[user_name] = {'workload_html': summary_chart_html, 'timeline_html': plot_html}
        except Exception as e:
            gantt_charts[user_name] = {'workload_html': f"<p>Could not generate chart: {str(e)}</p>", 'timeline_html': ""}
    return gantt_charts

# ── Page generators ──

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
                    <td><strong>{task_name}</strong></td>
                    <td><span class="priority-tag {priority_class}">{priority_label}</span></td>
                    <td>{milestone_name}{f' <span class="milestone-deadline">({milestone_deadline})</span>' if milestone_deadline else ''}</td>
                    <td>{stage}</td>
                    <td>{task_owner}</td>
                    <td>{open_date}</td>
                    <td>{age}</td>
                    <td>{deadline}</td>
                    <td><strong>{logged}</strong></td>
                    <td>{progress}</td>
                </tr>"""
            if description_html:
                rows_html += f"""<tr><td colspan="10"><div class="task-description"><div class="task-description-title">Description</div>{description_html}</div></td></tr>"""
            if log_summary_html:
                rows_html += f"""<tr><td colspan="10">{log_summary_html}</td></tr>"""
        if not rows_html:
            rows_html = '<tr><td colspan="10"><div class="no-tasks">No task data</div></td></tr>'
        project_sections_html += f"""
            <div class="project-section">
                <div class="project-title"><span>{project_name}</span><span class="project-hours">{project_data.get('total_hours', 0):.1f}h</span></div>
                <table class="insights-table">
                    <thead><tr><th>Task / Work Description</th><th>Priority</th><th>Milestone</th><th>Stage</th><th>Owner</th><th>Open Date</th><th>Age</th><th>Deadline</th><th>Logged</th><th>Progress</th></tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>"""
    return f"""<div class="project-section"><div class="project-title"><span>Detailed Task View</span></div></div>{project_sections_html}"""

def generate_user_page_html(user_id, data, hours, shift_hours, gantt_charts, idx, total, has_activity):
    page_id = f"page-{idx}"
    shift = calculate_shift_metrics(data.get('total_hours', 0), shift_hours)
    utilization_class = f"utilization-{shift.get('band', 'healthy')}"
    if not has_activity:
        status_class = "status-no-update"
        activity_html = f"""<div style="text-align:center;padding:80px 20px;"><div style="font-size:48px;color:#dc3545;margin-bottom:20px;">&#9888;</div><div style="font-size:24px;font-weight:700;color:#dc3545;margin-bottom:15px;">No Update - Move to Next Member</div><div style="font-size:14px;color:#6c757d;">This team member has no timesheet entries logged in the last {hours} hours.</div></div>"""
        detailed_html = ""
        gantt_html = ""
    else:
        status_class = "status-active"
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
                task_logs_html += f"""<div class="task-log-item"><div class="task-log-title">{row['title']}</div><div class="task-log-project">{row['project']} | {row['hours']:.1f}h</div><div class="task-log-summary">{safe_summary}</div>{authors_html}</div>"""
            gantt_html = f"""<div class="analytics-layout"><div class="analytics-top-row"><div class="analytics-panel"><h4>Workload Snapshot</h4><div class="panel-content chart-content">{chart_pack.get('workload_html', '')}</div></div><div class="analytics-panel"><h4>5-Day Task Timeline & Status</h4><div class="panel-content chart-content">{chart_pack.get('timeline_html', '')}</div></div></div><div class="analytics-bottom-row"><div class="analytics-panel"><h4>Task Summary</h4><div class="panel-content summary-content"><div class="task-log-list">{task_logs_html if task_logs_html else '<div class="task-log-empty">No task summaries available.</div>'}</div></div></div></div></div>"""
    page_html = f"""
    <div class="user-page {status_class}" id="{page_id}" data-index="{idx}">
        <div class="nav-bar">
            <div><span class="nav-arrow" onclick="navigate({idx - 1})" {'style="visibility:hidden"' if idx == 0 else ''}>&#9664; Previous</span></div>
            <div class="page-indicator"><span class="status-indicator {status_class}">&#9679;</span><span class="user-name-nav">{data['name']}</span><span class="page-count">{idx + 1} / {total}</span></div>
            <div><span class="nav-arrow" onclick="navigate({idx + 1})" {'style="visibility:hidden"' if idx == total - 1 else ''}>Next &#9654;</span></div>
        </div>
        <div class="user-header">
            <div class="user-header-left">
                <h2>{data['name']}</h2>
                <div class="user-meta">
                    <span class="status-badge {status_class}">&#9679; {'Active' if has_activity else 'No Update'}</span>
                    {f'<span class="hours-badge">{data["total_hours"]:.1f}h logged</span>' if has_activity else ''}
                </div>
            </div>
        </div>
        <div class="summary-grid compact-summary-grid">
            <div class="summary-card"><div class="summary-label">Logged</div><div class="summary-value">{shift['logged']:.1f}h</div></div>
            <div class="summary-card"><div class="summary-label">Shift Target</div><div class="summary-value">{shift['target']:.1f}h</div></div>
            <div class="summary-card"><div class="summary-label">Remaining</div><div class="summary-value">{shift['remaining']:.1f}h</div></div>
            <div class="summary-card"><div class="summary-label">Overtime</div><div class="summary-value">{shift['overtime']:.1f}h</div></div>
            <div class="summary-card"><div class="summary-label">Shift Utilization</div><div class="summary-value {utilization_class}">{shift['utilization']:.1f}% <span class="utilization-status {utilization_class}">{shift['status']}</span></div></div>
        </div>
        {gantt_html}
        {detailed_html}
        {activity_html}
    </div>"""
    return page_html

def generate_team_overview_page_html(team_summary, idx, total):
    page_id = f"page-{idx}"
    utilization_rows = team_summary.get('utilization_rows', [])
    top_projects_html = team_summary.get('top_projects_html', '')
    projects_bubble_html = team_summary.get('projects_bubble_html', '')
    projects_tasks_gantt_html = team_summary.get('projects_tasks_gantt_html', '')
    return f"""
    <div class="user-page status-overview" id="{page_id}" data-index="{idx}">
        <div class="nav-bar">
            <div><span class="nav-arrow" onclick="navigate({idx - 1})" style="visibility:hidden">&#9664; Previous</span></div>
            <div class="page-indicator"><span class="status-indicator status-active">&#9679;</span><span class="user-name-nav">Team Overview</span><span class="page-count">{idx + 1} / {total}</span></div>
            <div><span class="nav-arrow" onclick="navigate({idx + 1})" {'style="visibility:hidden"' if idx == total - 1 else ''}>Next &#9654;</span></div>
        </div>
        <div class="user-header">
            <div class="user-header-left">
                <h2>Team Snapshot</h2>
                <div class="user-meta"><span class="hours-badge">Shift baseline {team_summary['shift_hours']:.1f}h</span></div>
            </div>
        </div>
        <div class="project-section" id="landing-drilldown-panel">
            <div class="project-title"><span>Task Drilldown Filters</span></div>
            <div class="filter-chain-grid">
                <div class="filter-item"><label for="filter-project">Project</label><select id="filter-project"><option value="">Select Project</option></select></div>
                <div class="filter-item"><label for="filter-engineer">Engineer</label><select id="filter-engineer" disabled><option value="">Select Engineer</option></select></div>
                <div class="filter-item"><label for="filter-task">Task</label><select id="filter-task" disabled><option value="">Select Task</option></select></div>
            </div>
            <div id="task-drilldown-empty" class="task-drilldown-empty">Select Project -> Engineer -> Task to view summary, status, age, and technical details.</div>
            <div id="task-drilldown-details" class="task-drilldown-details" style="display:none;">
                <div class="drilldown-head"><div class="drilldown-title" id="drill-task-title">-</div><div class="drilldown-badges"><span class="priority-tag priority-p3" id="drill-task-priority">P3</span><span class="status-pill" id="drill-task-status">Unknown</span></div></div>
                <div class="drilldown-grid" id="drilldown-grid"></div>
                <div class="drilldown-summary-box"><div class="drilldown-summary-title">Summary</div><div id="drill-task-summary">-</div></div>
                <div class="drilldown-description-box" id="drill-task-description-wrap" style="display:none;"><div class="drilldown-summary-title">Description</div><div id="drill-task-description"></div></div>
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
        <div class="project-section"><div class="project-title"><span>Top 5 Projects Summary</span></div>{top_projects_html}</div>
        <div class="project-section"><div class="project-title"><span>Projects Worked vs Time (Bubble)</span></div><div style="overflow-x:auto;">{projects_bubble_html}</div></div>
        <div class="project-section"><div class="project-title"><span>Projects and Tasks Timeline (Last 5 Days)</span></div><div style="overflow-x:auto;">{projects_tasks_gantt_html}</div></div>
    </div>"""

# ── Main HTML report wrapper ──

def generate_html_report(user_pages_data, generated_date, hours, shift_hours, gantt_charts, landing_filter_data):
    all_pages = [p for p in user_pages_data]
    pages_html = "".join(p['html'] for p in all_pages)
    total_pages = len(all_pages)

    nav_items_html = ""
    for idx, page in enumerate(all_pages):
        active_attr = ' active' if idx == 0 else ''
        name = html_mod.escape(page.get('name', f'Page {idx+1}'))
        nav_items_html += f'''<div class="nav-menu-item{active_attr}" data-page="{idx}" onclick="showPage({idx}); closeNavMenu();">{name}</div>'''

    overview_filter_json = json.dumps(landing_filter_data)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
<title>Team Activity Report - Last {hours}h</title>
<style>
* {{ box-sizing: border-box; }}
:root {{ --bg: #f3f6fa; --card: #ffffff; --text: #1f2937; --muted: #6b7280; --brand: #0b7285; --brand-soft: #e6fcf5; --danger: #c92a2a; --ok: #2b8a3e; --line: #dbe4ef; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 0; background: radial-gradient(circle at top right, #e3fafc 0%, var(--bg) 35%, #edf2f7 100%); color: var(--text); }}
.container {{ width: 100%; max-width: none; margin: 0; padding: 18px 18px 24px; }}
h1 {{ color: #0f172a; font-size: 28px; margin-bottom: 6px; letter-spacing: 0.2px; }}
.meta {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
.report-header {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; margin-bottom: 18px; box-shadow: 0 8px 20px rgba(15,23,42,0.04); }}
.nav-menu-bar {{ margin-bottom: 18px; position: relative; }}
.nav-menu-toggle {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 10px 18px; font-size: 14px; font-weight: 600; color: #0b7285; cursor: pointer; transition: all 0.2s; }}
.nav-menu-toggle:hover {{ background: #e6fcf5; border-color: #0b7285; }}
.nav-menu-dropdown {{ display: none; position: absolute; top: 100%; left: 0; z-index: 200; background: white; border: 1px solid #dee2e6; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); max-height: 400px; overflow-y: auto; min-width: 220px; margin-top: 4px; }}
.nav-menu-item {{ padding: 10px 16px; cursor: pointer; font-size: 13px; color: #1f2937; border-bottom: 1px solid #f1f3f5; transition: background 0.15s; }}
.nav-menu-item:last-child {{ border-bottom: none; }}
.nav-menu-item:hover {{ background: #e6fcf5; color: #0b7285; }}
.nav-menu-item.active {{ background: #0b7285; color: white; font-weight: 600; }}
.nav-bar {{ display: flex; justify-content: space-between; align-items: center; background: white; padding: 12px 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; position: sticky; top: 10px; z-index: 100; }}
.nav-arrow {{ cursor: pointer; padding: 8px 18px; border-radius: 6px; font-size: 14px; font-weight: 600; color: #495057; background: #f8f9fa; border: 1px solid #dee2e6; transition: all 0.2s; user-select: none; }}
.nav-arrow:hover {{ background: #4a90d9; color: white; border-color: #4a90d9; }}
.page-indicator {{ display: flex; align-items: center; gap: 10px; font-size: 14px; color: #495057; }}
.status-indicator {{ font-size: 10px; }}
.status-indicator.status-active {{ color: #28a745; }}
.status-indicator.status-no-update {{ color: #dc3545; }}
.user-name-nav {{ font-weight: 600; font-size: 15px; }}
.page-count {{ color: #868e96; font-size: 13px; background: #f8f9fa; padding: 3px 10px; border-radius: 12px; }}
.user-page {{ background: white; border-radius: 12px; box-shadow: 0 8px 22px rgba(15,23,42,0.06); overflow: hidden; }}
.user-page.status-no-update {{ border: 2px solid #dc3545; }}
.user-page.status-active {{ border: 2px solid #28a745; }}
.user-page.status-overview {{ border: 2px solid #1864ab; }}
.user-page:not(.active) {{ display: none; }}
.user-header {{ padding: 20px 20px 8px; display: flex; justify-content: space-between; align-items: flex-start; }}
.user-header h2 {{ margin: 0; color: #2c3e50; font-size: 22px; }}
.user-header-left {{ display: flex; flex-direction: column; gap: 8px; }}
.user-meta {{ display: flex; align-items: center; gap: 10px; }}
.status-badge {{ padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
.status-badge.status-active {{ background: #d4edda; color: #155724; }}
.status-badge.status-no-update {{ background: #f8d7da; color: #721c24; }}
.hours-badge {{ background: #e7f5ff; color: #1864ab; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
.summary-grid {{ display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; padding: 0 20px 14px; }}
.compact-summary-grid {{ gap: 8px; padding: 0 15px 10px; }}
.compact-summary-grid .summary-card {{ padding: 7px 10px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
.compact-summary-grid .summary-label {{ margin-bottom: 0; font-size: 10px; line-height: 1; }}
.compact-summary-grid .summary-value {{ font-size: 16px; line-height: 1; white-space: nowrap; }}
.compact-summary-grid .utilization-status {{ margin-left: 4px; font-size: 11px; }}
.overview-grid {{ grid-template-columns: repeat(9, minmax(110px, 1fr)); }}
.summary-card {{ background: #f8fbff; border: 1px solid #e1ecf5; border-radius: 10px; padding: 10px; }}
.summary-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 5px; font-weight: 600; }}
.summary-value {{ font-size: 20px; font-weight: 700; color: #0f172a; }}
.utilization-status {{ font-size: 12px; font-weight: 600; color: #64748b; margin-left: 6px; }}
.summary-value.utilization-under, .utilization-status.utilization-under {{ color: #f08c00; }}
.summary-value.utilization-healthy, .utilization-status.utilization-healthy {{ color: #0b7285; }}
.summary-value.utilization-over, .utilization-status.utilization-over {{ color: #c92a2a; }}
.project-section {{ margin: 15px 15px 18px; padding: 15px; background: #f8fafc; border-radius: 10px; border-left: 4px solid #1971c2; border: 1px solid #e1e8f0; }}
.project-title {{ font-size: 16px; font-weight: 600; color: #2c3e50; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }}
.project-hours {{ background: #e3f2fd; color: #1976d2; padding: 3px 10px; border-radius: 10px; font-size: 12px; font-weight: 500; }}
.insights-table, .task-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.insights-table th, .task-table th {{ background: #f1f5f9; padding: 8px 10px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; color: #475569; border-bottom: 2px solid #e2e8f0; }}
.insights-table td, .task-table td {{ padding: 8px 10px; border-bottom: 1px solid #eef2f6; }}
.priority-tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }}
.priority-p1 {{ background: #ffe3e3; color: #c92a2a; }}
.priority-p2 {{ background: #fff3bf; color: #f08c00; }}
.priority-p3 {{ background: #e6fcf5; color: #2b8a3e; }}
.summary-box {{ background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 10px; margin-top: 6px; font-size: 13px; color: #334155; }}
.task-description {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; margin-top: 4px; font-size: 13px; }}
.task-description-title {{ font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700; margin-bottom: 4px; }}
.no-tasks {{ text-align: center; padding: 20px; color: #94a3b8; }}
.analytics-layout {{ padding: 0 15px 10px; }}
.analytics-top-row {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; margin-bottom: 8px; }}
.analytics-bottom-row {{ display: grid; grid-template-columns: minmax(0, 1fr); }}
.analytics-panel {{ border: 1px solid #dbe4ef; border-radius: 10px; background: #ffffff; min-height: 280px; display: flex; flex-direction: column; min-width: 0; overflow: hidden; }}
.analytics-panel h4 {{ margin: 0; padding: 12px 12px 0; color: #0f172a; font-size: 14px; }}
.panel-content {{ padding: 6px 8px 8px; flex: 1; overflow-x: auto; min-width: 0; }}
.panel-content .plotly-graph-div {{ width: 100% !important; min-width: 0 !important; }}
.chart-content > div {{ min-width: 0; width: 100%; }}
.task-log-list {{ display: flex; flex-direction: column; gap: 10px; }}
.task-log-item {{ border: 1px solid #dbe7f3; border-radius: 8px; background: #fcfdff; padding: 10px; }}
.task-log-title {{ font-size: 16px; font-weight: 700; color: #1f2937; margin-bottom: 4px; }}
.task-log-project {{ font-size: 11px; font-weight: 600; color: #64748b; margin-bottom: 7px; }}
.task-log-summary {{ font-size: 16px; color: #334155; line-height: 1.5; }}
.task-log-meta {{ font-size: 11px; color: #64748b; margin-top: 7px; }}
.task-log-empty {{ font-size: 12px; color: #64748b; padding: 10px; }}
.filter-chain-grid {{ display: grid; grid-template-columns: repeat(3, minmax(180px, 1fr)); gap: 10px; margin-bottom: 12px; }}
.filter-item {{ display: flex; flex-direction: column; gap: 6px; }}
.filter-item label {{ font-size: 12px; font-weight: 700; color: #334155; }}
.filter-item select {{ border: 1px solid #cbd5e1; border-radius: 8px; background: #ffffff; color: #1f2937; font-size: 13px; padding: 9px 10px; }}
.filter-item select:disabled {{ background: #f8fafc; color: #94a3b8; }}
.task-drilldown-empty {{ font-size: 13px; color: #64748b; padding: 10px; border: 1px dashed #cbd5e1; border-radius: 8px; background: #f8fafc; }}
.task-drilldown-details {{ border: 1px solid #dbe7f3; border-radius: 10px; background: #ffffff; padding: 12px; }}
.drilldown-head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }}
.drilldown-title {{ font-size: 15px; font-weight: 700; color: #0f172a; }}
.drilldown-badges {{ display: flex; gap: 8px; align-items: center; }}
.status-pill {{ display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; background: #e2e8f0; color: #334155; }}
.drilldown-grid {{ display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 8px; margin-bottom: 10px; }}
.drilldown-cell {{ border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; padding: 8px; }}
.drilldown-cell-label {{ font-size: 10px; letter-spacing: 0.35px; text-transform: uppercase; color: #64748b; margin-bottom: 4px; font-weight: 700; }}
.drilldown-cell-value {{ font-size: 13px; color: #1f2937; font-weight: 600; }}
.drilldown-summary-box, .drilldown-description-box {{ border: 1px solid #dbe7f3; border-radius: 8px; background: #fcfdff; padding: 10px; font-size: 13px; line-height: 1.5; color: #334155; margin-top: 8px; }}
.drilldown-summary-title {{ font-size: 11px; text-transform: uppercase; color: #475569; font-weight: 700; letter-spacing: 0.4px; margin-bottom: 5px; }}
.project-summary-grid {{ display: grid; grid-template-columns: repeat(5, minmax(200px, 1fr)); gap: 10px; }}
.project-summary-card {{ border: 1px solid #dbe7f3; background: #fcfdff; border-radius: 10px; padding: 10px; min-width: 0; }}
.project-summary-head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }}
.project-summary-name {{ font-size: 13px; font-weight: 700; color: #1f2937; line-height: 1.3; }}
.project-summary-hours {{ font-size: 11px; font-weight: 700; color: #0b7285; background: #e6fcf5; border-radius: 999px; padding: 3px 8px; white-space: nowrap; }}
.project-summary-notes {{ font-size: 12px; color: #475569; line-height: 1.5; }}
.project-summary-notes ul {{ margin: 4px 0 0; padding-left: 16px; }}
.project-summary-notes li {{ margin-bottom: 4px; }}
.project-summary-notes strong {{ color: #1f2937; }}
.project-note-empty {{ font-size: 12px; color: #94a3b8; padding: 2px 0; }}
.keyboard-hint {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 10px; }}
@media (max-width: 768px) {{
  .container {{ padding: 10px; }}
  .report-header {{ padding: 12px; }}
  h1 {{ font-size: 20px; }}
  .nav-bar {{ padding: 8px 12px; flex-wrap: wrap; gap: 6px; }}
  .nav-arrow {{ padding: 10px 14px; font-size: 13px; min-width: 44px; text-align: center; }}
  .summary-grid {{ grid-template-columns: repeat(2, 1fr); gap: 6px; padding: 0 10px 8px; }}
  .overview-grid {{ grid-template-columns: repeat(3, 1fr); }}
  .compact-summary-grid .summary-card {{ padding: 6px 8px; flex-direction: column; align-items: flex-start; gap: 2px; }}
  .compact-summary-grid .summary-value {{ font-size: 14px; }}
  .analytics-top-row {{ grid-template-columns: 1fr; }}
  .filter-chain-grid {{ grid-template-columns: 1fr; }}
  .project-summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .drilldown-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .user-header {{ padding: 14px 14px 6px; }}
  .user-header h2 {{ font-size: 18px; }}
  .project-section {{ margin: 10px; padding: 10px; }}
  .insights-table {{ font-size: 12px; }}
  .insights-table th, .insights-table td {{ padding: 6px; }}
  .insights-table td:first-child {{ max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .nav-menu-toggle {{ padding: 8px 14px; font-size: 13px; }}
  .nav-menu-item {{ padding: 12px 16px; }}
  .analytics-panel {{ min-height: auto; }}
  .page-count {{ font-size: 11px; }}
  .user-name-nav {{ font-size: 13px; }}
}}
@media (max-width: 480px) {{
  .container {{ padding: 6px; }}
  h1 {{ font-size: 17px; }}
  .report-header {{ padding: 10px; }}
  .summary-grid {{ grid-template-columns: 1fr 1fr; gap: 4px; padding: 0 6px 6px; }}
  .overview-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .project-summary-grid {{ grid-template-columns: 1fr; }}
  .project-summary-card {{ padding: 10px; }}
  .user-header h2 {{ font-size: 16px; }}
  .summary-value {{ font-size: 16px; }}
  .nav-bar {{ padding: 6px 8px; }}
  .nav-arrow {{ padding: 8px 10px; font-size: 12px; min-width: 38px; }}
  .page-indicator {{ gap: 4px; font-size: 12px; }}
  .user-header {{ padding: 10px 10px 4px; }}
  .insights-table {{ font-size: 11px; }}
  .insights-table th, .insights-table td {{ padding: 4px; }}
  .priority-bar-label {{ width: 18px; font-size: 10px; }}
  .priority-bar-value {{ width: 36px; font-size: 10px; }}
  .filter-item select {{ font-size: 12px; padding: 7px 8px; }}
  .drilldown-grid {{ grid-template-columns: repeat(2, 1fr); gap: 4px; }}
  .engineer-tag {{ font-size: 11px; padding: 4px 8px; }}
  .task-log-title {{ font-size: 14px; }}
  .task-log-summary {{ font-size: 13px; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="report-header">
        <h1>Team Activity Report - Last {hours} Hours</h1>
        <div class="meta">Generated on {generated_date} | Shift baseline: {shift_hours:.1f}h | Showing team overview + one team member per page</div>
    </div>
    <div class="nav-menu-bar">
        <button class="nav-menu-toggle" onclick="toggleNavMenu()">&#9776; Jump to Engineer</button>
        <div class="nav-menu-dropdown" id="nav-menu-dropdown">{nav_items_html}</div>
    </div>
    {pages_html}
    <div class="keyboard-hint">Use <kbd>&larr;</kbd> <kbd>&rarr;</kbd> or <kbd>&uarr;</kbd> <kbd>&darr;</kbd> keys to navigate</div>
</div>
<script>
var totalPages = {total_pages};
var currentPage = 0;
var projects = {overview_filter_json};

function clearSelect(el, placeholder) {{
    el.innerHTML = '<option value="">' + placeholder + '</option>';
}}
function fillSelect(el, items, labelFn) {{
    for (var i = 0; i < items.length; i++) {{
        var opt = document.createElement('option');
        opt.value = i;
        opt.textContent = labelFn(items[i]);
        el.appendChild(opt);
    }}
}}
function renderTaskDetails(task) {{
    var emptyEl = document.getElementById('task-drilldown-empty');
    var detailsEl = document.getElementById('task-drilldown-details');
    var titleEl = document.getElementById('drill-task-title');
    var priorityEl = document.getElementById('drill-task-priority');
    var statusEl = document.getElementById('drill-task-status');
    var gridEl = document.getElementById('drilldown-grid');
    var summaryEl = document.getElementById('drill-task-summary');
    var descWrapEl = document.getElementById('drill-task-description-wrap');
    var descEl = document.getElementById('drill-task-description');
    if (!task) {{
        emptyEl.style.display = 'block';
        detailsEl.style.display = 'none';
        return;
    }}
    emptyEl.style.display = 'none';
    detailsEl.style.display = 'block';
    titleEl.textContent = task.name;
    priorityEl.textContent = task.priority;
    priorityEl.className = 'priority-tag priority-' + task.priority.toLowerCase();
    statusEl.textContent = task.status;
    gridEl.innerHTML =
        '<div class="drilldown-cell"><div class="drilldown-cell-label">Priority</div><div class="drilldown-cell-value">' + task.priority + '</div></div>' +
        '<div class="drilldown-cell"><div class="drilldown-cell-label">Status</div><div class="drilldown-cell-value">' + task.status + '</div></div>' +
        '<div class="drilldown-cell"><div class="drilldown-cell-label">Age</div><div class="drilldown-cell-value">' + task.age + '</div></div>' +
        '<div class="drilldown-cell"><div class="drilldown-cell-label">Progress</div><div class="drilldown-cell-value">' + task.progress + '%</div></div>' +
        '<div class="drilldown-cell"><div class="drilldown-cell-label">Logged Hours</div><div class="drilldown-cell-value">' + task.logged_hours + 'h</div></div>' +
        '<div class="drilldown-cell"><div class="drilldown-cell-label">Owner</div><div class="drilldown-cell-value">' + task.owner + '</div></div>' +
        '<div class="drilldown-cell"><div class="drilldown-cell-label">Milestone</div><div class="drilldown-cell-value">' + (task.milestone || '-') + (task.milestone_deadline ? ' (' + task.milestone_deadline + ')' : '') + '</div></div>' +
        '<div class="drilldown-cell"><div class="drilldown-cell-label">Deadline</div><div class="drilldown-cell-value">' + (task.deadline || '-') + '</div></div>';
    summaryEl.textContent = task.summary || 'No summary available.';
    if (task.description) {{
        descWrapEl.style.display = 'block';
        descEl.innerHTML = task.description;
    }} else {{
        descWrapEl.style.display = 'none';
    }}
}}
function renderSelectedTask(taskIdx) {{
    if (taskIdx === '') {{ renderTaskDetails(null); return; }}
    var task = currentTaskPool[Number(taskIdx)];
    renderTaskDetails(task);
}}
var currentTaskPool = [];

function populateTasksAndRender() {{
    var projectEl = document.getElementById('filter-project');
    var engineerEl = document.getElementById('filter-engineer');
    var taskEl = document.getElementById('filter-task');
    var projectIdx = projectEl.value;
    var engineerIdx = engineerEl.value;
    if (projectIdx === '' || engineerIdx === '') {{
        clearSelect(taskEl, 'Select Task');
        taskEl.disabled = true;
        currentTaskPool = [];
        renderTaskDetails(null);
        return;
    }}
    var selectedProject = projects[Number(projectIdx)];
    if (!selectedProject) {{ taskEl.disabled = true; currentTaskPool = []; renderTaskDetails(null); return; }}
    var engineers = selectedProject.engineers || [];
    var selectedEngineer;
    if (engineerIdx === 'all') {{
        selectedEngineer = {{ tasks: [] }};
        for (var ei = 0; ei < engineers.length; ei++) {{
            selectedEngineer.tasks = selectedEngineer.tasks.concat(engineers[ei].tasks);
        }}
    }} else {{
        selectedEngineer = engineers[Number(engineerIdx)];
    }}
    if (!selectedEngineer) {{ taskEl.disabled = true; currentTaskPool = []; renderTaskDetails(null); return; }}
    var tasks = selectedEngineer.tasks || [];
    clearSelect(taskEl, 'Select Task');
    fillSelect(taskEl, tasks, function(t) {{ return t.name + ' [' + t.logged_hours + 'h]'; }});
    currentTaskPool = tasks;
    if (tasks.length > 0) {{
        taskEl.disabled = false;
        taskEl.value = 0;
        renderSelectedTask(0);
    }} else {{
        taskEl.disabled = true;
        renderTaskDetails(null);
    }}
}}
function initOverviewFilters() {{
    var projectEl = document.getElementById('filter-project');
    var engineerEl = document.getElementById('filter-engineer');
    var taskEl = document.getElementById('filter-task');
    if (!projectEl || projects.length === 0) return;
    clearSelect(projectEl, 'Select Project');
    fillSelect(projectEl, projects, function(p) {{ return p.name; }});
    projectEl.onchange = function() {{
        clearSelect(engineerEl, 'Select Engineer');
        clearSelect(taskEl, 'Select Task');
        taskEl.disabled = true;
        renderTaskDetails(null);
        var projectIdx = projectEl.value;
        if (projectIdx === '') {{ engineerEl.disabled = true; return; }}
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
    engineerEl.onchange = function() {{ populateTasksAndRender(); }};
    taskEl.onchange = function() {{ renderSelectedTask(taskEl.value); }};
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
    var items = document.querySelectorAll('.nav-menu-item');
    items.forEach(function(item, i) {{
        item.classList.toggle('active', i === idx);
    }});
    if (idx === 0) {{ initOverviewFilters(); }}
    if (window.Plotly && target) {{
        setTimeout(function() {{
            var plots = target.querySelectorAll('.plotly-graph-div');
            plots.forEach(function(plot) {{ try {{ Plotly.Plots.resize(plot); }} catch (e) {{ }} }});
        }}, 50);
    }}
    window.scrollTo({{ top: 0, behavior: 'smooth' }});
}}
function navigate(idx) {{ showPage(idx); }}
function toggleNavMenu() {{
    var menu = document.getElementById('nav-menu-dropdown');
    menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
}}
function closeNavMenu() {{
    document.getElementById('nav-menu-dropdown').style.display = 'none';
}}
document.addEventListener('click', function(e) {{
    var menu = document.getElementById('nav-menu-dropdown');
    var toggle = document.querySelector('.nav-menu-toggle');
    if (menu && toggle && !menu.contains(e.target) && !toggle.contains(e.target)) {{
        menu.style.display = 'none';
    }}
}});
document.addEventListener('keydown', function(e) {{
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {{
        if (currentPage < totalPages - 1) {{ showPage(currentPage + 1); }}
        e.preventDefault();
    }} else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{
        if (currentPage > 0) {{ showPage(currentPage - 1); }}
        e.preventDefault();
    }}
}});
if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', function() {{ showPage(0); }});
}} else {{
    showPage(0);
}}
</script>
</body>
</html>"""


def generate_project_html_report(projects_list, generated_date, hours, shift_hours, extra_charts=None):
    """
    Generate a project-focused HTML report with per-project pages.
    projects_list: [{'name', 'total_hours', 'engineers': [{'name','hours'}], 'tasks': [{...}], 'priority_hours': {'P1':..}}]
    """
    total_projects = len(projects_list)
    total_pages = total_projects + 1
    total_hours = sum(p['total_hours'] for p in projects_list)
    total_engineers = len(set(e['name'] for p in projects_list for e in p['engineers']))
    total_tasks = sum(len(p['tasks']) for p in projects_list)

    if not projects_list:
        return "<html><body><h2>No project data available</h2></body></html>"

    project_cards_html = ""
    for i, proj in enumerate(projects_list):
        proj_hours = proj['total_hours']
        eng_count = len(proj['engineers'])
        task_count = len(proj['tasks'])
        p1 = proj['priority_hours'].get('P1', 0)
        p2 = proj['priority_hours'].get('P2', 0)
        p3 = proj['priority_hours'].get('P3', 0)
        max_p = max(p1, p2, p3, 1)
        project_cards_html += f"""
            <div class="project-summary-card" onclick="showPage({i+1})" style="cursor:pointer;">
                <div class="project-summary-head">
                    <span class="project-summary-name">{html_mod.escape(proj['name'])}</span>
                    <span class="project-summary-hours">{proj_hours:.1f}h</span>
                </div>
                <div style="font-size:12px;color:#64748b;margin-top:6px;">{eng_count} engineer(s) | {task_count} task(s)</div>
                <div class="priority-bars" style="margin-top:10px;">
                    <div class="priority-bar-row"><span class="priority-bar-label">P1</span><div class="priority-bar-track"><div class="priority-bar-fill priority-p1" style="width:{p1/max_p*100:.1f}%"></div></div><span class="priority-bar-value">{p1:.1f}h</span></div>
                    <div class="priority-bar-row"><span class="priority-bar-label">P2</span><div class="priority-bar-track"><div class="priority-bar-fill priority-p2" style="width:{p2/max_p*100:.1f}%"></div></div><span class="priority-bar-value">{p2:.1f}h</span></div>
                    <div class="priority-bar-row"><span class="priority-bar-label">P3</span><div class="priority-bar-track"><div class="priority-bar-fill priority-p3" style="width:{p3/max_p*100:.1f}%"></div></div><span class="priority-bar-value">{p3:.1f}h</span></div>
                </div>
            </div>"""

    extra_charts_html = ""
    if extra_charts:
        if extra_charts.get('bubble_html'):
            extra_charts_html += f"""<div class="project-section"><div class="project-title"><span>Projects Bubble Chart</span></div><div style="overflow-x:auto;">{extra_charts['bubble_html']}</div></div>"""
        if extra_charts.get('heatmap_html'):
            extra_charts_html += f"""<div class="project-section"><div class="project-title"><span>Project Criticality Heatmap</span></div><div style="overflow-x:auto;">{extra_charts['heatmap_html']}</div></div>"""
        if extra_charts.get('gantt_html'):
            extra_charts_html += f"""<div class="project-section"><div class="project-title"><span>Projects & Tasks Timeline</span></div><div style="overflow-x:auto;">{extra_charts['gantt_html']}</div></div>"""

    overview_html = f"""
    <div class="user-page status-overview" id="page-0" data-index="0">
        <div class="nav-bar">
            <div><span class="nav-arrow" onclick="navigate(0)" style="visibility:hidden">&#9664; Previous</span></div>
            <div class="page-indicator"><span class="status-indicator status-active">&#9679;</span><span class="user-name-nav">Projects Overview</span><span class="page-count">1 / {total_pages}</span></div>
            <div><span class="nav-arrow" onclick="navigate(1)">Next &#9654;</span></div>
        </div>
        <div class="user-header">
            <div class="user-header-left">
                <h2>Projects Overview</h2>
                <div class="user-meta"><span class="hours-badge">Shift baseline {shift_hours:.1f}h</span></div>
            </div>
        </div>
        <div class="summary-grid overview-grid">
            <div class="summary-card"><div class="summary-label">Total Projects</div><div class="summary-value">{total_projects}</div></div>
            <div class="summary-card"><div class="summary-label">Total Hours</div><div class="summary-value">{total_hours:.1f}h</div></div>
            <div class="summary-card"><div class="summary-label">Engineers</div><div class="summary-value">{total_engineers}</div></div>
            <div class="summary-card"><div class="summary-label">Total Tasks</div><div class="summary-value">{total_tasks}</div></div>
            <div class="summary-card"><div class="summary-label">Hours Window</div><div class="summary-value">{hours}h</div></div>
        </div>
        <div class="project-section"><div class="project-title"><span>All Projects — Click a card to view details</span></div><div class="project-summary-grid">{project_cards_html}</div></div>
        {extra_charts_html}
    </div>"""

    project_pages_html = ""
    nav_items_html = """<div class="nav-menu-item active" data-page="0" onclick="showPage(0); closeNavMenu();">Projects Overview</div>"""

    for idx, proj in enumerate(projects_list, start=1):
        page_id = f"page-{idx}"
        task_panels_html = ""
        for task in proj['tasks']:
            priority_label = get_priority_label(task.get('priority', '0'))
            priority_class = f"priority-{priority_label.lower()}"
            engineers_list = task.get('engineers', [])
            eng_names = ", ".join(html_mod.escape(e) for e in engineers_list)
            desc = task.get('description', '') or ''
            llm_summary = task.get('llm_summary', '') or ''
            if isinstance(llm_summary, dict):
                llm_summary = llm_summary.get('summary', '') or ''
            create_date = task.get('create_date', '') or ''
            deadline = task.get('date_deadline', '') or ''
            owner = html_mod.escape(task.get('task_owner', '-'))
            stage = html_mod.escape(task.get('stage', 'Unknown'))
            task_name = html_mod.escape(task.get('name', 'Untitled'))
            task_hours = task.get('hours', 0)
            task_progress = task.get('progress', 0)

            badges = f"""<span class="ip-badge ip-badge-{priority_label.lower()}">{priority_label}</span><span class="ip-badge ip-badge-stage">{stage}</span><span class="ip-badge ip-badge-hours">{task_hours:.1f}h</span><span class="ip-badge ip-badge-progress">{task_progress:.0f}%</span><span class="ip-badge ip-badge-engineer">{eng_names}</span>"""
            if create_date:
                badges += f"""<span class="ip-badge ip-badge-date">Opened: {create_date}</span>"""
            if deadline:
                badges += f"""<span class="ip-badge ip-badge-date">Due: {deadline}</span>"""
            if owner:
                badges += f"""<span class="ip-badge ip-badge-owner">Owner: {owner}</span>"""

            desc_html = ""
            if desc:
                desc_html = f"""<div class="ip-section"><div class="ip-section-label">Description</div><div class="ip-section-body ip-desc-body">{format_log_notes(desc)}</div></div>"""

            summary_html = ""
            if llm_summary:
                summary_html = f"""<div class="ip-section"><div class="ip-section-label">Analysis &amp; Log Summary</div><div class="ip-section-body ip-summary-body">{html_mod.escape(llm_summary)}</div></div>"""

            task_panels_html += f"""
            <div class="task-panel">
                <div class="task-panel-header">
                    <span class="task-panel-title">{task_name}</span>
                    <span class="priority-tag {priority_class}">{priority_label}</span>
                </div>
                <div class="task-panel-body">
                    <div class="ip-badges-row">{badges}</div>
                    {desc_html}
                    {summary_html}
                </div>
            </div>"""

        if not task_panels_html:
            task_panels_html = '<div class="no-tasks">No task data</div>'

        project_pages_html += f"""
        <div class="user-page status-active" id="{page_id}" data-index="{idx}">
            <div class="nav-bar">
                <div><span class="nav-arrow" onclick="navigate({idx-1})">&#9664; Previous</span></div>
                <div class="page-indicator"><span class="status-indicator status-active">&#9679;</span><span class="user-name-nav">{html_mod.escape(proj['name'])}</span><span class="page-count">{idx+1} / {total_pages}</span></div>
                <div><span class="nav-arrow" onclick="navigate({idx+1})" {'style="visibility:hidden"' if idx == total_projects else ''}>Next &#9654;</span></div>
            </div>
            <div class="user-header">
                <div class="user-header-left">
                    <h2>{html_mod.escape(proj['name'])}</h2>
                    <div class="user-meta">
                        <span class="hours-badge">{proj['total_hours']:.1f}h total</span>
                        <span class="hours-badge">{len(proj['engineers'])} engineer(s)</span>
                        <span class="hours-badge">{len(proj['tasks'])} task(s)</span>
                    </div>
                </div>
            </div>
            {task_panels_html}
        </div>"""

        nav_items_html += f"""<div class="nav-menu-item" data-page="{idx}" onclick="showPage({idx}); closeNavMenu();">{html_mod.escape(proj['name'])}</div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
<title>Project Report - Last {hours}h</title>
<style>
* {{ box-sizing: border-box; }}
:root {{ --bg: #f3f6fa; --card: #ffffff; --text: #1f2937; --muted: #6b7280; --brand: #0b7285; --brand-soft: #e6fcf5; --danger: #c92a2a; --ok: #2b8a3e; --line: #dbe4ef; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 0; background: radial-gradient(circle at top right, #e3fafc 0%, var(--bg) 35%, #edf2f7 100%); color: var(--text); }}
.container {{ width: 100%; max-width: none; margin: 0; padding: 18px 18px 24px; }}
h1 {{ color: #0f172a; font-size: 28px; margin-bottom: 6px; letter-spacing: 0.2px; }}
.meta {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
.report-header {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; margin-bottom: 18px; box-shadow: 0 8px 20px rgba(15,23,42,0.04); }}
.nav-menu-bar {{ margin-bottom: 18px; position: relative; }}
.nav-menu-toggle {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 10px 18px; font-size: 14px; font-weight: 600; color: #0b7285; cursor: pointer; transition: all 0.2s; }}
.nav-menu-toggle:hover {{ background: #e6fcf5; border-color: #0b7285; }}
.nav-menu-dropdown {{ display: none; position: absolute; top: 100%; left: 0; z-index: 200; background: white; border: 1px solid #dee2e6; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); max-height: 400px; overflow-y: auto; min-width: 220px; margin-top: 4px; }}
.nav-menu-item {{ padding: 10px 16px; cursor: pointer; font-size: 13px; color: #1f2937; border-bottom: 1px solid #f1f3f5; transition: background 0.15s; }}
.nav-menu-item:last-child {{ border-bottom: none; }}
.nav-menu-item:hover {{ background: #e6fcf5; color: #0b7285; }}
.nav-menu-item.active {{ background: #0b7285; color: white; font-weight: 600; }}
.nav-bar {{ display: flex; justify-content: space-between; align-items: center; background: white; padding: 12px 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; position: sticky; top: 10px; z-index: 100; }}
.nav-arrow {{ cursor: pointer; padding: 8px 18px; border-radius: 6px; font-size: 14px; font-weight: 600; color: #495057; background: #f8f9fa; border: 1px solid #dee2e6; transition: all 0.2s; user-select: none; }}
.nav-arrow:hover {{ background: #4a90d9; color: white; border-color: #4a90d9; }}
.page-indicator {{ display: flex; align-items: center; gap: 10px; font-size: 14px; color: #495057; }}
.status-indicator {{ font-size: 10px; }}
.status-indicator.status-active {{ color: #28a745; }}
.status-indicator.status-no-update {{ color: #dc3545; }}
.user-name-nav {{ font-weight: 600; font-size: 15px; }}
.page-count {{ color: #868e96; font-size: 13px; background: #f8f9fa; padding: 3px 10px; border-radius: 12px; }}
.user-page {{ background: white; border-radius: 12px; box-shadow: 0 8px 22px rgba(15,23,42,0.06); overflow: hidden; }}
.user-page.status-no-update {{ border: 2px solid #dc3545; }}
.user-page.status-active {{ border: 2px solid #28a745; }}
.user-page.status-overview {{ border: 2px solid #1864ab; }}
.user-page:not(.active) {{ display: none; }}
.user-header {{ padding: 20px 20px 8px; display: flex; justify-content: space-between; align-items: flex-start; }}
.user-header h2 {{ margin: 0; color: #2c3e50; font-size: 22px; }}
.user-header-left {{ display: flex; flex-direction: column; gap: 8px; }}
.user-meta {{ display: flex; align-items: center; gap: 10px; }}
.hours-badge {{ background: #e7f5ff; color: #1864ab; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
.summary-grid {{ display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; padding: 0 20px 14px; }}
.summary-card {{ background: #f8fbff; border: 1px solid #e1ecf5; border-radius: 10px; padding: 10px; }}
.summary-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 5px; font-weight: 600; }}
.summary-value {{ font-size: 20px; font-weight: 700; color: #0f172a; }}
.project-section {{ margin: 15px 15px 18px; padding: 15px; background: #f8fafc; border-radius: 10px; border-left: 4px solid #1971c2; border: 1px solid #e1e8f0; }}
.project-title {{ font-size: 16px; font-weight: 600; color: #2c3e50; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }}
.project-summary-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }}
.project-summary-card {{ border: 1px solid #dbe7f3; background: #fcfdff; border-radius: 10px; padding: 12px; min-width: 0; transition: box-shadow 0.2s, transform 0.15s; }}
.project-summary-card:hover {{ box-shadow: 0 4px 12px rgba(11,114,133,0.15); transform: translateY(-1px); }}
.project-summary-head {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px; }}
.project-summary-name {{ font-size: 14px; font-weight: 700; color: #1f2937; line-height: 1.3; }}
.project-summary-hours {{ font-size: 11px; font-weight: 700; color: #0b7285; background: #e6fcf5; border-radius: 999px; padding: 3px 8px; white-space: nowrap; }}
.priority-bars {{ display: flex; flex-direction: column; gap: 4px; }}
.priority-bar-row {{ display: flex; align-items: center; gap: 6px; font-size: 11px; }}
.priority-bar-label {{ width: 22px; font-weight: 700; color: #475569; }}
.priority-bar-track {{ flex: 1; height: 6px; background: #e9ecef; border-radius: 3px; overflow: hidden; }}
.priority-bar-fill {{ height: 100%; border-radius: 3px; min-width: 2px; }}
.priority-bar-fill.priority-p1 {{ background: #c92a2a; }}
.priority-bar-fill.priority-p2 {{ background: #f08c00; }}
.priority-bar-fill.priority-p3 {{ background: #2b8a3e; }}
.priority-bar-value {{ width: 48px; text-align: right; font-weight: 600; color: #495057; }}
.priority-tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }}
.priority-p1 {{ background: #ffe3e3; color: #c92a2a; }}
.priority-p2 {{ background: #fff3bf; color: #f08c00; }}
.priority-p3 {{ background: #e6fcf5; color: #2b8a3e; }}
.keyboard-hint {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 10px; }}
.overview-grid {{ grid-template-columns: repeat(5, minmax(110px, 1fr)); }}
.no-tasks {{ text-align: center; padding: 20px; color: #94a3b8; }}
.task-panel {{ background: white; border: 1px solid #dbe4ef; border-radius: 8px; margin: 8px 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); overflow: hidden; }}
.task-panel-header {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: #f8fafc; border-bottom: 1px solid #eef2f6; }}
.task-panel-title {{ font-size: 14px; font-weight: 700; color: #0f172a; line-height: 1.3; }}
.task-panel-body {{ padding: 6px 12px 10px; }}
.ip-badges-row {{ display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }}
.ip-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; line-height: 1.5; }}
.ip-badge-p1 {{ background: #ffe3e3; color: #c92a2a; }}
.ip-badge-p2 {{ background: #fff3bf; color: #f08c00; }}
.ip-badge-p3 {{ background: #e6fcf5; color: #2b8a3e; }}
.ip-badge-stage {{ background: #e8f4f8; color: #0b7285; }}
.ip-badge-hours {{ background: #e7f5ff; color: #1864ab; }}
.ip-badge-progress {{ background: #f3f0ff; color: #5f3dc4; }}
.ip-badge-engineer {{ background: #f8f9fa; color: #495057; }}
.ip-badge-date {{ background: #fff4e6; color: #d9480f; }}
.ip-badge-owner {{ background: #f1f3f5; color: #343a40; }}
.ip-section {{ margin-top: 6px; padding: 6px 8px; background: #fafbfc; border-radius: 6px; border-left: 3px solid #1971c2; }}
.ip-section-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px; color: #475569; font-weight: 700; margin-bottom: 3px; }}
.ip-section-body {{ font-size: 13px; color: #334155; line-height: 1.5; word-break: break-word; }}
.ip-desc-body a {{ color: #0b7285; }}
.ip-desc-body a:hover {{ text-decoration: underline; }}
.ip-summary-body {{ white-space: pre-wrap; }}
@media (max-width: 768px) {{
  .container {{ padding: 10px; }}
  .report-header {{ padding: 12px; }}
  h1 {{ font-size: 20px; }}
  .nav-bar {{ padding: 8px 12px; flex-wrap: wrap; gap: 6px; }}
  .nav-arrow {{ padding: 10px 14px; font-size: 13px; min-width: 44px; text-align: center; }}
  .summary-grid {{ grid-template-columns: repeat(2, 1fr); gap: 6px; padding: 0 10px 8px; }}
  .overview-grid {{ grid-template-columns: repeat(3, 1fr); }}
  .project-summary-grid {{ grid-template-columns: repeat(2, 1fr); gap: 8px; }}
  .project-summary-card {{ padding: 10px; }}
  .user-header {{ padding: 14px 14px 6px; }}
  .user-header h2 {{ font-size: 18px; }}
  .nav-menu-toggle {{ padding: 8px 14px; font-size: 13px; }}
  .nav-menu-item {{ padding: 12px 16px; }}
  .page-count {{ font-size: 11px; }}
  .user-name-nav {{ font-size: 13px; }}
  .task-panel {{ margin: 6px 8px; }}
  .task-panel-header {{ padding: 6px 10px; }}
  .task-panel-title {{ font-size: 13px; }}
  .task-panel-body {{ padding: 4px 10px 8px; }}
  .ip-section {{ padding: 4px 6px; }}
  .ip-section-body {{ font-size: 12px; }}
}}
@media (max-width: 480px) {{
  .container {{ padding: 6px; }}
  h1 {{ font-size: 17px; }}
  .report-header {{ padding: 10px; }}
  .summary-grid {{ grid-template-columns: 1fr 1fr; gap: 4px; padding: 0 6px 6px; }}
  .overview-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .project-summary-grid {{ grid-template-columns: 1fr; }}
  .user-header h2 {{ font-size: 16px; }}
  .summary-value {{ font-size: 16px; }}
  .nav-bar {{ padding: 6px 8px; }}
  .nav-arrow {{ padding: 8px 10px; font-size: 12px; min-width: 38px; }}
  .page-indicator {{ gap: 4px; font-size: 12px; }}
  .user-header {{ padding: 10px 10px 4px; }}
  .task-panel {{ margin: 4px 6px; }}
  .task-panel-title {{ font-size: 12px; }}
  .ip-badge {{ font-size: 10px; padding: 1px 6px; }}
  .ip-section-body {{ font-size: 11px; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="report-header">
        <h1>Project Report - Last {hours} Hours</h1>
        <div class="meta">Generated on {generated_date} | Shift baseline: {shift_hours:.1f}h | Project-focused view with per-project details and engineer attribution</div>
    </div>
    <div class="nav-menu-bar">
        <button class="nav-menu-toggle" onclick="toggleNavMenu()">&#9776; Jump to Project</button>
        <div class="nav-menu-dropdown" id="nav-menu-dropdown">{nav_items_html}</div>
    </div>
    {overview_html}
    {project_pages_html}
    <div class="keyboard-hint">Use <kbd>&larr;</kbd> <kbd>&rarr;</kbd> or <kbd>&uarr;</kbd> <kbd>&darr;</kbd> keys to navigate</div>
</div>
<script>
var totalPages = {total_pages};
var currentPage = 0;

function showPage(idx) {{
    if (idx < 0 || idx >= totalPages) return;
    currentPage = idx;
    for (var i = 0; i < totalPages; i++) {{
        var el = document.getElementById('page-' + i);
        if (el) el.classList.remove('active');
    }}
    var target = document.getElementById('page-' + idx);
    if (target) target.classList.add('active');
    var items = document.querySelectorAll('.nav-menu-item');
    items.forEach(function(item, i) {{
        item.classList.toggle('active', i === idx);
    }});
    window.scrollTo({{ top: 0, behavior: 'smooth' }});
}}
function navigate(idx) {{ showPage(idx); }}
function toggleNavMenu() {{
    var menu = document.getElementById('nav-menu-dropdown');
    menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
}}
function closeNavMenu() {{
    document.getElementById('nav-menu-dropdown').style.display = 'none';
}}
document.addEventListener('click', function(e) {{
    var menu = document.getElementById('nav-menu-dropdown');
    var toggle = document.querySelector('.nav-menu-toggle');
    if (menu && toggle && !menu.contains(e.target) && !toggle.contains(e.target)) {{
        menu.style.display = 'none';
    }}
}});
document.addEventListener('keydown', function(e) {{
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {{
        if (currentPage < totalPages - 1) {{ showPage(currentPage + 1); }}
        e.preventDefault();
    }} else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {{
        if (currentPage > 0) {{ showPage(currentPage - 1); }}
        e.preventDefault();
    }}
}});
if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', function() {{ showPage(0); }});
}} else {{
    showPage(0);
}}
</script>
</body>
</html>"""
