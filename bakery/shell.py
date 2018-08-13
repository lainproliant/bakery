import asyncio
import os

from .utils import *
from .exceptions import *

# --------------------------------------------------------------------
class Shell:
    limiter = asyncio.BoundedSemaphore(CPU_CORES)

    def __init__(self, config=None):
        self.log = get_logger("bakery.shell.Shell")
        self.env = {}

    def derive(self):
        derived_shell = Shell()
        derived_Shell.env.update(self.env)
        return derived_shell

    async def __call__(
        self,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        name=None,
        log=None,
        **kwargs
    ):
        # Limit concurrency in shell calls to the number of cores on the system, so that we
        # do not end up spawning more jobs from coroutines than the system has processors.
        await Shell.limiter.acquire()

        try:
            if name is None:
                name = "#"
            if log is None:
                log = JobLog(self.log, name=name)

            cmd_line = compose(
                lambda x: flat_map(x, degenerate), lambda x: flat_map(x, str)
            )(args)

            log.trace(" ".join(cmd_line))

            output = []
            err_output = []
            env = os.environ.copy()
            env.update(self.env)
            proc = await asyncio.create_subprocess_exec(
                *cmd_line, stdout=stdout, stderr=stderr, env=env, **kwargs
            )
            readline_tasks = {
                asyncio.Task(proc.stdout.readline()): (
                    output,
                    proc.stdout,
                    lambda x: log.print(x),
                ),
                asyncio.Task(proc.stderr.readline()): (
                    err_output,
                    proc.stderr,
                    lambda x: log.error(x),
                ),
            }
            while readline_tasks:
                done, pending = await asyncio.wait(
                    readline_tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for future in done:
                    buf, stream, display = readline_tasks.pop(future)
                    line = future.result()
                    if line:  # if not EOF
                        line = line.decode("utf-8").strip()
                        buf.append(line)
                        display(line)
                        readline_tasks[asyncio.Task(stream.readline())] = (
                            buf,
                            stream,
                            display,
                        )

            await proc.wait()
            if proc.returncode != 0:
                raise SubprocessError(cmd_line, output, err_output, proc.returncode)
            else:
                return output
        finally:
            Shell.limiter.release()
