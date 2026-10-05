import asyncio
import threading


class AsyncRunner:
    def __init__(self):
        self.loop = None
        self.thread = None

    def start(self):
        if self.loop:
            return
        self.loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()

        self.thread = threading.Thread(target=_run, daemon=True, name="async-runner")
        self.thread.start()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


runner = AsyncRunner()
