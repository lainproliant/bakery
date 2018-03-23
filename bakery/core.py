#--------------------------------------------------------------------
# bakery: Dependency-based build system built atop a Xeno injector.
#
# Author: Lain Supe (supelee)
# Date: Thursday March 23 2017,
#       Tuesday January 23 2018
#--------------------------------------------------------------------
__all__ = ['singleton',
           'provide',
           'inject',
           'named',
           'alias',
           'namespace',
           'const',
           'using',
           'compose',
           'BuildError',
           'TargetConflictError',
           'Build',
           'build',
           'target',
           'default']

#--------------------------------------------------------------------
import ansilog
import argparse
import asyncio
import glob
import hashlib
import inspect
import json
import logging
import multiprocessing
import os
import shutil
import sys
import uuid
import xeno

from ansilog import fg, bg

#--------------------------------------------------------------------
CHECKSUM_CACHE_FILENAME = 'bakery-check.json'
CPU_CORES = multiprocessing.cpu_count()
DEBUG = 'BAKERY_DEBUG' in os.environ

#--------------------------------------------------------------------
singleton = xeno.singleton
provide = xeno.provide
inject = xeno.inject
named = xeno.named
alias = xeno.alias
namespace = xeno.namespace
const = xeno.const
using = xeno.using
method_attr = xeno.MethodAttributes.add

#--------------------------------------------------------------------
class BuildError(Exception):
    pass

#--------------------------------------------------------------------
class TargetConflictError(BuildError):
    def __init__(self, message, targets):
        super().__init__('%s. (%s)' % (message, ', '.join(targets)))

#--------------------------------------------------------------------
class JobError(BuildError):
    pass

#--------------------------------------------------------------------
class SubprocessError(JobError):
    def __init__(self, cmd_line, output, err_output, returncode):
        super().__init__('Failed to execute command: %s' % ' '.join(cmd_line))
        self.cmd_line = cmd_line
        self.output = output
        self.err_output = err_output
        self.returncode = returncode

#--------------------------------------------------------------------
class EvaluationError(BuildError):
    pass

#--------------------------------------------------------------------
class InternalError(Exception):
    pass

#--------------------------------------------------------------------
def get_logger(name = 'bakery'):
    logger = ansilog.getLogger(name)
    if DEBUG:
        ansilog.handler.setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    return logger

#--------------------------------------------------------------------
def compose(*functions):
    def composition(arg):
        v = arg
        for f in functions:
            v = f(v)
        return v
    return composition

#--------------------------------------------------------------------
def degenerate(arg):
    if inspect.isgenerator(arg):
        return list(arg)
    else:
        return arg

#--------------------------------------------------------------------
def flat_map(arg, f = lambda x: x):
    if isinstance(arg, (set, list, tuple)):
        results = []
        for x in arg:
            results.extend(flat_map(x, f))
        return results

    elif isinstance(arg, dict):
        return flat_map(list(arg.values()), f)

    else:
        return [f(arg)]

#--------------------------------------------------------------------
def is_iterable(x):
    """
    Determine if the given object is an iterable.
    Specificially if it is a list, tuple, range, or generator.
    """
    return isinstance(x, (list, tuple, range)) or inspect.isgenerator(x)

#--------------------------------------------------------------------
def make_iterable(x, ctor = lambda x: list([x])):
    """
    Wrap the given value in an iterable, or return it if it is
    already an iterable.  Returns None if the given value is None.
    """
    if x is None:
        return None
    return x if is_iterable(x) else ctor(x)

#--------------------------------------------------------------------
def generate(x):
    """
    Converts the object to a generator.
    If the object is iterable, it yields each entry of it.
    """
    if not x: 
        yield
    if is_iterable(x):
        for y in x:
            yield y
        else:
            yield x

#--------------------------------------------------------------------
def create_job_id(name = None):
    """
    Create a short, unique job id to associate with some work.
    """

    return str(uuid.uuid4())[:8] + ('-' + name if name is not None else '')

#--------------------------------------------------------------------
def build_eval_deck(injector, targets):
    eval_deck = []
    dep_graph = injector.get_dependency_graph(*targets)
    todo_set = set(dep_graph.keys())
    processed_set = set()

    while todo_set:
        card_set = set()
        for target in todo_set:
            deps = dep_graph[target]
            if all(x in processed_set for x in deps):
                card_set.add(target)
        if not card_set:
            # This should never happen because of the dependency cycle checks in xeno, but just in case...
            raise EvaluationError('Unable to resolve remaining dependencies for build deck: %s' % repr(todo_set))
        eval_deck.append(card_set)
        processed_set |= card_set
        todo_set ^= card_set
    return eval_deck

#--------------------------------------------------------------------
class JobLog:
    def __init__(self, log, job_id = None, name = None):
        self.log = log
        self.name = name
        self.job_id = job_id or create_job_id(name = name)
    
    def get_name(self):
        if self.name is not None:
            return self.name
        else:
            return 'job %s' % self.job_id

    def print(self, msg, *args, **kwargs):
        prefix = fg.blue('[%s]' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        prefix = fg.yellow('[%s]' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        prefix = fg.red('[%s]' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)

    def trace(self, msg, *args, **kwargs):
        prefix = fg.green('[%s]' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)

    def fail(self, msg = 'FAILED', *args, **kwargs):
        self.log.error(fg.red('[%s] %s' % (self.get_name(), msg)), *args, **kwargs)

    def finish(self, msg = 'Finished.', *args, **kwargs):
        prefix = fg.red('[%s] <-- ' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)

#--------------------------------------------------------------------
class File:
    """
        A class of static utility methods for operating on filenames.
    """
    @staticmethod
    def glob(pattern):
        return glob.glob(pattern)

    @staticmethod
    def ext(filename, ext):
        return '.'.join([os.path.splitext(filename)[0], ext])

    @staticmethod
    def remove(file, log = None):
        if os.path.isdir(file):
            if log:
                log.trace('Removing directory "%s"...' % file)
            shutil.rmtree(file)
        elif os.path.exists(file):
            if log:
                log.trace('Removing file "%s"...' % file)
            os.remove(file)

#--------------------------------------------------------------------
class Config:
    """
        Describes the configuration options that can be passed to the
        'bake' command line tool.
    """
    def __init__(self):
        self.targets = []
        self.bakefile = 'Bakefile.py'
        self.clean = False

    def get_arg_parser(self):
        parser = argparse.ArgumentParser(description = 'Build targets in bakefiles.')
        parser.add_argument('targets', metavar='TARGET', nargs='*', default=None)
        parser.add_argument('-b', '--bakefile')
        parser.add_argument('-c', '--clean', action='store_true')
        return parser

    def parse_known_args(self):
        self.get_arg_parser().parse_known_args(namespace = self)
        return self

    def parse_args(self):
        self.get_arg_parser().parse_args(namespace = self)
        return self

#--------------------------------------------------------------------
@xeno.namespace('bakery')
class Build:
    build_count = 0
    critical = False
    interactive = False
    config = Config()

    def __init__(self, config = None):
        if config is None:
            config = Build.config
        self.temp_files = []
        self.log = get_logger("bakery.Build")
        self.config = config
        self.shell_limiter = asyncio.BoundedSemaphore(CPU_CORES)

    def target(self, f):
        @singleton
        @xeno.MethodAttributes.wraps(f)
        @xeno.MethodAttributes.add('bakery-target')
        async def wrapper(*args, **kwargs):
            self.log.info("Invoking target '%s'..." % target)
            return await xeno.async_wrap(f)(*args, **kwargs)
        return wrapper

    def default(self, f):
        return xeno.MethodAttributes.add('bakery-default')(self.target(f))
    
    @xeno.provide
    @xeno.singleton
    def log(self):
        return self.log

    @xeno.provide
    def cleaning(self):
        return self.config.clean
    
    @xeno.provide
    @xeno.singleton
    def loop(self):
        return asyncio.get_event_loop()
    
    def build(self, *module_classes, targets = []):
        Build.build_count += 1
        modules = [module_class() for module_class in module_classes]
        injector = xeno.Injector(self, *modules)

        if Build.interactive and not targets:
            targets = self.config.targets
        if not targets:
            targets = [self._find_default_target(injector)]
        
        valid_targets = set(self._find_targets(injector))
        for target in targets:
            if not target in valid_targets:
                raise BuildError('Unknown target: %s' % target)

        setup_methods = self._find_setup_methods(injector)
        for setup_method_name in setup_methods:
            injector.require(setup_method_name)
            
        result = [injector.require(target) for target in targets]
        self._clean_temp_files()
        return result
    
    def recipe(self, *targets, check = None, temp = None):
        targets = set(targets)
        check = make_iterable(check, lambda x: set([x])) or set()
        temp = make_iterable(temp, lambda x: set([x])) or set()
        outputs = targets | temp

        def decorator(f):
            attrs = xeno.MethodAttributes.for_method(f)
            name = attrs.get('name', 'recipe')
            signature = inspect.signature(f)
            @xeno.MethodAttributes.wraps(f)
            async def wrapper(*args, **kwargs):
                log_param = None
                for param_name, param in signature.parameters.items():
                    if param.annotation == 'log':
                        log_param = param_name
                        kwargs[param_name] = self.log

                bound_params = signature.bind(*args, **kwargs)
                target_params = [bound_params.arguments[k] for k in targets]
                target_files = set(flat_map(target_params))
                check_files = set(flat_map([bound_params.arguments[k] for k in check]))
                temp_files = set(flat_map([bound_params.arguments[k] for k in temp]))
                output_files = target_files | temp_files
                log = None
                long_name = name
                if check_files or output_files or temp_files:
                    long_name = '%s %s' % (name, ','.join(check_files or output_files or temp_files))
                log = JobLog(self.log, name = long_name)

                if log_param:
                    kwargs[log_param] = log
                
                def outputs_exist():
                    return all(os.path.exists(file) for file in output_files)
                
                def check_mtimes():
                    return [os.path.getmtime(file) for file in check_files if os.path.exists(file)]

                def output_mtimes():
                    return [os.path.getmtime(file) for file in output_files if os.path.exists(file)]

                def outputs_up_to_date():
                    return (outputs and outputs_exist() and ((check_mtimes() and output_mtimes()) and (max(check_mtimes()) <= max(output_mtimes())) or not check_files))
            
                def clean():
                    if outputs_exist():
                        for file in output_files:
                            File.remove(file, log = log)
                    else:
                        log.trace('There is nothing to clean.')
                    return coalesce_default_outputs()

                def coalesce_default_outputs():
                    if len(targets) == 1 and len(target_params) == 1 and not is_iterable(target_params[0]):
                        return target_params[0]
                    else:
                        return output_files

                async def build_recipe():
                    result = await xeno.async_wrap(f, *args, **kwargs)
                    self.temp_files.extend(temp_files)
                    if not outputs_up_to_date():
                        raise BuildError('Recipe "%s %s" failed to create the prescribed output: %s' % (name, ', '.join(check_files), ', '.join(output_files)))
                    return result

                if self.config.clean:
                    return clean()
                elif not outputs_up_to_date():
                    return await build_recipe()
                else:
                    log.trace('There is nothing to do.')
                    return coalesce_default_outputs()
            return wrapper
        return decorator

    async def shell(self, *args, stdout = asyncio.subprocess.PIPE, stderr = asyncio.subprocess.PIPE, name = None, log = None, **kwargs):
        # Limit concurrency in shell calls to the number of cores on the system, so that we 
        # do not end up spawning more jobs from coroutines than the system has processors.
        await self.shell_limiter.acquire()
        
        try:
            if name is None:
                name = 'sh'
            if log is None:
                log = JobLog(self.log, name = name)
                
            cmd_line = compose(
                    lambda x: flat_map(x, degenerate),
                    lambda x: flat_map(x, str))(args)

            log.trace(' '.join(cmd_line))

            output = []
            err_output = []
            proc = await asyncio.create_subprocess_exec(*cmd_line, stdout = stdout, stderr = stderr, **kwargs)
            readline_tasks = {
                asyncio.Task(proc.stdout.readline()): (
                    output, proc.stdout, lambda x: log.print(x)),
                asyncio.Task(proc.stderr.readline()): (
                    err_output, proc.stderr, lambda x: log.error(x))
            }
            while readline_tasks:
                done, pending = await asyncio.wait(readline_tasks, return_when = asyncio.FIRST_COMPLETED)
                for future in done:
                    buf, stream, display = readline_tasks.pop(future)
                    line = future.result()
                    if line: # if not EOF
                        line = line.decode('utf-8').strip()
                        buf.append(line)
                        display(line)
                        readline_tasks[asyncio.Task(stream.readline())] = buf, stream, display
            
            await proc.wait()
            if proc.returncode != 0:
                raise SubprocessError(cmd_line, output, err_output, proc.returncode)
            else:
                return output
        finally:
            self.shell_limiter.release()

    def __call__(self, *modules):
        self.build(*modules)
    
    def _clean_temp_files(self):
        log = JobLog(self.log, name = '<cleanup>') 
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                File.remove(temp_file, log = log)
    
    def _find_setup_methods(self, injector):
        return [r[0] for r in injector.scan_resources(lambda name, attr: attr.check('bakery-setup'))]

    def _find_targets(self, injector):
        return [r[0] for r in injector.scan_resources(lambda name, attr: attr.check('bakery-target'))]

    def _find_default_target(self, injector):
        results = list(injector.scan_resources(lambda name, attr: attr.check('bakery-default')))
        if not results:
            results = list(injector.scan_resources(lambda name, attr: attr.check('bakery-target')))
        elif len(results) > 1:
            raise TargetConflictError('Multiple default targets defined.', results)
        return results[0][0] if results else None

#--------------------------------------------------------------------
build = Build()
shell = lambda *args, **kwargs: build.shell(*args, **kwargs)
setup = compose(singleton, method_attr('bakery-setup'))
target = compose(asyncio.coroutine, singleton, method_attr('bakery-target'))
default = compose(target, method_attr('bakery-default'))
gather = asyncio.gather
recipe = build.recipe

#--------------------------------------------------------------------
PREAMBLE = """from bakery import *
"""

#--------------------------------------------------------------------
def main():
    """
        The main entry point of the 'bake' command line tool.
        Prepends the PREAMBLE source to the contents of 'Bakefile.py'
        in the current directory, or the file specified by the '-b'
        command line switch, and executes the resulting script.
    """
    log = get_logger("bakery.main")
    Build.config.parse_known_args()
    Build.config.bakefile = Build.config.bakefile
    Build.interactive = True
    if not os.path.exists(Build.config.bakefile):
        log.critical("No '%s' in the current directory." % Build.config.bakefile)
        sys.exit(1)

    bake_instructions = PREAMBLE + open(Build.config.bakefile).read()

    try:
        exec(bake_instructions, globals())
        log.info(fg.bright.green('BUILD SUCCEEDED'))
    except Exception as e:
        Build.critical = True
        log.error(str(e))
        if DEBUG:
            log.exception("Exception details follow.")
        log.info(fg.bright.red('BUILD FAILED'))

    if Build.build_count == 0 and not Build.critical:
        log.warn(ansilog.Node.list("Nothing was built, did you forget to decorate your module with ", fg.bright.yellow("@build"), "?"))

    sys.exit(0)

#--------------------------------------------------------------------
if __name__ == '__main__':
    main()
