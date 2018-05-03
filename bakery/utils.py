import ansilog
import glob
import inspect
import logging
import multiprocessing
import os
import shutil
import uuid

from ansilog import fg, bg

#--------------------------------------------------------------------
CPU_CORES = multiprocessing.cpu_count()
DEBUG = 'BAKERY_DEBUG' in os.environ

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
        prefix = fg.blue('[%s]' % self.get_name())
        self.log.info(ansilog.Node.list(prefix, ' ', msg), *args, **kwargs)

#--------------------------------------------------------------------
def remove(file, log = None):
    if os.path.isdir(file):
        if log:
            log.trace('Removing directory "%s"...' % file)
        shutil.rmtree(file)
    elif os.path.exists(file):
        if log:
            log.trace('Removing file "%s"...' % file)
        os.remove(file)

