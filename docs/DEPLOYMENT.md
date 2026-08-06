# Deployment & Operations Guide

## Pre-Deployment Checklist

- [ ] PostgreSQL 16+ available
- [ ] Docker & Docker Compose installed
- [ ] All environment variables configured
- [ ] Odoo server reachable and credentials valid
- [ ] LLM API credentials and rate limits verified
- [ ] SSL certificates ready for HTTPS (optional but recommended)
- [ ] Backup strategy documented

## Deployment Steps

### 1. Environment Setup

```bash
# Create production .env
cat > backend/.env << EOF
DATABASE_URL=postgresql://postgres:securepassword@postgres:5432/team_activity_db
JWT_SECRET_KEY=$(openssl rand -hex 32)
FLASK_ENV=production
ODOO_URL=https://hrms.opensource-db.com
ODOO_DB=openhrms18
ODOO_USER=your_email@example.com
ODOO_PASSWORD=your_password
LLM_API_URL=https://inference.do-ai.run/v1/chat/completions
LLM_MODEL=openai-gpt-oss-120b
LLM_API_KEY=your_api_key
LLM_MAX_TOKENS=2000
BACKEND_PORT=5000
BACKEND_HOST=0.0.0.0
EOF
```

### 2. Database Initialization

```bash
# Start only PostgreSQL first
docker-compose up -d postgres

# Wait for PostgreSQL to be ready
sleep 10

# Check database
docker exec team_activity_db psql -U postgres -d team_activity_db -c "\\dt"
```

### 3. Start Complete Stack

```bash
# Start all services
docker-compose up -d

# Verify all services are running
docker-compose ps

# Check logs
docker-compose logs -f
```

### 4. Verify Health

```bash
# Check backend health
curl http://localhost:5000/api/health

# Expected response:
# {"status":"healthy","timestamp":"2024-...","database":"connected"}

# Check frontend accessibility
curl http://localhost:3000 -I

# Test database connection
docker exec team_activity_backend python -c "from app import db; db.session.execute('SELECT 1')"
```

## Database Maintenance

### Backup

```bash
# Full database backup
docker exec team_activity_db pg_dump -U postgres team_activity_db > backup_$(date +%Y%m%d_%H%M%S).sql

# Or using automated backups
docker exec team_activity_db pg_dump -U postgres team_activity_db | gzip > backup_$(date +%Y%m%d).sql.gz
```

### Restore

```bash
# Restore from backup
docker exec -i team_activity_db psql -U postgres team_activity_db < backup_2024xxxx.sql
```

### Cleanup Old Data

```bash
# Archive reports older than 90 days
docker exec team_activity_backend python << EOF
from app import db, create_app
from models import Report
from datetime import datetime, timedelta

app = create_app('production')
with app.app_context():
    cutoff = datetime.utcnow() - timedelta(days=90)
    old_reports = Report.query.filter(Report.created_at < cutoff).update({'is_archived': True})
    db.session.commit()
    print(f"Archived {old_reports} old reports")
EOF
```

## Monitoring & Logging

### Log Files

```bash
# Real-time logs
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f postgres

# Specific service
docker-compose logs --tail=100 backend

# Save logs to file
docker-compose logs backend > backend_logs.txt
```

### Health Monitoring

```bash
#!/bin/bash
# health_check.sh - Monitor service health

while true; do
  echo "=== $(date) ==="
  
  # Check backend
  if curl -s http://localhost:5000/api/health | grep -q "healthy"; then
    echo "✓ Backend: healthy"
  else
    echo "✗ Backend: UNHEALTHY"
  fi
  
  # Check database
  if docker exec team_activity_db pg_isready -U postgres > /dev/null; then
    echo "✓ Database: connected"
  else
    echo "✗ Database: DISCONNECTED"
  fi
  
  # Check frontend
  if curl -s http://localhost:3000 -I | grep -q "200\|301"; then
    echo "✓ Frontend: responding"
  else
    echo "✗ Frontend: NOT responding"
  fi
  
  sleep 60
done
```

## Scaling Considerations

### Horizontal Scaling

```yaml
# Update docker-compose.yml for multiple backend instances
backend:
  deploy:
    replicas: 3  # Scale to 3 instances
```

### Database Optimization

```sql
-- Monitor query performance
SELECT query, calls, mean_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;

-- Analyze tables for optimization
ANALYZE report_analytics;
REINDEX TABLE report_analytics;
```

## Security Hardening

### 1. Enable HTTPS

```bash
# Generate self-signed certificate (dev only)
openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365
```

### 2. Database Security

```bash
# Change default password
docker exec team_activity_db psql -U postgres -c "ALTER USER postgres WITH PASSWORD 'strong_password';"

# Create restricted user
docker exec team_activity_db psql -U postgres << EOF
CREATE USER app_user WITH PASSWORD 'app_password';
GRANT CONNECT ON DATABASE team_activity_db TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
EOF
```

### 3. API Security

```python
# In backend app.py - Add rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Apply to routes
@main_bp.route('/reports', methods=['POST'])
@limiter.limit("5 per hour")
def create_report():
    ...
```

## Troubleshooting Common Issues

### Issue: PostgreSQL Connection Refused

```bash
# Check if postgres container is running
docker ps | grep postgres

# Check logs
docker logs team_activity_db

# Restart postgres
docker-compose restart postgres
```

### Issue: Backend Crashes on Startup

```bash
# Check database migrations
docker exec team_activity_backend flask db current
docker exec team_activity_backend flask db upgrade

# Verify database schema
docker exec team_activity_db psql -U postgres team_activity_db -c "\\dt"
```

### Issue: LLM API Rate Limit

```python
# Add retry logic with exponential backoff
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def call_llm_api(prompt):
    response = requests.post(llm_api_url, json={"prompt": prompt})
    response.raise_for_status()
    return response.json()
```

### Issue: Out of Memory

```bash
# Check Docker memory usage
docker stats

# Increase memory limits in docker-compose.yml
backend:
  mem_limit: 2g
  memswap_limit: 2g
```

## Performance Tuning

### Database Query Optimization

```sql
-- Index frequently used columns
CREATE INDEX idx_analytics_user_date ON report_analytics(user_id, date DESC);
CREATE INDEX idx_timesheets_date_user ON timesheets(date DESC, user_id);

-- Cluster tables for faster scans
CLUSTER report_analytics USING idx_analytics_user_date;
```

### Connection Pooling

```python
# In app.py
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 20,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
    'max_overflow': 40,
}
```

## Scheduled Tasks

### Daily Report Generation

```bash
#!/bin/bash
# daily_report.sh - Generate reports daily at 8 AM

0 8 * * * cd /path/to/hostedapp && docker-compose exec -T backend python -c "from services import ReportGenerationService; ReportGenerationService.sync_odoo_data(24)"
```

### Weekly Analytics Aggregation

```bash
# Add to crontab
0 2 * * 0 docker-compose exec -T backend python << 'EOF'
from services import ReportGenerationService
for i in range(1, 8):
    ReportGenerationService.generate_analytics()
EOF
```

## Backup & Recovery Plan

### Automated Daily Backups

```bash
#!/bin/bash
# backup_daily.sh

BACKUP_DIR="/backups/team_activity"
mkdir -p $BACKUP_DIR

docker exec team_activity_db pg_dump -U postgres team_activity_db | \
  gzip > $BACKUP_DIR/team_activity_$(date +%Y%m%d_%H%M%S).sql.gz

# Keep only last 30 days
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete
```

### Disaster Recovery

```bash
# 1. Restore database
docker-compose down
gunzip -c $BACKUP_DIR/team_activity_20240115_120000.sql.gz | \
  docker exec -i team_activity_db psql -U postgres team_activity_db

# 2. Verify data integrity
docker-compose exec backend python -c \
  "from models import User, Report; print(f'Users: {User.query.count()}, Reports: {Report.query.count()}')"

# 3. Restart application
docker-compose up -d
```

## Documentation

- **API Documentation**: `/docs/API.md` (generate with Swagger)
- **Database Schema**: `/docs/SCHEMA.md`
- **Deployment Scenarios**: `/docs/SCENARIOS.md`
- **Runbooks**: `/docs/RUNBOOKS/`

## Support & Escalation

- **Level 1**: Check health endpoint, review logs
- **Level 2**: Restart affected service
- **Level 3**: Database maintenance, backup/restore
- **Level 4**: Contact DevOps team
