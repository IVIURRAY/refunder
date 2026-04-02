#!/usr/bin/env python3
"""Invoke the Lambda handler locally using a fixture SES event.

Usage:
    python scripts/invoke_local.py [path/to/ses_event.json]

If no path is given, uses tests/fixtures/sample_ses_event.json.
The raw email referenced by the S3 key in the event must already be
uploaded to your configured S3 bucket (or use a local mock).
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.ses_handler import handler


class MockLambdaContext:
    """Minimal mock of the Lambda context object."""

    function_name = "refundagent-email-processor-local"
    aws_request_id = "local-invocation-000"
    memory_limit_in_mb = 256


def main() -> None:
    """Load a fixture event and invoke the Lambda handler locally.

    Returns:
        None
    """
    fixture_path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/sample_ses_event.json"

    event_path = Path(fixture_path)
    if not event_path.exists():
        print(f"ERROR: Event file not found: {fixture_path}")
        sys.exit(1)

    event = json.loads(event_path.read_text())
    print(f"==> Invoking handler with event from: {fixture_path}")

    try:
        result = handler(event, MockLambdaContext())
        print(f"==> Result: {json.dumps(result, indent=2)}")
    except Exception as exc:
        print(f"==> Handler raised exception: {exc}")
        raise


if __name__ == "__main__":
    main()
