import asyncio
from dataclasses import dataclass
from app.orchestrator.orchestrator import Orchestrator


@dataclass
class Job:
    run_id: str
    action: str = "execute"
    shot_id: str | None = None


class LocalJobRunner:
    def __init__(self, orchestrator: Orchestrator, workers: int = 1):
        self.orchestrator = orchestrator
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.workers = workers
        self.tasks: list[asyncio.Task] = []
        self.cancelled: set[str] = set()
        self.current: dict[asyncio.Task, str] = {}

    async def start(self) -> None:
        if not self.tasks:
            self.tasks = [asyncio.create_task(self._worker(), name=f"fashion-worker-{i}") for i in range(self.workers)]

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

    async def submit(self, run_id: str, action: str = "execute", shot_id: str | None = None) -> None:
        await self.queue.put(Job(run_id, action, shot_id))

    async def cancel(self, run_id: str) -> None:
        self.cancelled.add(run_id)
        active = next((task for task, current_run in self.current.items() if current_run == run_id), None)
        if active is not None:
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
            if active in self.tasks:
                self.tasks.remove(active)
            replacement = asyncio.create_task(self._worker(), name="fashion-worker-replacement")
            self.tasks.append(replacement)
            self.cancelled.discard(run_id)

    async def resume(self, run_id: str) -> None:
        await self.submit(run_id, "execute")

    async def retry_step(self, run_id: str, action: str, shot_id: str | None = None) -> None:
        await self.submit(run_id, action, shot_id)

    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            worker_task = asyncio.current_task()
            self.current[worker_task] = job.run_id
            try:
                if job.run_id in self.cancelled:
                    self.cancelled.remove(job.run_id)
                    continue
                if job.action == "execute":
                    await self.orchestrator.execute(job.run_id)
                elif job.action == "execute_image":
                    await self.orchestrator.execute_image(job.run_id)
                elif job.action == "retry_keyframe":
                    await self.orchestrator.generate_keyframe(job.run_id, job.shot_id, force=True)
                    await self.orchestrator.generate_video(job.run_id, job.shot_id, force=True)
                    await self.orchestrator.compose(job.run_id)
                elif job.action == "retry_video":
                    await self.orchestrator.generate_video(job.run_id, job.shot_id, force=True)
                    await self.orchestrator.compose(job.run_id)
                elif job.action == "compose":
                    await self.orchestrator.compose(job.run_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                try:
                    state = self.orchestrator.runs.get(job.run_id)
                    self.orchestrator.runs.update(job.run_id, "FAILED", state.progress, "Queued action failed",
                                                  error=f"{type(exc).__name__}: {exc}")
                    self.orchestrator.runs.event(job.run_id, "RUN_FAILED", error=f"{type(exc).__name__}: {exc}")
                except KeyError:
                    pass
            finally:
                self.current.pop(worker_task, None)
                self.queue.task_done()
