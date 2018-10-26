from ..core import recipe, shell

#--------------------------------------------------------------------
CC = 'cc'
CFLAGS = []
LDFLAGS = []

#--------------------------------------------------------------------
@recipe('obj', check='src', verbose = True)
async def compile(src, obj, log: 'log'):
    await shell(CC, CFLAGS, '-c', src, '-o', obj, log = log)
    return obj

#--------------------------------------------------------------------
@recipe('executable', check='obj')
async def link(obj, executable, log: 'log'):
    await shell(CC, LDFLAGS, obj, '-o', executable, log = log)
    return executable

