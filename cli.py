"""Flask CLI commands for operational tasks.

Registered in app.py via app.cli.add_command(...). Run with:
    docker compose exec app flask <command>

Available command groups:
    flask admin create               — interactive prompt, never logs the password
    flask admin reset-password EMAIL — interactive prompt
    flask admin list                 — list all super-admins
    flask uploads migrate-to-s3      — one-shot migration of legacy fs uploads to S3

Audit reference: P3 / "Provisionner le super-admin via une CLI dediee".
The ADMIN_INITIAL_PASSWORD env var bootstrap remains for first-boot use
but should not be relied on day to day — once the platform is live, all
admin lifecycle goes through this CLI.
"""

from __future__ import annotations

import datetime
import getpass
import mimetypes
import os
import sys

import bcrypt
import click
from flask.cli import AppGroup
from sqlalchemy import select

from blueprints.auth import validate_password
from database import get_session
from models import Caterer, User, UserRole


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
        # Stamp `password_changed_at` so the first password rotation does
        # invalidate active sessions. `before_request` compares this against
        # `session["pwd_changed_at"]` — a null value would silently disable
        # the session-invalidation tripwire for newly-created admins.
        now = datetime.datetime.utcnow()

        session.add(
            User(
                email=email,
                password_hash=password_hash,
                first_name=first_name,
                last_name=last_name,
                role=UserRole.super_admin,
                is_active=True,
                password_changed_at=now,
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
        # Audit H-5 (2026-05-13): the CLI is the incident-response tool
        # ops reach for when a session is suspected compromised. Without
        # bumping `password_changed_at`, the existing session keeps
        # working — the very fix becomes a no-op against the attacker.
        user.password_changed_at = datetime.datetime.utcnow()
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


# ---------------------------------------------------------------------------
# Uploads — one-shot migration from local filesystem to S3
# ---------------------------------------------------------------------------

uploads_cli = AppGroup(
    "uploads",
    help="Manage user-uploaded assets (logos, photos).",
)


_LEGACY_PREFIX = "/static/uploads/"
_S3_PREFIX = "/uploads/"


def _is_legacy_fs_url(url: str | None) -> bool:
    return isinstance(url, str) and url.startswith(_LEGACY_PREFIX)


def _legacy_url_to_paths(url: str) -> tuple[str, str, str]:
    """Map `/static/uploads/<rest>` to (fs_path, s3_key, new_url).

    `fs_path` is where the file lives on disk today. `s3_key` is what we
    write to in the bucket. `new_url` is what should land in DB after
    the upload so the Flask proxy can serve it.
    """
    rest = url[len(_LEGACY_PREFIX) :]
    fs_path = os.path.join(os.path.dirname(__file__), "static", "uploads", rest)
    s3_key = f"uploads/{rest}"
    new_url = f"{_S3_PREFIX}{rest}"
    return fs_path, s3_key, new_url


@uploads_cli.command(
    "migrate-to-s3",
    help="Upload every legacy `/static/uploads/*` referenced in DB to S3, "
    "then point the column at the new `/uploads/*` URL. Idempotent.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List what would change, do not touch S3 or DB.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Print every file processed (default: only summary + errors).",
)
def migrate_uploads_to_s3(dry_run: bool, verbose: bool):
    """Push every fs-backed caterer logo/photo to S3 and rewrite the URL in DB.

    Behaviour:
      * Logos (`Caterer.logo_url`) and photo galleries (`Caterer.photos`)
        are scanned. Other tables don't currently store uploads.
      * URLs already pointing at `/uploads/*` are skipped (already on S3).
      * URLs whose file is missing on disk are reported as warnings and
        the column is NULLed out (logo) or the entry dropped from the
        list (photos) so dead refs stop crashing templates.
      * The command is safe to re-run: on the second pass nothing matches.

    Exit codes: 0 on success, 1 if any upload failed (DB still committed
    for whatever succeeded).
    """
    # Lazy imports — boto3 is heavy and we don't want the rest of the
    # CLI to pay its cost on `flask --help`.
    from botocore.exceptions import BotoCoreError, ClientError

    from config import settings
    from services.uploads import _get_s3, _s3_enabled

    if not _s3_enabled():
        click.echo(
            "S3_BUCKET / SCW_S3_BUCKET not configured — nothing to do.", err=True
        )
        sys.exit(1)

    s3 = _get_s3()
    bucket = settings.s3_bucket

    uploaded = 0
    skipped_already = 0
    missing = 0
    errors = 0

    with get_session() as session:
        caterers = session.scalars(select(Caterer)).all()
        for c in caterers:
            # --- logo ---------------------------------------------------
            if _is_legacy_fs_url(c.logo_url):
                fs_path, s3_key, new_url = _legacy_url_to_paths(c.logo_url)
                if not os.path.isfile(fs_path):
                    action = "would null column" if dry_run else "nulling column"
                    click.echo(
                        f"  ! [{c.id}] logo file missing: {fs_path} — {action}",
                        err=True,
                    )
                    missing += 1
                    if not dry_run:
                        c.logo_url = None
                else:
                    if dry_run:
                        click.echo(f"  · [{c.id}] would upload logo → {s3_key}")
                    else:
                        try:
                            content_type, _ = mimetypes.guess_type(fs_path)
                            with open(fs_path, "rb") as fh:
                                s3.upload_fileobj(
                                    fh,
                                    bucket,
                                    s3_key,
                                    ExtraArgs={
                                        "ContentType": content_type
                                        or "application/octet-stream",
                                        "CacheControl": "public, max-age=31536000, immutable",
                                    },
                                )
                            c.logo_url = new_url
                            uploaded += 1
                            if verbose:
                                click.echo(f"  ✓ [{c.id}] logo → {s3_key}")
                        except (BotoCoreError, ClientError, OSError) as exc:
                            click.echo(
                                f"  ✗ [{c.id}] logo upload failed: {exc}", err=True
                            )
                            errors += 1
            elif c.logo_url:
                skipped_already += 1

            # --- photos -------------------------------------------------
            if c.photos:
                new_photos: list[str] = []
                changed = False
                for url in c.photos:
                    if not _is_legacy_fs_url(url):
                        new_photos.append(url)
                        if url:
                            skipped_already += 1
                        continue
                    fs_path, s3_key, new_url = _legacy_url_to_paths(url)
                    if not os.path.isfile(fs_path):
                        action = "would drop" if dry_run else "dropping"
                        click.echo(
                            f"  ! [{c.id}] photo file missing: {fs_path} — {action}",
                            err=True,
                        )
                        missing += 1
                        if not dry_run:
                            changed = True
                        else:
                            # In dry-run we want to preserve the legacy
                            # URL in the rebuilt list so the printed
                            # summary doesn't lie about counts. The drop
                            # is reported but not applied.
                            new_photos.append(url)
                        continue
                    if dry_run:
                        click.echo(f"  · [{c.id}] would upload photo → {s3_key}")
                        new_photos.append(url)  # keep legacy URL under dry-run
                        continue
                    try:
                        content_type, _ = mimetypes.guess_type(fs_path)
                        with open(fs_path, "rb") as fh:
                            s3.upload_fileobj(
                                fh,
                                bucket,
                                s3_key,
                                ExtraArgs={
                                    "ContentType": content_type
                                    or "application/octet-stream",
                                    "CacheControl": "public, max-age=31536000, immutable",
                                },
                            )
                        new_photos.append(new_url)
                        uploaded += 1
                        changed = True
                        if verbose:
                            click.echo(f"  ✓ [{c.id}] photo → {s3_key}")
                    except (BotoCoreError, ClientError, OSError) as exc:
                        click.echo(
                            f"  ✗ [{c.id}] photo upload failed ({url}): {exc}",
                            err=True,
                        )
                        errors += 1
                        new_photos.append(url)  # keep legacy on failure
                if changed and not dry_run:
                    c.photos = new_photos or None

    click.echo("")
    click.echo(f"  uploaded:        {uploaded}")
    click.echo(f"  already on S3:   {skipped_already}")
    click.echo(f"  missing on disk: {missing}")
    click.echo(f"  errors:          {errors}")
    if dry_run:
        click.echo("  (dry-run: no changes were committed)")
    sys.exit(1 if errors else 0)
