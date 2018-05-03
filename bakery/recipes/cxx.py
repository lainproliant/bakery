from ..core import recipe, shell

#--------------------------------------------------------------------
CXX = 'c++'
CFLAGS = []
LDFLAGS = []

#--------------------------------------------------------------------
@recipe('obj', check='src', verbose = True)
async def compile(src, obj, log: 'log'):
    await shell(CXX, CFLAGS, '-c', src, '-o', obj, log = log)
    return obj

#--------------------------------------------------------------------
@recipe('executable', check='obj')
async def link(obj, executable, log: 'log'):
    await shell(CXX, LDFLAGS, obj, '-o', executable, log = log)
    return executable

