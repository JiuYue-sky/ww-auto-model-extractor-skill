"""Watchdog subprocess manager with hard timeout, I/O heartbeat, zombie tree cleanup, and retries."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence


@dataclass
class WatchdogResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_s: float
    attempts: int
    timed_out: bool = False
    idle_killed: bool = False
    kill_reason: str = ""
    killed_pids: List[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.idle_killed

    def to_dict(self) -> Dict[str, object]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "elapsed_s": round(self.elapsed_s, 3),
            "attempts": self.attempts,
            "ok": self.ok,
            "timed_out": self.timed_out,
            "idle_killed": self.idle_killed,
            "kill_reason": self.kill_reason,
            "killed_pids": self.killed_pids,
        }


def _dir_footprint(watch_dir: Optional[Path]) -> tuple[int, int]:
    """Return (file_count, total_bytes) inside watch_dir safely."""
    if watch_dir is None or not watch_dir.exists():
        return (0, 0)
    count = 0
    total_bytes = 0
    try:
        for root, _dirs, files in os.walk(watch_dir):
            for fn in files:
                count += 1
                try:
                    total_bytes += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    except OSError:
        pass
    return (count, total_bytes)


def kill_process_tree(pid: int) -> bool:
    """Force-kill a process and all descendant children across Windows/POSIX."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            res = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False
    else:
        import signal

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return True
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
                return True
            except Exception:
                return False


def run_watched(
    cmd: Sequence[str],
    *,
    cwd: Optional[str | Path] = None,
    env: Optional[Dict[str, str]] = None,
    hard_timeout_s: float = 240.0,
    io_idle_timeout_s: float = 60.0,
    watch_dir: Optional[str | Path] = None,
    max_retries: int = 2,
    poll_interval_s: float = 0.5,
    label: str = "process",
    on_log: Optional[Callable[[str], None]] = None,
) -> WatchdogResult:
    """Execute an external process guarded by hard timeout and I/O + output heartbeat."""
    cmd_list = [str(c) for c in cmd]
    watch_path = Path(watch_dir) if watch_dir is not None else None
    total_start = time.monotonic()
    last_result: Optional[WatchdogResult] = None
    killed_pids: List[int] = []

    for attempt in range(1, max(1, max_retries) + 1):
        if on_log:
            on_log(f"[watchdog:{label}] attempt {attempt}/{max(1, max_retries)}: {' '.join(cmd_list[:4])} ...")

        creationflags = 0
        popen_kwargs: Dict[str, object] = {}
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            popen_kwargs["creationflags"] = creationflags
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            cmd_list,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            bufsize=0,
            **popen_kwargs,
        )

        stdout_chunks: List[bytes] = []
        stderr_chunks: List[bytes] = []
        last_activity = [time.monotonic()]
        lock = threading.Lock()

        def _reader(stream, sink: List[bytes]) -> None:
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    with lock:
                        sink.append(chunk)
                        last_activity[0] = time.monotonic()
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        t_out = threading.Thread(target=_reader, args=(proc.stdout, stdout_chunks), daemon=True)
        t_err = threading.Thread(target=_reader, args=(proc.stderr, stderr_chunks), daemon=True)
        t_out.start()
        t_err.start()

        start_t = time.monotonic()
        last_fp = _dir_footprint(watch_path)
        timed_out = False
        idle_killed = False
        kill_reason = ""

        while proc.poll() is None:
            now = time.monotonic()
            if watch_path is not None:
                cur_fp = _dir_footprint(watch_path)
                if cur_fp != last_fp:
                    last_fp = cur_fp
                    with lock:
                        last_activity[0] = now

            with lock:
                idle_s = now - last_activity[0]
            elapsed_attempt = now - start_t

            if hard_timeout_s > 0 and elapsed_attempt > hard_timeout_s:
                timed_out = True
                kill_reason = f"hard timeout exceeded ({elapsed_attempt:.1f}s > {hard_timeout_s:.1f}s)"
                if on_log:
                    on_log(f"[watchdog:{label}] KILL pid={proc.pid}: {kill_reason}")
                killed_pids.append(proc.pid)
                kill_process_tree(proc.pid)
                break

            if io_idle_timeout_s > 0 and idle_s > io_idle_timeout_s:
                idle_killed = True
                kill_reason = f"I/O heartbeat idle timeout ({idle_s:.1f}s > {io_idle_timeout_s:.1f}s)"
                if on_log:
                    on_log(f"[watchdog:{label}] KILL pid={proc.pid}: {kill_reason}")
                killed_pids.append(proc.pid)
                kill_process_tree(proc.pid)
                break

            time.sleep(min(poll_interval_s, 0.25))

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            killed_pids.append(proc.pid)
            kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

        t_out.join(timeout=5)
        t_err.join(timeout=5)

        stdout_text = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        last_result = WatchdogResult(
            command=cmd_list,
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_text,
            stderr=stderr_text,
            elapsed_s=time.monotonic() - total_start,
            attempts=attempt,
            timed_out=timed_out,
            idle_killed=idle_killed,
            kill_reason=kill_reason,
            killed_pids=list(killed_pids),
        )

        # Retry ONLY on hang/timeout/idle kill, NOT on deterministic non-zero application exit
        if not (timed_out or idle_killed):
            return last_result

    assert last_result is not None
    return last_result
