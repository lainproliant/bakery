from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='bakery-build',
    version='0.3.2',
    description='A dependency-driven build manager based on xeno.',
    long_description=long_description,
    url='https://github.com/lainproliant/bakery',
    author='Lain Supe (lainproliant)',
    author_email='lainproliant@gmail.com',
    license='BSD',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6'
    ],

    keywords='build make dependency',
    packages=find_packages(),
    install_requires=['xeno>=3.0.0', 'ansilog'],

    entry_points={
        'console_scripts': [
            'bake=bakery.bake:main'
        ],
    }
)
