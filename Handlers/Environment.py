#!/usr/bin/env python
# Environment.py
#   Copyright (C) 2006 CCLRC, Graeme Winter
#
#   This code is distributed under the terms and conditions of the
#   CCP4 Program Suite Licence Agreement as a CCP4 Library.
#   A copy of the CCP4 licence can be obtained by writing to the
#   CCP4 Secretary, Daresbury Laboratory, Warrington WA4 4AD, UK.
#
# Maintained by Graeme Winter
# 18th September 2006
# 
# A handler for matters of the operating environment, which will impact
# on data harvesting, working directories, a couple of other odds & sods.
# 
# 
# 

import os
import sys

class _Environment:
    '''A class to store environmental considerations.'''

    def __init__(self):
        self._cwd = os.getcwd()

        harvest_directory = self.generate_directory('Harvest')
        self.setenv('HARVESTHOME', harvest_directory)

    def generate_directory(self, path_tuple):
        '''Used for generating working directories.'''
        path = self._cwd

        if type(path_tuple) == type('string'):
            path_tuple = (path_tuple,)

        for p in path_tuple:
            path = os.path.join(path, p)

        os.makedirs(path)

        return path

    def setenv(self, name, value):
        '''A wrapper for os.environ.'''

        os.environ[name] = value

        return

    def getenv(self, name):
        '''A wrapper for os.environ.'''
        try:
            return os.environ[name]
        except:
            return None

Environment = _Environment()

if __name__ == '__main__':

    print Environment.getenv('HARVESTHOME')
