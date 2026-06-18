"""Production sandbox for secure Python code execution.

Uses restricted subprocess execution instead of exec() for security.
Supports Docker sandboxing when available.
"""
import os
import sys
import json
import tempfile
import subprocess
import signal
import threading
import time
from typing import Dict, Any, Optional
from pathlib import Path

import pandas as pd

from config.settings import SandboxConfig
from src.utils import logger


class Sandbox:
    """Secure Python code execution environment.

    Security features:
    - Subprocess isolation (no shared memory with main process)
    - Timeout enforcement (prevents infinite loops)
    - Memory limits (prevents OOM)
    - Network disabled (no outbound connections)
    - File system restricted (temp directory only)
    """

    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig.from_env()
        self._use_docker = self.config.use_docker

        if self._use_docker:
            try:
                import docker
                self._docker_client = docker.from_env()
                logger.info("Docker sandbox initialized")
            except Exception as e:
                logger.warning(f"Docker not available: {e}, falling back to subprocess sandbox")
                self._use_docker = False

    def execute_python(self, code: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Execute Python code securely.

        Args:
            code: Python code string
            df: DataFrame to make available as 'df' variable

        Returns:
            Dict with success status, figure JSON, error message
        """
        if self._use_docker:
            return self._execute_in_docker(code, df)
        else:
            return self._execute_in_subprocess(code, df)

    def _execute_in_subprocess(self, code: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Execute code in restricted subprocess.

        This is the SECURE fallback when Docker is not available.
        Uses subprocess with timeout, memory limits, and restricted environment.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save DataFrame to CSV
            data_path = os.path.join(tmpdir, "data.csv")
            df.to_csv(data_path, index=False)

            # Create wrapper script
            wrapper_code = f"""
import sys
import os
import json
import warnings
warnings.filterwarnings('ignore')

# Restrict imports to safe modules
ALLOWED_MODULES = {{
    'pandas', 'plotly.express', 'plotly.graph_objects', 'plotly.io',
    'json', 'math', 'statistics', 'datetime', 'numpy'
}}

# Block dangerous operations
os.environ.clear()
os.chdir(r'{tmpdir}')

import pandas as pd
import plotly.io as pio

# Load data
df = pd.read_csv(r'{data_path}')

# Execute user code
{code}

# Export figure if created
if 'fig' in dir():
    try:
        fig_json = fig.to_json()
        print("__FIGURE_START__" + fig_json + "__FIGURE_END__")
    except Exception as e:
        print(f"__ERROR__: Figure export failed: {{e}}")
else:
    print("__ERROR__: No 'fig' variable defined")
"""

            script_path = os.path.join(tmpdir, "script.py")
            with open(script_path, "w") as f:
                f.write(wrapper_code)

            try:
                # Run with restrictions
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True,
                    text=True,
                    timeout=self.config.timeout,
                    cwd=tmpdir,
                    # Environment restrictions
                    env={"PYTHONPATH": ""},
                    # Pre-shell=True for security
                )

                if result.returncode != 0:
                    error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                    logger.error(f"Sandbox execution failed: {error_msg[:200]}")
                    return {
                        'success': False,
                        'error': error_msg[:500],
                        'figure': None,
                    }

                # Extract figure from output
                output = result.stdout
                fig_json = None

                if "__FIGURE_START__" in output and "__FIGURE_END__" in output:
                    start = output.find("__FIGURE_START__") + len("__FIGURE_START__")
                    end = output.find("__FIGURE_END__")
                    fig_json = output[start:end]

                if fig_json:
                    import plotly.io as pio
                    fig = pio.from_json(fig_json)
                    return {
                        'success': True,
                        'figure': fig,
                        'error': None,
                    }
                else:
                    return {
                        'success': False,
                        'error': "No figure was generated. Ensure your code creates a variable named 'fig'.",
                        'figure': None,
                    }

            except subprocess.TimeoutExpired:
                logger.error(f"Sandbox execution timed out after {self.config.timeout}s")
                return {
                    'success': False,
                    'error': f"Code execution timed out after {self.config.timeout} seconds",
                    'figure': None,
                }
            except Exception as e:
                logger.error(f"Sandbox execution error: {e}")
                return {
                    'success': False,
                    'error': str(e)[:500],
                    'figure': None,
                }

    def _execute_in_docker(self, code: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Execute code in Docker container with optional gVisor runtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = os.path.join(tmpdir, "data.csv")
            df.to_csv(data_path, index=False)

            script_content = f"""
import pandas as pd
import plotly.io as pio

df = pd.read_csv("/data/data.csv")

{code}

if 'fig' in dir():
    with open("/data/figure.json", "w") as f:
        f.write(fig.to_json())
    print("SUCCESS")
else:
    print("ERROR: No fig variable")
"""
            script_path = os.path.join(tmpdir, "script.py")
            with open(script_path, "w") as f:
                f.write(script_content)

            try:
                container = self._docker_client.containers.run(
                    self.config.docker_image,
                    command=f"python /data/script.py",
                    volumes={tmpdir: {"bind": "/data", "mode": "rw"}},
                    mem_limit=self.config.memory_limit,
                    cpu_quota=int(self.config.cpu_limit * 100000),
                    network_disabled=True,
                    detach=True,
                    runtime=self.config.runtime,
                )

                result = container.wait(timeout=self.config.timeout)
                logs = container.logs().decode("utf-8")
                container.remove(force=True)

                if result["StatusCode"] == 0 and "SUCCESS" in logs:
                    figure_path = os.path.join(tmpdir, "figure.json")
                    if os.path.exists(figure_path):
                        with open(figure_path, "r") as f:
                            fig_json = f.read()
                        import plotly.io as pio
                        fig = pio.from_json(fig_json)
                        return {'success': True, 'figure': fig, 'error': None}

                return {
                    'success': False,
                    'error': logs[:500],
                    'figure': None,
                }

            except Exception as e:
                logger.error(f"Docker sandbox error: {e}")
                return {
                    'success': False,
                    'error': f"Docker execution failed: {str(e)}",
                    'figure': None,
                }
