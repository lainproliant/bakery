import bakery.recipes.c as C
import bakery.recipes.file as File

C.CC = "clang"
C.CFLAGS.append("-g")


@build
class Bakefile:
    @provide
    def sources(self):
        return File.glob("src/*.c")

    @temp
    def objects(self, sources):
        return [C.compile(x, File.swap_ext(x, "o")) for x in sources]

    @default
    def executable(self, objects):
        return C.link(objects, "executable")
