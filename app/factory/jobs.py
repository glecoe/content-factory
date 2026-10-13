"""Background jobs with a log the UI can poll."""
from __future__ import annotations
import threading
import time
import uuid

_jobs = {}
_lock = threading.Lock()


class Job:
    def __init__(self, title):
        self.id = uuid.uuid4().hex[:10]
        self.title = title
        self.status = "running"      # running | done | error
        self.log = []
        self.progress = 0.0
        self.result = None
        self.started = time.time()

    def say(self, msg):
        from .safety import clean_text
        self.log.append(time.strftime("%H:%M:%S ") + clean_text(msg))

    def to_dict(self):
        return {"id": self.id, "title": self.title, "status": self.status, "log": self.log[-80:],
                "progress": round(self.progress, 2), "result": self.result,
                "elapsed": int(time.time() - self.started)}


def start(title, fn, *args, **kwargs) -> Job:
    job = Job(title)
    with _lock:
        _jobs[job.id] = job

    def runner():
        try:
            job.result = fn(job, *args, **kwargs)
            job.status = "done"
            job.progress = 1.0
            job.say("Готово.")
        except Exception as e:  # причина — в интерфейс (без путей), подробности — в терминал
            from .safety import public_error
            job.status = "error"
            job.say(f"Ошибка: {public_error(e)}")
    threading.Thread(target=runner, daemon=True).start()
    return job


def get(job_id):
    j = _jobs.get(job_id)
    return j.to_dict() if j else None


def active():
    return [j.to_dict() for j in _jobs.values() if j.status == "running"]
