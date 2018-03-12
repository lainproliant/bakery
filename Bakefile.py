import glob

@recipe(check='src', temp='obj')
async def compile(src, obj, log: 'log'):
    await shell('cc', '-c', src, '-o', obj, log = log)
    return obj

@recipe('executable', check='objects')
async def link(objects, executable, log: 'log'):
    await shell('cc', objects, '-o', executable, log = log)
    return executable

@build
class Bakefile:
    @provide
    def sources(self):
        return File.glob('src/*.c') 
   
    @provide
    def objects(self, sources):
        return [compile(x, x + '.o') for x in sources]

    @default
    def executable(self, objects):
        return link(objects, 'executable')

