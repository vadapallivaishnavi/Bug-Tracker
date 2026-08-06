# Quick Start Guide

## 5-Minute Setup (Development)

### Prerequisites
- Docker & Docker Compose
- Git
- Odoo credentials

### Step 1: Clone & Configure
```bash
cd /Users/sivasankar/projects/odoo/hostedapp

# Copy environment template
cp backend/.env.example backend/.env

# Edit configuration
nano backend/.env
# Update: ODOO_URL, ODOO_USER, ODOO_PASSWORD, LLM_API_KEY
```

### Step 2: Start Services
```bash
# Start all containers
docker-compose up -d

# Wait for database to initialize
sleep 10

# Check status
docker-compose ps
```

### Step 3: Access Application
- **Frontend**: http://localhost:3000
- **API**: http://localhost:5000/api
- **Database**: localhost:5432

### Step 4: Verify Setup
```bash
# Health check
curl http://localhost:5000/api/health

# Should return: {"status":"healthy",...}
```

## Next Steps

1. **View Dashboard**: Navigate to http://localhost:3000
2. **Generate Report**: Click "Generate Report" button
3. **View Analytics**: Go to Analytics section
4. **Browse History**: Check Reports page for all stored reports

---

## 30-Minute Full Setup (Production)

### Prerequisites
- Linux/macOS server with Docker
- PostgreSQL 16+
- Public domain name (for HTTPS)
- SSL certificates

### Step 1: Server Setup
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Create app directory
sudo mkdir -p /opt/team_activity_report
cd /opt/team_activity_report

# Clone application
git clone <repo> .
```

### Step 2: Environment Configuration
```bash
# Create production .env
cat > backend/.env << EOF
DATABASE_URL=postgresql://app_user:strong_password@postgres:5432/team_activity_db
JWT_SECRET_KEY=$(openssl rand -hex 32)
FLASK_ENV=production

ODOO_URL=https://hrms.opensource-db.com
ODOO_DB=openhrms18
ODOO_USER=your_email@example.com
ODOO_PASSWORD=your_password

LLM_API_URL=https://inference.do-ai.run/v1/chat/completions
LLM_MODEL=openai-gpt-oss-120b
LLM_API_KEY=your_api_key

BACKEND_PORT=5000
BACKEND_HOST=0.0.0.0
EOF

chmod 600 backend/.env
```

### Step 3: SSL Certificates
```bash
# Option 1: Self-signed (dev only)
openssl req -x509 -newkey rsa:4096 -nodes \
  -out nginx/ssl/cert.pem \
  -keyout nginx/ssl/key.pem \
  -days 365

# Option 2: Let's Encrypt (production)
sudo apt-get install certbot
sudo certbot certonly --standalone -d your-domain.com
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem nginx/ssl/key.pem
```

### Step 4: Deploy
```bash
# Build and start
docker-compose build
docker-compose up -d

# Verify
docker-compose ps
docker-compose logs -f
```

### Step 5: Verify
```bash
# API health
curl https://your-domain.com/api/health

# Frontend access
curl https://your-domain.com -I
```

---

## Common Operations

### Generate Report Now
```bash
curl -X POST http://localhost:5000/api/reports \
  -H "Content-Type: application/json" \
  -d '{
    "report_type": "team",
    "hours_window": 24,
    "title": "Daily Team Report"
  }'
```

### List All Reports
```bash
curl http://localhost:5000/api/reports?page=1&per_page=20
```

### Get User Analytics
```bash
curl http://localhost:5000/api/analytics/user/USER_ID/summary?days=30
```

### Get Team Summary
```bash
curl http://localhost:5000/api/analytics/team/summary?days=7
```

### View Trends
```bash
curl http://localhost:5000/api/analytics/trends?metric=total_hours&days=90
```

### Download Report HTML
```bash
curl -o report.html http://localhost:5000/api/reports/REPORT_ID/html
```

---

## Troubleshooting

### Port Already in Use
```bash
# Find process using port
lsof -i :5000
lsof -i :3000

# Kill process
kill -9 <PID>

# Or use different ports
docker-compose down
# Edit docker-compose.yml ports
docker-compose up -d
```

### Database Connection Error
```bash
# Check PostgreSQL is running
docker ps | grep postgres

# Check logs
docker logs team_activity_db

# Test connection
docker exec team_activity_db psql -U postgres -d team_activity_db -c "SELECT 1"
```

### Backend Not Starting
```bash
# Check logs
docker logs team_activity_backend

# Try restarting
docker-compose restart backend

# Check database migrations
docker exec team_activity_backend flask db current
```

### Odoo Connection Failed
```bash
# Verify credentials
# Test Odoo server reachability
curl -I https://hrms.opensource-db.com

# Check configuration
docker exec team_activity_backend cat /app/config.yaml

# Try manual connection
docker exec team_activity_backend python << 'EOF'
from services import OdooService
try:
    service = OdooService()
    uid, models = service.connect()
    print("✓ Connected successfully")
except Exception as e:
    print(f"✗ Connection failed: {e}")
EOF
```

---

## Architecture Overview

```
┌──────────────────────────────────────┐
│   Frontend (React/Node.js)           │
│   http://localhost:3000              │
└──────────────┬───────────────────────┘
               │ HTTP/JSON
┌──────────────▼───────────────────────┐
│   Nginx (Reverse Proxy)              │
│   http://localhost:80/443            │
│   ├── / → Frontend                   │
│   └── /api → Backend                 │
└──────────────┬───────────────────────┘
               │ HTTP/JSON
┌──────────────▼───────────────────────┐
│   Backend (Flask/Python)             │
│   http://localhost:5000              │
│   ├── Models (SQLAlchemy)            │
│   ├── Services (Business Logic)      │
│   └── Routes (API Endpoints)         │
└──────────────┬───────────────────────┘
               │ PostgreSQL
┌──────────────▼───────────────────────┐
│   Database (PostgreSQL)              │
│   localhost:5432                     │
│   ├── users                          │
│   ├── projects                       │
│   ├── tasks                          │
│   ├── timesheets                     │
│   ├── reports                        │
│   ├── analytics                      │
│   └── ...                            │
└──────────────────────────────────────┘
                  │ XML-RPC
         ┌────────▼────────┐
         │  Odoo Server    │
         │ (External)      │
         └─────────────────┘
```

---

## File Structure
```
hostedapp/
├── backend/              # Flask API server
│   ├── app.py           # Application factory
│   ├── models.py        # Database models
│   ├── services.py      # Business logic
│   ├── api/
│   │   └── routes.py    # API endpoints
│   ├── requirements.txt  # Python dependencies
│   ├── Dockerfile       # Container image
│   └── .env.example     # Configuration template
│
├── frontend/            # React web interface
│   ├── src/
│   │   ├── App.js       # Main app component
│   │   ├── pages/       # Page components
│   │   ├── components/  # Reusable components
│   │   └── services/    # API client
│   ├── package.json     # NPM dependencies
│   ├── Dockerfile       # Container image
│   └── public/          # Static assets
│
├── database/            # Database setup
│   └── init.sql         # Schema initialization
│
├── nginx/               # Reverse proxy configuration
│   ├── nginx.conf       # Main configuration
│   └── ssl/             # SSL certificates
│
├── docs/                # Documentation
│   ├── README.md        # This file
│   ├── DEPLOYMENT.md    # Deployment guide
│   ├── MIGRATION.md     # Migration guide
│   └── API.md           # API documentation (TODO)
│
├── docker-compose.yml   # Container orchestration
├── config.yaml          # Odoo/LLM configuration
└── .gitignore          # Git ignore rules
```

---

## Key URLs & Ports

| Service | URL | Port | Purpose |
|---------|-----|------|---------|
| Frontend | http://localhost:3000 | 3000 | Web UI |
| Backend API | http://localhost:5000 | 5000 | REST API |
| PostgreSQL | localhost | 5432 | Database |
| Nginx | http://localhost:80/443 | 80/443 | Proxy (production) |

---

## Getting Help

### Check Application Health
```bash
# API health endpoint
curl http://localhost:5000/api/health

# Database connectivity
docker exec team_activity_db pg_isready -U postgres

# Service logs
docker-compose logs backend
docker-compose logs frontend
docker-compose logs postgres
```

### Review Documentation
- **Deployment**: See `docs/DEPLOYMENT.md`
- **Migration**: See `docs/MIGRATION.md`
- **API**: See `/api/docs` (Swagger, if enabled)

### Debug Issues
```bash
# Backend shell
docker exec -it team_activity_backend bash

# Database shell
docker exec -it team_activity_db psql -U postgres

# View raw logs
docker-compose logs --tail=100 backend > backend.log
```

---

## Next: Production Checklist

- [ ] Configure SSL certificates
- [ ] Set up database backups
- [ ] Configure email notifications
- [ ] Set up monitoring/alerting
- [ ] Plan capacity scaling
- [ ] Document runbooks
- [ ] Train team on new system
- [ ] Schedule migration date

See `docs/DEPLOYMENT.md` for detailed production setup.
