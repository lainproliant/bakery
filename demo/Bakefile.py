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
   
    @target
    async def objects(self, sources):
        return await asyncio.gather(*[compile(x, File.ext(x, 'o')) for x in sources])

    @default
    async def executable(self, objects):
        return await link(objects, 'executable')

