import subprocess
import sys


def test_logger_writes_once_to_stderr_after_reconfiguration():
    script = """
import logging
import sys

import ansible_content_capture.logger as logger

root_handler = logging.StreamHandler(sys.stderr)
logging.getLogger().addHandler(root_handler)
logging.getLogger().setLevel(logging.WARNING)

logger.set_logger_channel("ansible-scan-test")
logger.set_logger_channel("ansible-scan-test")
logger.set_log_level("warning")
logger.warning("metadata not found: amazon.aws")
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == (
        "WARNING:ansible-scan-test:metadata not found: amazon.aws\n"
    )
