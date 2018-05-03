import argparse
import sys

from .core import build
from .recipes.core import Recipes
from .utils import *

#--------------------------------------------------------------------
class Config:
    """
        Describes the configuration options that can be passed to the
        'bake' command line tool.
    """
    def __init__(self):
        self.targets = []
        self.bakefile = 'Bakefile.py'
        self.cleaning = False

    @staticmethod
    def get_arg_parser():
        parser = argparse.ArgumentParser(description = 'Build targets in bakefiles.')
        parser.add_argument('targets', metavar='TARGET', nargs='*', default=None)
        parser.add_argument('-b', '--bakefile')
        parser.add_argument('-c', '--clean', dest='cleaning', action='store_true')
        return parser

    def parse_known_args(self):
        self.get_arg_parser().parse_known_args(namespace = self)
        return self

    def parse_args(self):
        self.get_arg_parser().parse_args(namespace = self)
        return self

#--------------------------------------------------------------------
PREAMBLE = """from bakery import *
"""

#--------------------------------------------------------------------
def configure():
    log = get_logger("bakery.bake.configure")
    config = Config()
    config.parse_known_args()
    build.interactive = True
    build.targets = config.targets
    Recipes().cleaning = config.cleaning

    if not os.path.exists(config.bakefile):
        log.critical("No '%s' in the current directory." % config.bakefile)
        sys.exit(1)

    return config

#--------------------------------------------------------------------
def main():
    """
        The main entry point of the 'bake' command line tool.
        Prepends the PREAMBLE source to the contents of 'Bakefile.py'
        in the current directory, or the file specified by the '-b'
        command line switch, and executes the resulting script.
    """
    log = get_logger("bakery.bake.main")
    config = configure()
    
    bake_instructions = PREAMBLE + open(config.bakefile).read()

    try:
        exec(bake_instructions, globals())
        log.info(fg.bright.green('BUILD SUCCEEDED'))
    except Exception as e:
        build.critical = True
        log.error(str(e))
        if DEBUG:
            log.exception("Exception details follow.")
        log.info(fg.bright.red('BUILD FAILED'))

    if build.build_count == 0 and not build.critical:
        log.warn(ansilog.Node.list("Nothing was built, did you forget to decorate your module with ", fg.bright.yellow("@build"), "?"))

    sys.exit(0)

#--------------------------------------------------------------------
if __name__ == '__main__':
    main()

