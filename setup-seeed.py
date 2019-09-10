import os
import sys
inc = '''
include mu/*
include README.rst
include CHANGES.rst
include LICENSE
include conf/*
include mu/resources/css/*
include mu/resources/images/*
include mu/resources/fonts/*
include mu/resources/pygamezero/*
include mu/resources/seeed/*
include run.py
recursive-include mu/locale *
'''
file = open('MANIFEST.in', 'w')
if os.name == 'posix':
    file.write('include mu/resources/seeed/tools-posix/*\n' + inc)
elif os.name == 'nt':
    file.write('include mu/resources/seeed/tools-win/*\n' + inc)
file.close()
