# app/entrypoint.py
import subprocess
import time
import sys
import signal


def run_background(cmd: list):
    """Run a process in background and return the Popen object."""
    return subprocess.Popen(cmd)


def run_foreground(cmd: list):
    """Run a process in the foreground, replacing the current process."""
    os.execvp(cmd[0], cmd)


def main():
    # 1) Redis 서버 실행 (백그라운드)
    redis_proc = run_background([
        "redis-server",
        "--bind", "0.0.0.0",
        "--port", "6379"
    ])
    time.sleep(1)

    # 2) Uvicorn 실행 (백그라운드)
    uvicorn_proc = run_background([
        "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", "8000"
    ])

    # 3) Celery worker 실행 (포그라운드)
    # exec (shell exec) 와 동일하게 현재 프로세스 대체
    os.execvp("celery", [
        "celery",
        "-A", "app.celery_app:celery_app",
        "worker",
        "--loglevel=info"
    ])


if __name__ == "__main__":
    import os
    main()
