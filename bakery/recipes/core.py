import os
import sys
import traceback
import xeno

from ..utils import *
from ..exceptions import *

#--------------------------------------------------------------------
class Recipes:
    __borg = None

    def __init__(self, config = None):
        if Recipes.__borg is None:
            self.temp_files = []
            self.cleaning = False
            self.log = get_logger("bakery.recipes.core.Recipes")
            Recipes.__borg = self.__dict__
        else:
            self.__dict__ = self.__borg

    def recipe(self, *targets, check = None, temp = None, name = None, verbose = False):
        targets = set(targets)
        check = make_iterable(check, lambda x: set([x])) or set()
        temp = make_iterable(temp, lambda x: set([x])) or set()
        outputs = targets | temp

        def decorator(f):
            attrs = xeno.MethodAttributes.for_method(f)
            recipe_name = name or attrs.get('name', 'recipe')
            signature = inspect.signature(f)
            recipe_qualname = '%s.%s#recipe' % (f.__module__, f.__qualname__)
            
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
                long_name = recipe_name
                if (check_files or output_files or temp_files) and verbose:
                    long_name = '%s %s' % (recipe_name, ','.join(check_files or output_files or temp_files))
                log = JobLog(self.log, name = long_name)

                if DEBUG:
                    print('Recipe %s invoked here...' % recipe_qualname, file = sys.stderr)
                    for line in traceback.format_stack():
                        sys.stderr.write(line)

            
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

                def coalesce_default_outputs():
                    if len(targets) == 1 and len(target_params) == 1 and not is_iterable(target_params[0]):
                        return target_params[0]
                    else:
                        return output_files
            
                def clean():
                    if outputs_exist():
                        log.trace('Cleaning...')
                        for file in output_files:
                            remove(file, log = log)
                    return coalesce_default_outputs()

                async def build_recipe():
                    result = await xeno.async_wrap(f, *args, **kwargs)
                    self.temp_files.extend(temp_files)
                    if not outputs_up_to_date():
                        raise BuildError('Recipe "%s %s" failed to create the prescribed output: %s' % (recipe_name, ', '.join(check_files), ', '.join(output_files)))
                    return result

                if self.cleaning:
                    return clean()
                elif not outputs_up_to_date():
                    return await build_recipe()
                else:
                    return coalesce_default_outputs()
            wrapper.__name__ = recipe_qualname
            wrapper.__qualname__ = recipe_qualname
            return wrapper
        return decorator

    def cleanup(self):
        log = JobLog(self.log, name = 'cleanup') 
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                remove(temp_file, log = log)

#--------------------------------------------------------------------
recipe = Recipes().recipe
