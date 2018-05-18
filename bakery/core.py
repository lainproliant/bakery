#--------------------------------------------------------------------
# bakery: Dependency-based build system built atop a Xeno injector.
#
# Author: Lain Supe (supelee)
# Date: Thursday March 23 2017,
#       Tuesday January 23 2018
#--------------------------------------------------------------------
import asyncio
import xeno

from .utils import *
from .exceptions import *
from .shell import Shell
from .recipes.core import Recipes

#--------------------------------------------------------------------
@xeno.namespace('bakery')
class Build:
    build_count = 0

    def __init__(self):
        self.log = get_logger("bakery.Build")
        self.coro_results = {}
        self.scanned_iterables = set()
        self.interactive = False
        self.targets = []
        self.critical = False
        self.injector = None
        self.built_temp_resources = []

    def temp(self, f):
        @xeno.MethodAttributes.wraps(f)
        async def wrapper(*args, **kwargs):
            attrs = xeno.MethodAttributes.for_method(wrapper)
            result = await xeno.async_wrap(f, *args, **kwargs)
            self.built_temp_resources.append(attrs.get('resource-name'))
            return result
        return wrapper

    def noclean(self, f):
        @xeno.MethodAttributes.wraps(f)
        async def wrapper(*args, **kwargs):
            if self.cleaning():
                return None
            else:
                return await xeno.async_wrap(f, *args, **kwargs)
        return wrapper

    @xeno.provide
    @xeno.singleton
    def log(self):
        return self.log

    @xeno.provide
    def cleaning(self):
        return Recipes().cleaning

    @xeno.provide
    @xeno.singleton
    def loop(self):
        return asyncio.get_event_loop()

    def build(self, *module_classes, targets = []):
        try:
            loop = asyncio.get_event_loop()
            Build.build_count += 1
            modules = [module_class() for module_class in module_classes]
            self.injector = xeno.Injector(self, *modules)
            self.injector.add_async_injection_interceptor(self._intercept_coroutines)

            if build.interactive and not targets:
                targets = self.targets
            if not targets:
                default_target = self._find_default_target()
                if not default_target:
                    raise BuildError('No target was specified and no default target was defined.')
                targets = [default_target]

            valid_targets = set(self._find_targets())
            for target in targets:
                if not target in valid_targets:
                    raise BuildError('Unknown target: %s' % target)

            setup_methods = self._find_setup_methods()
            for setup_method_name in setup_methods:
                self.injector.require(setup_method_name)

            result_map = {target: self.injector.require(target) for target in targets}
            result_map = {target: loop.run_until_complete(self._resolve_resource(target)) for target, value in result_map.items()}
            loop.run_until_complete(self._prepare_temp_targets_for_cleanup())

            # If we are cleaning, we need to resolve all targets in the dependency chain
            if self.cleaning():
                for dep in self.injector.get_dependency_graph(*targets):
                    if dep in valid_targets:
                        loop.run_until_complete(self._resolve_resource(dep))
        finally:
            Recipes().cleanup()

        return result_map

    async def _resolve_resource(self, name, value = xeno.NOTHING, alias = None):
        name = alias or name
        attr = self.injector.get_resource_attributes(name)
        if name in self.coro_results and attr.check('singleton'):
            return self.coro_results[name]
        else:
            value = await self.injector.require_async(name) if value is xeno.NOTHING else value

        if asyncio.iscoroutine(value):
            value = await value
            if attr.check('singleton'):
                self.coro_results[name] = value
                return self.coro_results[name]

        elif is_iterable(value) and name not in self.scanned_iterables:
            self.scanned_iterables.add(name)
            coro_offsets = filter(lambda cv: asyncio.iscoroutine(cv[1]), enumerate(value))
            if coro_offsets:
                value = value[:]
                coro_values = await asyncio.gather(*[xeno.async_map(*cv) for cv in coro_offsets])
                for x, v in coro_values:
                    value[x] = v
                self.coro_results[name] = value

        return value

    async def _intercept_coroutines(self, attrs, param_map, alias_map):
        return {k: await self._resolve_resource(k, value=v, alias=alias_map[k]) for k, v in param_map.items()}

    def __call__(self, *modules):
        self.build(*modules)

    async def _prepare_temp_targets_for_cleanup(self):
        for target in self.built_temp_resources:
            result = await self._resolve_resource(target)

            if is_iterable(result):
                Recipes().temp_files.extend(list(result))
            else:
                Recipes().temp_files.append(result)

    def _find_setup_methods(self):
        return [r[0] for r in self.injector.scan_resources(lambda name, attr: attr.check('bakery-setup'))]

    def _find_targets(self):
        return [r[0] for r in self.injector.scan_resources(lambda name, attr: attr.check('bakery-target'))]

    def _find_default_target(self):
        results = list(self.injector.scan_resources(lambda name, attr: attr.check('bakery-default')))
        if not results:
            return None
        elif len(results) > 1:
            raise TargetConflictError('Multiple default targets defined.', results)
        return results[0][0] if results else None

#--------------------------------------------------------------------
__all__ = [
   'alias',
   'build',
   'compose',
   'const',
   'default',
   'inject',
   'named',
   'namespace',
   'noclean',
   'provide',
   'recipe',
   'setup',
   'shell',
   'singleton',
   'target',
   'temp',
   'using'
]

#--------------------------------------------------------------------
alias = xeno.alias
build = Build()
const = xeno.const
gather = asyncio.gather
inject = xeno.inject
method_attr = xeno.MethodAttributes.add
named = xeno.named
namespace = xeno.namespace
noclean = build.noclean
provide = xeno.provide
recipe = Recipes().recipe
singleton = xeno.singleton
setup = compose(singleton, method_attr('bakery-setup'))
shell = Shell().__call__
target = compose(asyncio.coroutine, singleton, method_attr('bakery-target'))
temp = compose(singleton, build.temp)
default = compose(target, method_attr('bakery-default'))
using = xeno.using

