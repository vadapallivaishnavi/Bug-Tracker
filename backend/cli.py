"""
Custom Flask CLI commands.

Usage (run inside the backend container):
    docker exec -it <backend-container-name> flask create-admin

This creates (or promotes/updates) a local account with role='admin', which
authenticates entirely against the local password_hash -- no Odoo required
-- and is exempt from the 'reporter' scoping in bug_list()/bug_detail(), so
it can see every bug report submitted by every user in "All Reports".
"""
import click
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash


def register_cli(app):
    @app.cli.command('create-admin')
    @click.option('--name', default='Admin', show_default=True,
                  help='Display name for the account.')
    @click.option('--email', default='ai@opensource-db.com', show_default=True,
                  help='Login email for the account.')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True,
                  help='Password for the account (prompted securely if omitted).')
    @click.option('--bug-tracker-only/--full-nav', default=True, show_default=True,
                  help='Restrict the navbar to Bug Tracker only (still sees ALL reports, '
                       'unlike a reporter account). Pass --full-nav for the normal admin navbar.')
    @with_appcontext
    def create_admin(name, email, password, bug_tracker_only):
        """Create or promote a local admin account that can view every
        report in All Reports, independent of Odoo. Safe to re-run --
        if the email already exists it just updates the name/role/password
        instead of failing.
        """
        from app import db
        from models import User

        email = email.strip().lower()
        name = name.strip() or 'Admin'

        if len(password) < 8:
            click.echo('Password must be at least 8 characters.')
            raise SystemExit(1)

        user = User.query.filter_by(email=email).first()
        if user:
            user.name = name
            user.role = 'admin'
            user.password_hash = generate_password_hash(password)
            user.bug_tracker_only = bug_tracker_only
            action = 'Updated existing'
        else:
            user = User(
                name=name,
                email=email,
                role='admin',
                password_hash=generate_password_hash(password),
                odoo_user_id=None,
                bug_tracker_only=bug_tracker_only,
            )
            db.session.add(user)
            action = 'Created new'

        db.session.commit()
        click.echo(f"{action} admin account: {name} <{email}> (role=admin)")
        nav_note = "restricted to Bug Tracker only" if bug_tracker_only else "full admin navbar"
        click.echo(f"Navbar: {nav_note}. This account sees every report in All Reports.")
