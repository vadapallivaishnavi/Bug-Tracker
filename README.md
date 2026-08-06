# Team Activity Report - Hosted Application

A production-ready web application for generating, storing, and analyzing team activity reports from Odoo with historical data insights.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                         │
│  Dashboard | Reports | Analytics | Team Overview | Settings    │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP/REST API
┌────────────────────────▼────────────────────────────────────────┐
│                     Backend (Flask/SQLAlchemy)                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ API Routes: Reports, Analytics, Users, Projects         │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ Services: OdooService, ReportGeneration, Analytics      │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ Database ORM (SQLAlchemy) & Migrations (Alembic)        │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │ PostgreSQL Driver
┌────────────────────────▼────────────────────────────────────────┐
│               PostgreSQL Database (persistent storage)          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Users | Projects | Tasks | Timesheets | Reports         │  │
│  │ TaskSummaries | ReportAnalytics | Historical Data       │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                         │ XML-RPC
┌────────────────────────▼────────────────────────────────────────┐
│              Odoo (External Data Source)                        │
│  Users | Projects | Tasks | Timesheets | Activity Logs         │
└─────────────────────────────────────────────────────────────────┘
```

## Features

### Report Generation
- **Team Reports**: Comprehensive team activity overview with utilization metrics
- **Personal Reports**: Individual team member activity summaries
- **Project Reports**: Project-specific insights and progress tracking
- **Historical Caching**: Reports stored for historical analysis and comparison

### Analytics & Historical Analysis
- **Daily Metrics**: Track hours logged, project count, task distribution
- **Priority Analysis**: P1/P2/P3 effort distribution over time
- **Utilization Trends**: Monitor team productivity patterns
- **Comparative Analysis**: Compare metrics across different time periods
- **Custom Queries**: 90-day trends, team summaries, user analytics

### Data Management
- **Odoo Integration**: Automatic data sync from Odoo (users, projects, tasks, timesheets)
- **LLM Summaries**: AI-powered task summarization using Digital Ocean's LLM API
- **Report Caching**: HTML snapshots and JSON data for historical retrieval
- **Full Audit Trail**: All reports timestamped and archived

### User Interface
- **Responsive Dashboard**: Real-time metrics and quick actions
- **Report Gallery**: Browse, filter, and manage all generated reports
- **Interactive Charts**: Plotly-powered visualizations
- **Team Overview**: Member performance and workload distribution
- **Search & Filter**: Find reports by type, date, and team member

## Quick Start

### Prerequisites
- Docker & Docker Compose
- PostgreSQL 16+ (or use Docker)
- Python 3.11+ (for development)
- Node.js 18+ (for frontend development)

### Installation

1. **Clone and Setup**
```bash
cd /Users/sivasankar/projects/odoo/hostedapp
cp backend/.env.example backend/.env
cp config.yaml config.yaml  # Already exists
```

2. **Configure Environment**
Edit `backend/.env`:
```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/team_activity_db
JWT_SECRET_KEY=your-secure-random-key-here
ODOO_URL=https://hrms.opensource-db.com
ODOO_DB=openhrms18
ODOO_USER=your_email@example.com
ODOO_PASSWORD=your_password
LLM_API_KEY=your_api_key
```

3. **Start Application**
```bash
# Using Docker Compose (recommended)
docker-compose up -d

# Or run locally for development
cd backend && python app.py  # Terminal 1
cd frontend && npm start     # Terminal 2
```

4. **Access Application**
- Frontend: http://localhost:3000
- Backend API: http://localhost:5000/api
- Database: localhost:5432

## API Endpoints

### Reports
```
POST   /api/reports                    - Create new report
GET    /api/reports                    - List all reports (paginated)
GET    /api/reports/<id>               - Get specific report
GET    /api/reports/<id>/html          - Download report as HTML
DELETE /api/reports/<id>/delete        - Archive report
```

### Analytics
```
GET    /api/analytics/user/<id>/summary    - User analytics
GET    /api/analytics/team/summary         - Team aggregated analytics
GET    /api/analytics/trends               - Historical trends (90-day)
```

### Master Data
```
GET    /api/users                      - List team members
GET    /api/users/<id>                 - Get user details
GET    /api/projects                   - List all projects
```

### System
```
GET    /api/health                     - Health check & DB status
```

## Database Schema

### Core Tables
- **users**: Team members with Odoo sync
- **projects**: Projects from Odoo
- **tasks**: Project tasks with priority/stage
- **timesheets**: Logged hours entries

### Report Tables
- **reports**: Generated reports (HTML + JSON cache)
- **task_summaries**: LLM-generated task summaries
- **report_analytics**: Pre-computed metrics for trends

### Indexes
Optimized for:
- User lookups by email/Odoo ID
- Task filtering by project
- Timesheet queries by date range
- Report searches by type/date

## Deployment

### Production Docker Compose
```bash
export JWT_SECRET_KEY=$(openssl rand -hex 32)
docker-compose -f docker-compose.yml up -d
```

### Environment Variables Required
```
DATABASE_URL              # PostgreSQL connection string
JWT_SECRET_KEY            # For API authentication
ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD  # Odoo credentials
LLM_API_URL, LLM_API_KEY  # LLM service credentials
```

### Health Check
```bash
curl http://localhost:5000/api/health
```

### Logs
```bash
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f postgres
```

## Development

### Backend Development
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export FLASK_ENV=development
flask run
```

### Frontend Development
```bash
cd frontend
npm install
npm start  # Runs on http://localhost:3000
```

### Database Migrations
```bash
cd backend
flask db init      # First time only
flask db migrate -m "Description"
flask db upgrade
```

## Data Sync Strategy

### Initial Sync
1. Start application
2. Backend automatically syncs users, projects, tasks from Odoo
3. Historical timesheets loaded for analysis

### Continuous Sync
- Triggered via API or scheduled job
- Incremental updates for efficiency
- New reports automatically generate daily analytics

### Historical Data
- Timesheet entries stored permanently
- Daily analytics pre-computed for fast retrieval
- Reports archived with snapshots

## Performance Optimization

### Caching
- Report HTML cached in database
- Task summaries cached to avoid re-LLM calls
- Daily analytics pre-computed at end of day

### Indexes
- Date-based queries: `report_analytics(date)`
- User-specific: `report_analytics(user_id, date)`
- Report lookups: `reports(report_type, generated_at)`

### Pagination
- Reports: 12-20 per page
- Analytics: Configurable time windows
- API responses: Always paginated

## Troubleshooting

### Database Connection Issues
```bash
docker-compose logs postgres
# Or test directly:
psql postgresql://postgres:postgres@localhost:5432/team_activity_db
```

### Backend API Errors
```bash
docker-compose logs backend
# Check /api/health endpoint
curl http://localhost:5000/api/health
```

### Odoo Sync Failures
- Check `ODOO_URL`, `ODOO_USER`, `ODOO_PASS` in backend/.env
- Verify Odoo server is reachable
- Check firewall rules

### LLM Summary Issues
- Verify `LLM_API_KEY` is valid
- Check API rate limits
- Fall back to task description if LLM fails

## File Structure
```
hostedapp/
├── backend/
│   ├── app.py                  # Flask app factory
│   ├── models.py               # SQLAlchemy models
│   ├── services.py             # Business logic
│   ├── api/
│   │   └── routes.py           # API endpoints
│   ├── requirements.txt         # Python dependencies
│   ├── Dockerfile              # Backend container
│   └── .env.example            # Environment template
├── frontend/
│   ├── src/
│   │   ├── App.js              # React app
│   │   ├── pages/              # Page components
│   │   ├── components/         # Reusable components
│   │   └── services/           # API client
│   ├── package.json            # NPM dependencies
│   └── Dockerfile              # Frontend container
├── database/
│   └── init.sql                # Database schema
├── docker-compose.yml          # Container orchestration
├── config.yaml                 # Odoo/LLM configuration
└── README.md                   # This file
```

## Next Steps

1. **Customize Reports**: Modify report templates in frontend
2. **Add Authentication**: Implement JWT-based access control
3. **Schedule Jobs**: Set up cron for automatic daily report generation
4. **Notifications**: Add email alerts for low utilization
5. **Dashboard Widgets**: Create custom KPI cards
6. **Data Export**: Add CSV/Excel export functionality

## License

Internal use only

## Support

Contact: sivasankar@opensource-db.com
