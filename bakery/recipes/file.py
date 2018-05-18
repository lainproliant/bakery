from ..core import recipe, remove

import glob
import shutil
import urllib.request
import os

from os.path import *
from glob import glob

#--------------------------------------------------------------------
@recipe('dst', check='src')
def copy(src, dst, log: 'log'):
    if isdir(src):
        log.trace('Copying directory: %s --> %s' % (src, dst))
        shutil.copytree(src, dst)
    else:
        log.trace('Copying file: %s --> %s' % (src, dst))
        shutil.copy(src, dst)
    return dst

#--------------------------------------------------------------------
@recipe('path')
def directory(path, log: 'log'):
    if not exists(path):
        log.trace('Making directory: %s' % path)
        os.makedirs(path)
    if not isdir(path):
        raise BuildError('File exists but is not a directory: %s' % path)
    return path

#--------------------------------------------------------------------
@recipe(temp='path')
def temp_directory(path, log: 'log'):
    if not exists(path):
        log.trace('Making directory: %s' % path)
        os.makedirs(path)
    if not isdir(path):
        raise BuildError('File exists but is not a directory: %s' % path)
    return path

#--------------------------------------------------------------------
@recipe('file')
def download(url, file):
    urllib.request.urlretrieve(url, file)

#--------------------------------------------------------------------
def drop_ext(filename):
    return splitext(filename)[0]

#--------------------------------------------------------------------
def swap_ext(filename, ext):
    return '.'.join([splitext(filename)[0], ext])

