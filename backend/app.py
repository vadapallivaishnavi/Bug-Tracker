"""
Team Activity Report - Backend Application
Flask API for report generation, storage, and retrieval with historical analysis
"""
import os
from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from datetime import timedelta
import logging

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app(config_name='development'):
    """
    Application factory function
    """
    app = Flask(__name__)
    
    # Configuration
    if config_name == 'development':
        app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
            'DATABASE_URL', 
            'postgresql://postgres:postgres@localhost:5532/team_activity_db'
        )
        app.config['DEBUG'] = True
    elif config_name == 'production':
        app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
        app.config['DEBUG'] = False
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JSON_SORT_KEYS'] = False
    
    # JWT Configuration
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)
    # Plain <img>/<a> tags (used to view/download screenshots & attachments)
    # can't set an Authorization header, so those specific requests carry
    # the token as ?token=... instead. JWT_TOKEN_LOCATION covers both;
    # everything else (all normal API calls) keeps using the header.
    app.config['JWT_TOKEN_LOCATION'] = ['headers', 'query_string']
    app.config['JWT_QUERY_STRING_NAME'] = 'token'
    
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    
    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # Register blueprints
    from api.routes import main_bp, report_bp, analytics_bp, auth_bp, bugtracker_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(bugtracker_bp)

    # Custom CLI commands (e.g. `flask create-admin`)
    from cli import register_cli
    register_cli(app)
    
    # Create database tables
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Error creating database tables: {e}")

        # db.create_all() only creates tables that don't exist yet -- it
        # won't add new columns to a table that's already there. Patch in
        # any columns added by later releases so existing deployments don't
        # need a manual migration step.
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            if 'bug_reports' in inspector.get_table_names():
                existing_cols = {c['name'] for c in inspector.get_columns('bug_reports')}
                if 'sprint' not in existing_cols:
                    db.session.execute(text('ALTER TABLE bug_reports ADD COLUMN sprint INTEGER'))
                    db.session.commit()
                    logger.info("Added missing 'sprint' column to bug_reports")
                if 'roadmap' not in existing_cols:
                    db.session.execute(text("ALTER TABLE bug_reports ADD COLUMN roadmap BOOLEAN NOT NULL DEFAULT FALSE"))
                    db.session.commit()
                    logger.info("Added missing 'roadmap' column to bug_reports")
                if 'user_id' not in existing_cols:
                    db.session.execute(text("ALTER TABLE bug_reports ADD COLUMN user_id VARCHAR(36) REFERENCES users(id)"))
                    db.session.commit()
                    logger.info("Added missing 'user_id' column to bug_reports")

            # RBAC columns on users, plus relaxing odoo_user_id to nullable
            # so self-registered ('reporter') accounts -- which have no
            # Odoo employee behind them -- can be created at all.
            if 'users' in inspector.get_table_names():
                existing_user_cols = {c['name'] for c in inspector.get_columns('users')}
                if 'role' not in existing_user_cols:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'employee'"))
                    db.session.commit()
                    logger.info("Added missing 'role' column to users")
                if 'password_hash' not in existing_user_cols:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)"))
                    db.session.commit()
                    logger.info("Added missing 'password_hash' column to users")
                if 'bug_tracker_only' not in existing_user_cols:
                    db.session.execute(text("ALTER TABLE users ADD COLUMN bug_tracker_only BOOLEAN NOT NULL DEFAULT FALSE"))
                    db.session.commit()
                    logger.info("Added missing 'bug_tracker_only' column to users")
                odoo_col = next((c for c in inspector.get_columns('users') if c['name'] == 'odoo_user_id'), None)
                if odoo_col and not odoo_col.get('nullable', True):
                    db.session.execute(text("ALTER TABLE users ALTER COLUMN odoo_user_id DROP NOT NULL"))
                    db.session.commit()
                    logger.info("Relaxed users.odoo_user_id to nullable")
        except Exception as e:
            logger.error(f"Error patching bug_reports schema: {e}")
            db.session.rollback()

        # Seed the sign-in welcome popup with a default image so it's ready
        # to go out of the box; an admin can replace it any time from
        # Settings without touching this file again.
        try:
            from models import WelcomePopup
            if not WelcomePopup.query.get('default'):
                seed_path = os.path.join(os.path.dirname(__file__), 'seed_assets', 'welcome_popup_default.jpeg')
                if os.path.exists(seed_path):
                    with open(seed_path, 'rb') as f:
                        image_bytes = f.read()
                    db.session.add(WelcomePopup(
                        id='default',
                        enabled=True,
                        title='Cortex Byte',
                        caption="Every Postgres outage starts as a boring metric -- OSDBcortex catches it before it becomes your problem.",
                        image_filename='cortex_byte.jpeg',
                        image_content_type='image/jpeg',
                        image_data=image_bytes,
                    ))
                    db.session.commit()
                    logger.info("Seeded default welcome popup image")
        except Exception as e:
            logger.error(f"Error seeding welcome popup: {e}")
            db.session.rollback()

    return app

# Create default app instance for Gunicorn
app = create_app('production')

if __name__ == '__main__':
    app = create_app('development')
    app.run(host='0.0.0.0', port=5000, debug=True)