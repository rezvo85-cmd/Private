import threading
import time
from ecosystem_store import due_routines, mark_routine_run, notification_add

_started = False
_lock = threading.Lock()


def start(enqueue_callback):
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def loop():
        while True:
            try:
                for row in due_routines():
                    prompt = (row.get("prompt") or "").strip()
                    if prompt:
                        enqueue_callback(
                            row.get("owner") or "legacy",
                            "default",
                            row.get("name") or "Scheduled routine",
                            prompt,
                            50,
                        )
                        notification_add(
                            row.get("owner") or "legacy",
                            f"Routine queued: {row.get('name')}",
                            "RONN added the scheduled routine to your task queue.",
                            "routine",
                        )
                    mark_routine_run(row["id"])
            except Exception:
                pass
            time.sleep(30)

    threading.Thread(target=loop, name="RONN-RoutineScheduler", daemon=True).start()
