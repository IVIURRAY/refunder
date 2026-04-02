"""Command-line interface for RefundAgent.

Provides commands for viewing, filtering, and updating refund claims and
their associated email events. Uses rich for formatted console output.

Usage:
    python -m src.cli.main claims list
    python -m src.cli.main claims list --status pending
    python -m src.cli.main claims show <claim-id>
    python -m src.cli.main claims update-status <id> <status>
    python -m src.cli.main emails list
    python -m src.cli.main emails show <event-id>
    python -m src.cli.main process <s3-key>
"""

import json
import uuid
from typing import Optional

import click
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from src.db.connection import get_session
from src.models.claim import Claim, ClaimStatus, ClaimVertical, EmailEvent

logger = structlog.get_logger(__name__)
console = Console()

# Status colour map for rich markup
STATUS_COLOURS: dict[str, str] = {
    ClaimStatus.DETECTED.value: "blue",
    ClaimStatus.PENDING.value: "yellow",
    ClaimStatus.ACKNOWLEDGED.value: "cyan",
    ClaimStatus.IN_REVIEW.value: "magenta",
    ClaimStatus.RESOLVED.value: "green",
    ClaimStatus.REJECTED.value: "red",
    ClaimStatus.ESCALATED.value: "bright_red",
    ClaimStatus.CLOSED.value: "dim",
}


def _coloured_status(status: str) -> str:
    colour = STATUS_COLOURS.get(status, "white")
    return f"[{colour}]{status}[/{colour}]"


@click.group()
def cli() -> None:
    """RefundAgent — AI-powered refund claims automation."""
    pass


# ---------------------------------------------------------------------------
# claims group
# ---------------------------------------------------------------------------

@cli.group()
def claims() -> None:
    """Manage refund claims."""
    pass


@claims.command("list")
@click.option(
    "--status",
    type=click.Choice([s.value for s in ClaimStatus], case_sensitive=False),
    default=None,
    help="Filter claims by status.",
)
def claims_list(status: Optional[str]) -> None:
    """List all claims, optionally filtered by status.

    Args:
        status: Optional status filter.

    Returns:
        None
    """
    from src.claims.manager import list_claims

    status_enum = ClaimStatus(status) if status else None

    with get_session() as session:
        all_claims = list_claims(session, status=status_enum)

    if not all_claims:
        console.print("[dim]No claims found.[/dim]")
        return

    table = Table(
        "ID", "Merchant", "Vertical", "Amount", "Status", "Reference", "Detected",
        box=box.ROUNDED,
        show_lines=False,
    )

    for c in all_claims:
        amount_str = f"{c.currency} {c.amount:.2f}" if c.amount else "—"
        table.add_row(
            str(c.id)[:8] + "…",
            c.merchant,
            c.vertical.value,
            amount_str,
            _coloured_status(c.status.value),
            c.reference or "—",
            c.detected_at.strftime("%Y-%m-%d %H:%M") if c.detected_at else "—",
        )

    console.print(table)


@claims.command("show")
@click.argument("claim_id")
def claims_show(claim_id: str) -> None:
    """Show full details for a single claim.

    Args:
        claim_id: UUID of the claim to display.

    Returns:
        None
    """
    from src.claims.manager import get_claim_by_id

    try:
        parsed_id = uuid.UUID(claim_id)
    except ValueError:
        console.print(f"[red]Invalid UUID: {claim_id}[/red]")
        raise SystemExit(1)

    with get_session() as session:
        claim = get_claim_by_id(session, parsed_id)

    if not claim:
        console.print(f"[red]Claim {claim_id} not found.[/red]")
        raise SystemExit(1)

    details = (
        f"[bold]Merchant:[/bold] {claim.merchant}\n"
        f"[bold]Vertical:[/bold] {claim.vertical.value}\n"
        f"[bold]Amount:[/bold] {claim.currency} {claim.amount or '—'}\n"
        f"[bold]Reference:[/bold] {claim.reference or '—'}\n"
        f"[bold]Status:[/bold] {_coloured_status(claim.status.value)}\n"
        f"[bold]Detected:[/bold] {claim.detected_at}\n"
        f"[bold]Last Updated:[/bold] {claim.last_updated}\n"
        f"[bold]Resolved At:[/bold] {claim.resolved_at or '—'}\n"
        f"[bold]Resolved Amount:[/bold] {claim.resolved_amount or '—'}\n"
        f"[bold]Next Action:[/bold] {claim.next_action_at or '—'}\n"
        f"[bold]Description:[/bold] {claim.description or '—'}\n"
        f"[bold]Metadata:[/bold] {json.dumps(claim.metadata_ or {}, indent=2)}"
    )
    console.print(Panel(details, title=f"Claim {str(claim.id)[:8]}…", border_style="blue"))


@claims.command("update-status")
@click.argument("claim_id")
@click.argument("new_status", type=click.Choice([s.value for s in ClaimStatus], case_sensitive=False))
def claims_update_status(claim_id: str, new_status: str) -> None:
    """Manually update a claim's status.

    Args:
        claim_id: UUID of the claim to update.
        new_status: The target status value.

    Returns:
        None
    """
    from src.claims.manager import update_claim_status
    from src.claims.state_machine import InvalidStatusTransitionError

    try:
        parsed_id = uuid.UUID(claim_id)
    except ValueError:
        console.print(f"[red]Invalid UUID: {claim_id}[/red]")
        raise SystemExit(1)

    status_enum = ClaimStatus(new_status)

    try:
        with get_session() as session:
            claim = update_claim_status(session, parsed_id, status_enum)
        console.print(f"[green]Claim {claim_id[:8]}… updated to {_coloured_status(claim.status.value)}[/green]")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    except InvalidStatusTransitionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# emails group
# ---------------------------------------------------------------------------

@cli.group()
def emails() -> None:
    """Manage email events."""
    pass


@emails.command("list")
@click.option("--limit", default=20, show_default=True, help="Maximum number of events to show.")
def emails_list(limit: int) -> None:
    """List recent inbound email events.

    Args:
        limit: Maximum number of events to display.

    Returns:
        None
    """
    with get_session() as session:
        events = (
            session.query(EmailEvent)
            .order_by(EmailEvent.received_at.desc())
            .limit(limit)
            .all()
        )

    if not events:
        console.print("[dim]No email events found.[/dim]")
        return

    table = Table(
        "ID", "Subject", "Sender", "Classification", "Proc. Status", "Received",
        box=box.ROUNDED,
    )
    for ev in events:
        table.add_row(
            str(ev.id)[:8] + "…",
            (ev.subject or "")[:50],
            (ev.sender or "")[:30],
            ev.classification or "—",
            ev.processing_status,
            ev.received_at.strftime("%Y-%m-%d %H:%M") if ev.received_at else "—",
        )
    console.print(table)


@emails.command("show")
@click.argument("event_id")
def emails_show(event_id: str) -> None:
    """Show full details for a single email event.

    Args:
        event_id: UUID of the email event to display.

    Returns:
        None
    """
    try:
        parsed_id = uuid.UUID(event_id)
    except ValueError:
        console.print(f"[red]Invalid UUID: {event_id}[/red]")
        raise SystemExit(1)

    with get_session() as session:
        ev = session.get(EmailEvent, parsed_id)

    if not ev:
        console.print(f"[red]Email event {event_id} not found.[/red]")
        raise SystemExit(1)

    details = (
        f"[bold]Message ID:[/bold] {ev.message_id}\n"
        f"[bold]S3 Key:[/bold] {ev.s3_key}\n"
        f"[bold]Sender:[/bold] {ev.sender or '—'}\n"
        f"[bold]Subject:[/bold] {ev.subject or '—'}\n"
        f"[bold]Received:[/bold] {ev.received_at}\n"
        f"[bold]Direction:[/bold] {ev.direction}\n"
        f"[bold]Classification:[/bold] {ev.classification or '—'}\n"
        f"[bold]Processing Status:[/bold] {ev.processing_status}\n"
        f"[bold]Claim ID:[/bold] {ev.claim_id or '—'}\n"
        f"[bold]Extracted Data:[/bold]\n{json.dumps(ev.extracted_data or {}, indent=2)}"
    )
    if ev.error_message:
        details += f"\n[bold red]Error:[/bold red] {ev.error_message}"

    console.print(Panel(details, title=f"Email Event {str(ev.id)[:8]}…", border_style="cyan"))


# ---------------------------------------------------------------------------
# process command
# ---------------------------------------------------------------------------

@cli.command("process")
@click.argument("s3_key")
def process_email(s3_key: str) -> None:
    """Manually trigger processing of a raw email from S3.

    Useful for reprocessing failed events or testing locally.

    Args:
        s3_key: The S3 object key of the raw email to process.

    Returns:
        None
    """
    from src.ingestion.ses_handler import handler
    from src.config import settings

    # Construct a minimal synthetic SES event pointing to the given S3 key
    synthetic_event = {
        "Records": [
            {
                "ses": {
                    "receipt": {
                        "action": {
                            "type": "S3",
                            "bucketName": settings.raw_emails_bucket,
                            "objectKey": s3_key,
                        }
                    }
                }
            }
        ]
    }

    console.print(f"[blue]Processing email from S3 key: {s3_key}[/blue]")
    try:
        result = handler(synthetic_event, context=None)
        console.print(f"[green]Processing complete: {result}[/green]")
    except Exception as exc:
        console.print(f"[red]Processing failed: {exc}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
