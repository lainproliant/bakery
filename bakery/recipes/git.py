from ..core import recipe, remove, shell

# --------------------------------------------------------------------
@recipe("repo")
async def clone(url, repo):
    await shell("git", "clone", url, repo)
    return repo

# --------------------------------------------------------------------
async def submodule_update():
    await shell('git', 'submodule', 'update', '--init' '--recursive')
