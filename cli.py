"""Flask CLI commands for operational tasks.

Registered in app.py via app.cli.add_command(...). Run with:
    docker compose exec app flask <command>

Available command groups:
    flask admin create               — interactive prompt, never logs the password
    flask admin reset-password EMAIL — interactive prompt
    flask admin list                 — list all super-admins

Audit reference: P3 / "Provisionner le super-admin via une CLI dediee".
The ADMIN_INITIAL_PASSWORD env var bootstrap remains for first-boot use
but should not be relied on day to day — once the platform is live, all
admin lifecycle goes through this CLI.
"""

from __future__ import annotations

import getpass
import sys

import bcrypt
import click
from flask.cli import AppGroup
from sqlalchemy import select

from blueprints.auth import validate_password
from database import get_session
from models import User, UserRole


admin_cli = AppGroup("admin", help="Manage super-admin accounts.")


def _read_password_twice(prompt: str = "Mot de passe") -> str:
    """Prompt twice to avoid typo-locking the account, with policy validation."""
    while True:
        first = getpass.getpass(f"{prompt} : ")
        if not first:
            click.echo("Annule.", err=True)
            sys.exit(1)
        error = validate_password(first)
        if error:
            click.echo(f"  Refuse : {error}", err=True)
            continue
        second = getpass.getpass(f"{prompt} (confirmation) : ")
        if first != second:
            click.echo("  Les deux saisies different, recommence.", err=True)
            continue
        return first


@admin_cli.command("create", help="Create a new super-admin (interactive).")
@click.option("--email", prompt=True, help="Email of the new super-admin.")
@click.option("--first-name", prompt=True, default="Admin")
@click.option("--last-name", prompt=True, default="Plateforme")
def create_admin(email: str, first_name: str, last_name: str):
    email = email.strip().lower()
    with get_session() as session:
        existing = session.scalar(select(User).where(User.email == email))
        if existing:
            click.echo(f"Un compte existe deja pour {email}.", err=True)
            sys.exit(1)

        password = _read_password_twice()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        session.add(
            User(
                email=email,
                password_hash=password_hash,
                first_name=first_name,
                last_name=last_name,
                role=UserRole.super_admin,
                is_active=True,
            )
        )
        click.echo(f"Super-admin cree : {email}")


@admin_cli.command(
    "reset-password", help="Reset the password of an existing super-admin."
)
@click.argument("email")
def reset_password(email: str):
    email = email.strip().lower()
    with get_session() as session:
        user = session.scalar(
            select(User).where(User.email == email, User.role == UserRole.super_admin)
        )
        if not user:
            click.echo(f"Aucun super-admin trouve pour {email}.", err=True)
            sys.exit(1)

        password = _read_password_twice("Nouveau mot de passe")
        user.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        click.echo(f"Mot de passe reinitialise pour {email}.")


@admin_cli.command("list", help="List every super-admin (active + disabled).")
def list_admins():
    with get_session() as session:
        rows = session.scalars(
            select(User)
            .where(User.role == UserRole.super_admin)
            .order_by(User.created_at)
        ).all()
        if not rows:
            click.echo("Aucun super-admin.")
            return
        for u in rows:
            status = "actif" if u.is_active else "DESACTIVE"
            click.echo(
                f"  - {u.email}  ({u.first_name} {u.last_name}, {status}, cree {u.created_at:%Y-%m-%d})"
            )


@admin_cli.command(
    "disable",
    help="Mark a super-admin as inactive (soft delete, audit trail preserved).",
)
@click.argument("email")
def disable_admin(email: str):
    email = email.strip().lower()
    with get_session() as session:
        user = session.scalar(
            select(User).where(User.email == email, User.role == UserRole.super_admin)
        )
        if not user:
            click.echo(f"Aucun super-admin trouve pour {email}.", err=True)
            sys.exit(1)
        user.is_active = False
        click.echo(f"Super-admin desactive : {email}")
