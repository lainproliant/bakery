from ..core import recipe, remove, shell

# --------------------------------------------------------------------
@recipe("repo")
async def clone(url, repo):
    await shell("git", "clone", url, repo)
    return repo
