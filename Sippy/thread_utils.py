import threading

class ThreadedLoop:
    """Run a target function repeatedly in a daemon thread until stopped."""
    def __init__(self, target, *args, **kwargs):
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            args=(target,) + args,
            kwargs=kwargs,
            daemon=True,
        )
        self._target = target
        self._args = args
        self._kwargs = kwargs

    def _run(self, target, *args, **kwargs):
        while not self._stop_event.is_set():
            target(*args, **kwargs)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=2.0)
