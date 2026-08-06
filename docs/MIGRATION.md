# Migration Guide: Standalone Script → Hosted Application

## Overview

Your original `team_activity_paginated_report.py` was a standalone script that:
- Connected to Odoo directly via XML-RPC
- Generated HTML reports
- Sent emails with reports
- Used LLM for task summarization

The new hosted application:
- Maintains all original functionality
- Adds persistent data storage (PostgreSQL)
- Provides REST API for programmatic access
- Enables historical trend analysis
- Offers web-based UI for report browsing
- Allows report caching and archival

## What's Been Preserved

### 1. Odoo Integration
```python
# OLD: Direct connection in main()
uid, models = connect_odoo()

# NEW: Wrapped in service
odoo_service = OdooService()
uid, models = odoo_service.connect()
```

### 2. LLM Summarization
```python
# OLD: Direct API call in summarize_with_llm()
payload = {"model": LLM_MODEL, "messages": [...]}
resp = requests.post(LLM_API_URL, ...)

# NEW: Same logic in services.OdooService.summarize_with_llm()
# Plus caching in task_summaries table
```

### 3. Report Generation
```python
# OLD: Generated HTML on demand, sent via email
html_report = generate_html_report(...)
send_email(html_report, ...)

# NEW: Generated HTML stored in reports table
# Available via API, downloadable, can be emailed
```

### 4. Visualizations
```python
# OLD: Plotly charts generated in Python
fig = ff.create_gantt(gantt_rows, ...)

# NEW: Same visualization logic, now also available via API
# Frontend can render charts using Plotly React
```

## Database Schema Mapping

| Old Concept | New Storage | Benefits |
|-------------|-------------|----------|
| Timesheets in memory | `timesheets` table | Permanent history, queryable |
| Tasks in memory | `tasks` table | Task tracking, analytics |
| Users in memory | `users` table | Team roster, historical |
| One-off HTML report | `reports` table | Archival, comparison |
| Task summaries generated each time | `task_summaries` table | Cached, fast retrieval |
| - | `report_analytics` table | Daily metrics, trends |

## API Equivalents

### Original: Standalone Report Generation
```bash
python team_activity_paginated_report.py --hours 24
# Output: team_activity_paginated_report_24h.html
# Email: sent to REPORT_RECIPIENTS
```

### New: API-Based Report Generation
```bash
# 1. Create report job
curl -X POST http://localhost:5000/api/reports \
  -H "Content-Type: application/json" \
  -d '{"report_type": "team", "hours_window": 24}'

# 2. Poll for completion status
curl http://localhost:5000/api/reports/<report_id>

# 3. Download HTML
curl http://localhost:5000/api/reports/<report_id>/html > report.html

# 4. Or get JSON data
curl http://localhost:5000/api/reports/<report_id>?include_html=true
```

## Migration Path

### Phase 1: Side-by-Side (Week 1-2)

Keep original script running while testing new app:

```bash
# Terminal 1: Run new hosted app
docker-compose up

# Terminal 2: Continue running original script
python team_activity_paginated_report.py --hours 24

# Both generate reports independently
# Original: HTML file + email
# New: Database + API + UI
```

### Phase 2: Parallel Sync (Week 3-4)

Modify original script to also sync to new database:

```python
# In team_activity_paginated_report.py, after generating HTML:

import requests
import json

# Store in new system
payload = {
    'report_type': 'team',
    'hours_window': 24,
    'title': f'Team Report - {datetime.now().strftime("%Y-%m-%d %H:%M")}',
}
response = requests.post('http://localhost:5000/api/reports', json=payload)
report_id = response.json()['data']['id']

# Also store HTML and JSON
cache_payload = {
    'html_content': html_report,
    'json_data': {
        'users': [u.to_dict() for u in user_tasks_data.values()],
        'analytics': team_summary,
    }
}
# (Would need new endpoint for this)
```

### Phase 3: Full Migration (Week 5)

Switch to new hosted app exclusively:

```bash
# Archive old script
mkdir -p archive/2024-01
mv team_activity_paginated_report.py archive/2024-01/
mv team_activity_paginated_report_*.html archive/2024-01/

# All reports now via API
# Scheduled jobs use API instead of script
# Email notifications configured in new app
```

## Configuration Migration

### Old: config.yaml
```yaml
odoo:
  url: "https://hrms.opensource-db.com"
  db: "openhrms18"
  user: "sivasankar@opensource-db.com"
  password: "Perot@123"

llm:
  api_url: "https://inference.do-ai.run/v1/chat/completions"
  model: "openai-gpt-oss-120b"
  api_key: "sk-do-..."
```

### New: backend/.env + backend/services.py
```python
# Load same config.yaml for Odoo/LLM settings
class OdooService:
    def __init__(self, config_path='config.yaml'):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        self.odoo_url = config['odoo']['url']
        # ... same as before
```

## Functional Mapping

### Report Types

```python
# Generate reports via API
POST /api/reports
{
  "report_type": "team",      # Was: always team
  "hours_window": 24          # Was: --hours parameter
}

# Personal report
{
  "report_type": "personal",
  "user_id": "user_123",
  "hours_window": 24
}

# Project report
{
  "report_type": "project",
  "project_id": "proj_456",
  "hours_window": 24
}
```

### Historical Analysis

```python
# OLD: Not possible - each report was one-off

# NEW: Query historical data
GET /api/analytics/user/user_123/summary?days=30
# Returns: [
#   {"date": "2024-01-15", "total_hours": 7.5, "utilization": 90.4, ...},
#   {"date": "2024-01-14", "total_hours": 8.3, "utilization": 100, ...},
#   ...
# ]

GET /api/analytics/trends?metric=total_hours&days=90
# Returns: Trend data and percentage change
```

## Testing the Migration

### 1. Verify Data Integrity
```bash
# Compare old vs new output
curl http://localhost:5000/api/users | jq '.count'
# Should match number of users in original script

curl http://localhost:5000/api/analytics/team/summary | jq '.data'
# Should show reasonable metrics
```

### 2. Verify Report Generation
```bash
# Generate test report
REPORT_ID=$(curl -X POST http://localhost:5000/api/reports \
  -H "Content-Type: application/json" \
  -d '{"report_type": "team", "hours_window": 24}' | jq -r '.data.id')

# Wait a moment
sleep 5

# Get report
curl http://localhost:5000/api/reports/$REPORT_ID
```

### 3. Verify LLM Integration
```bash
# Check if task summaries are being generated
curl http://localhost:5000/api/reports | jq '.data[0].json_data'
# Should see task_summaries with LLM content
```

## Scheduled Execution

### Old: Cron Job
```bash
0 8 * * * cd /home/user/odoo/hostedapp && python team_activity_paginated_report.py --hours 24
```

### New: API Endpoint Call
```bash
# Option 1: Curl from cron
0 8 * * * curl -X POST http://localhost:5000/api/reports \
  -H "Content-Type: application/json" \
  -d '{"report_type": "team", "hours_window": 24}'

# Option 2: Python script using requests
0 8 * * * python /home/user/scripts/generate_daily_report.py
```

### New: generate_daily_report.py
```python
import requests
import os

api_url = os.getenv('API_URL', 'http://localhost:5000/api')

response = requests.post(f'{api_url}/reports', json={
    'report_type': 'team',
    'hours_window': 24,
    'title': 'Daily Team Report'
})

if response.status_code == 201:
    print(f"Report created: {response.json()['data']['id']}")
else:
    print(f"Error: {response.status_code}")
    print(response.text)
```

## Emails & Notifications

### Old: Direct Sendmail
```python
send_email(html_content, recipients, hours)
```

### New: API + Email Service (To Be Implemented)
```python
# In services.py (future enhancement)
class EmailService:
    @staticmethod
    def send_report(report_id, recipients):
        report = Report.query.get(report_id)
        # Send email with link to report
        # Or attach HTML if file size allows
```

## Rollback Plan

If needed to return to original script:

```bash
# 1. Stop new app
docker-compose down

# 2. Verify old script still works
python team_activity_paginated_report.py --hours 24

# 3. Restore old cron job
crontab -e
# 0 8 * * * cd /home/user/odoo/hostedapp && python team_activity_paginated_report.py --hours 24

# 4. Archive new app
mkdir -p archive/hosted_app_2024-01
cp -r backend frontend database docs *.yml *.md archive/hosted_app_2024-01/
```

## Recommended Transition Timeline

| Week | Action | Status |
|------|--------|--------|
| 1 | Deploy hosted app alongside original | Testing |
| 2 | Verify data sync and report generation | Validation |
| 3 | Start using hosted app for key reports | Parallel |
| 4 | Migrate team to use new UI | Adoption |
| 5 | Archive original script | Complete |

## Support Transition

### For End Users
- Old way: Check email for HTML report
- New way: Log into web app, browse reports

### For Admins
- Old way: Check cron logs for failures
- Old way: SSH to server to run manual reports

- New way: Check `/api/health` endpoint
- New way: Call API from anywhere
- New way: View reports in UI with full history

## Key Advantages of New System

1. **Persistence**: All historical data retained
2. **Accessibility**: Web UI + REST API
3. **Scalability**: Can handle multiple concurrent users
4. **Flexibility**: Generate reports on-demand or scheduled
5. **Analysis**: Historical trends and comparisons
6. **Reliability**: Database transactions ensure data consistency
7. **Integration**: API allows integration with other tools
