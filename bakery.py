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
import asyncio
import glob
import hashlib
import inspect
import json
import logging
import os
import shutil
import sys
import uuid
import xeno

from ansilog import fg, bg

#--------------------------------------------------------------------
CHECKSUM_CACHE_FILENAME = 'bakery-check.json'

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
def get_logger(name = 'bakery'):
    logger = ansilog.getLogger(name)
    if 'BAKERY_DEBUG' in os.environ:
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

    def start(self, msg = 'Started.', *args, **kwargs):
        prefix = fg.green('[%s] --> ' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)

    def print(self, msg, *args, **kwargs):
        prefix = fg.blue('[%s]\t ' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        prefix = fg.yellow('[%s] ' % self.get_name()) + bg.yellow(fg.black('/!\\')) + ' '
        self.log.warning(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        prefix = fg.red('[%s] ' % self.get_name())
        self.log.error(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)

    def trace(self, msg, *args, **kwargs):
        prefix = fg.green('[%s] ' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)

    def fail(self, msg = 'FAILED', *args, **kwargs):
        self.log.error(fg.red('[%s] %s' % (self.get_name(), msg)), *args, **kwargs)

    def finish(self, msg = 'Finished.', *args, **kwargs):
        prefix = fg.red('[%s] <-- ' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)

#--------------------------------------------------------------------
class File:
    @staticmethod
    def glob(pattern):
        return glob.glob(pattern)

#--------------------------------------------------------------------
@xeno.namespace('bakery')
class Build:
    build_count = 0
    critical = False

    def __init__(self):
        self.cleaning = False
        self.temp_objects = []
        self.log = get_logger("bakery.Build")

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

    @xeno.singleton
    def log(self):
        return self.log
    
    def build(self, *module_classes, targets = []):
        Build.build_count += 1
        modules = [module_class() for module_class in module_classes]
        injector = xeno.Injector(self, *modules)

        if not targets:
            targets = [self._find_default_target(injector)]

        eval_deck = build_eval_deck(injector, targets)
        loop = asyncio.get_event_loop()
        
        for card in eval_deck:
            loop.run_until_complete(self._evaluate_card(injector, card))
        
        return [injector.require(target) for target in targets]
    
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
                target_files = set(flat_map([bound_params.arguments[k] for k in targets]))
                check_files = set(flat_map([bound_params.arguments[k] for k in check]))
                temp_files = set(flat_map([bound_params.arguments[k] for k in temp]))
                output_files = target_files | temp_files
                check_mtimes = [os.path.getmtime(file) for file in check_files
                        if os.path.exists(file)]
                output_mtimes = [os.path.getmtime(file) for file in output_files
                        if os.path.exists(file)]
                outputs_exist = all(os.path.exists(file) for file in output_files)
                log = JobLog(self.log, name = '%s %s' % (name, ','.join(output_files)))
                if log_param:
                    kwargs[log_param] = log

                def clean():
                    log.start('Cleaning...')
                    if outputs_exist:
                        for file in output_files:
                            if os.path.isdir(file):
                                log.trace('Removing directory "%s"...' % file)
                                shutil.rmtree(file)
                            elif os.path.exists(file):
                                log.trace('Removing file "%s"...' % file)
                                os.remove(file)
                    return outputs

                async def build_recipe():
                    return await xeno.async_wrap(f, *args, **kwargs)

                if self.cleaning:
                    return clean()
                elif (outputs_exist and (check_mtimes and output_mtimes) and max(check_mtimes) > max(output_mtimes)) or not outputs_exist:
                    return await build_recipe()
                else:
                    log.trace('There is nothing to do.')
                    return output_files
            return wrapper
        return decorator

    async def _dispatch_target(self, injector, target, v):
        loop = asyncio.get_event_loop()
        self.log.debug('Dispatching target "%s" result for build...' % target)
        await injector.provide_async(target, v, is_singleton = True)

    async def _dispatch_list_target(self, injector, target, l, offset, v):
        loop = asyncio.get_event_loop()
        l[offset] = v
        await self._dispatch_target(injector, target, l)

    async def _evaluate_card(self, injector, card):
        coro_map = {}
        coro_value_list_map = {}
        coro_value_list_target_set = set()
        coro_lambdas = []
        loop = asyncio.get_event_loop()
        
        self.log.debug('Evaluating card: %s' % repr(card))

        for target in card:
            resource = await injector.require_async(target)
            if asyncio.iscoroutine(resource):
                coro_map[target] = resource
            elif is_iterable(resource):
                resource = degenerate(resource)
                # It might contain coroutines, let's scan it later.
                coro_value_list_map[target] = resource
        
        waiting_futures = []
        for target, coro in coro_map.items():
            coro_lambdas.append((coro, lambda v: waiting_futures.append(
                asyncio.ensure_future(self._dispatch_target(injector, target, v)))))

        for target, coro_value_list in coro_value_list_map.items():
            coro_indexes = filter(lambda t: asyncio.iscoroutine(t[1]), enumerate(coro_value_list))
            if coro_indexes:
                coro_value_list_target_set.add(target)
                for x, coro in coro_indexes:
                    coro_lambdas.append((coro, lambda v: waiting_futures.append(
                        self._dispatch_list_target(injector, target, coro_value_list, x, v))))

        dispatch_lambdas = await asyncio.gather(*(xeno.async_map(l, coro) for coro, l in coro_lambdas))
        for l, v in dispatch_lambdas:
            l(v)

        await asyncio.gather(*waiting_futures)
        self.log.debug('Finished evaluting card: %s' % repr(card))

    async def shell(self, *args, stdout = asyncio.subprocess.PIPE, stderr = asyncio.subprocess.PIPE, name = None, log = None, **kwargs):
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

    def __call__(self, *modules):
        self.build(*modules)
    
    def _clean_temp_objects(self):
        for temp_obj in self.temp_objects:
            temp_obj.clean()

    def _find_default_target(self, injector):
        results = list(injector.scan_resources(lambda f, attr: attr.check('bakery-default')))
        if not results:
            results = list(injector.scan_resources(lambda f, attr: attr.check('bakery-target')))
        elif len(results) > 1:
            raise TargetConflictError('Multiple default targets defined.', results)
        return results[0][0] if results else None

#--------------------------------------------------------------------
build = Build()
shell = lambda *args, **kwargs: build.shell(*args, **kwargs)
target = compose(asyncio.coroutine, singleton, method_attr('bakery-target'))
default = compose(target, method_attr('bakery-default'))
gather = asyncio.gather
recipe = build.recipe

#--------------------------------------------------------------------
BAKEFILE_NAME = 'Bakefile.py'
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
    bakefile_name = BAKEFILE_NAME
    if '-b' in sys.argv and len(sys.argv) > sys.argv.index('-b'):
        bakefile_name = sys.argv[sys.argv.index('-b') + 1]
    if not os.path.exists(bakefile_name):
        log.critical("No '%s' in the current directory." % bakefile_name)
        sys.exit(1)

    bake_instructions = PREAMBLE + open(bakefile_name).read()

    try:
        exec(bake_instructions, globals())
        log.info(fg.bright.green('BUILD SUCCEEDED'))
    except Exception as e:
        Build.critical = True
        log.error('An exception occurred during the build.')
        log.exception("Exception details follow.")
        log.error('BUILD FAILED')

    if Build.build_count == 0 and not Build.critical:
        log.warn(ansilog.Node.list("Nothing was built, did you forget to decorate your module with ", fg.bright.yellow("@build"), "?"))

    sys.exit(0)

#--------------------------------------------------------------------
if __name__ == '__main__':
    main()
