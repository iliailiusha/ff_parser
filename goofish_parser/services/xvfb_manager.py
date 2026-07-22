import asyncio
import logging
import os
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DISPLAY = ":99"
XVRF_RESOLUTION = "1920x1080x24"


class XvfbManager:
    def __init__(self, display: str = DEFAULT_DISPLAY) -> None:
        self._display = display
        self._process: Optional[subprocess.Popen] = None

    @property
    def display(self) -> str:
        return self._display

    async def start(self, timeout: int = 10) -> bool:
        if self._process is not None:
            return True

        existing = self._find_existing_xvfb()
        if existing:
            logger.info("Found existing Xvfb on display %s (PID %d)", self._display, existing.pid)
            self._process = existing
            os.environ["DISPLAY"] = self._display
            return True

        logger.info("Starting Xvfb on display %s...", self._display)
        try:
            self._process = subprocess.Popen(
                ["Xvfb", self._display, "-screen", "0", XVRF_RESOLUTION, "-ac"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.environ["DISPLAY"] = self._display

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                rc = self._process.poll()
                if rc is not None:
                    logger.error("Xvfb exited prematurely with code %d", rc)
                    self._process = None
                    return False
                try:
                    subprocess.run(
                        ["xdpyinfo", "-display", self._display],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                    )
                    logger.info("Xvfb ready on display %s", self._display)
                    return True
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                    await asyncio.sleep(0.5)

            logger.error("Xvfb failed to start within %ds", timeout)
            self.stop()
            return False

        except FileNotFoundError:
            logger.error("Xvfb not found. Install: apt-get install xvfb")
            return False
        except Exception as e:
            logger.exception("Failed to start Xvfb: %s", e)
            self.stop()
            return False

    def stop(self) -> None:
        if self._process is not None:
            logger.info("Stopping Xvfb (PID %d)...", self._process.pid)
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Xvfb did not terminate, killing...")
                self._process.kill()
                self._process.wait(timeout=3)
            except Exception as e:
                logger.error("Error stopping Xvfb: %s", e)
            self._process = None
        if "DISPLAY" in os.environ:
            del os.environ["DISPLAY"]

    def _find_existing_xvfb(self) -> Optional[subprocess.Popen]:
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"Xvfb.*{self._display}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                pid = int(result.stdout.strip().split("\n")[0])
                logger.info("Existing Xvfb process found: PID %d", pid)
                return subprocess.Popen(["true"])  # placeholder
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass
        return None

    def is_running(self) -> bool:
        if self._process is None:
            return False
        rc = self._process.poll()
        return rc is None


_xvfb: Optional[XvfbManager] = None


async def get_xvfb() -> XvfbManager:
    global _xvfb
    if _xvfb is None:
        _xvfb = XvfbManager()
        started = await _xvfb.start()
        if not started:
            logger.warning("Xvfb failed to start, trying without virtual display")
    return _xvfb


async def stop_xvfb() -> None:
    global _xvfb
    if _xvfb is not None:
        _xvfb.stop()
        _xvfb = None
