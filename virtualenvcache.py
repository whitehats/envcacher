#!/usr/bin/env python

import logging as log
import argparse
import contextlib
import fileinput
import hashlib
import imp
import multiprocessing
import os.path
import shutil
import sys
import virtualenv

import requirements


class BuildingVEUnsuccessfulError(Exception):
    ''' Thrown when virtualenv seems not to be ready for use. '''
    pass


class Options(object):
    ''' Parses and stores options. '''
    def __init__(self):
        self.parser = None

    def __parser(self):
        parser = argparse.ArgumentParser(
            description='A wrapper over `virtualenv` which caches '
                        'environments.')

        parser.add_argument('-d', '--directory', nargs=1,
                            default=[os.path.expanduser('~/.cache/virtualenvs')],
                            help='where cached virtual environments go')

        parser.add_argument('-r', '--requirements', action='append',
                            required=True,
                            help='your pip requirements file')

        parser.add_argument('-a', '--activate-script', nargs=1,
                            help='symlink activation script to given file')

        parser.add_argument('-k', '--keep-broken', action='store_true',
                            help='keep virtualenv if there was an error '
                                 'while building it')

        parser.add_argument('--fix-pip', action='store_true',
                            help='fix pip problem with missing uses_fragment')

        parser.add_argument('-v', '--verbose', action='store_true',
                            default=False,
                            help='print verbose informations while processing')

        return parser

    def parse(self):
        ''' Parse my arguments. '''

        args = self.__parser().parse_args()

        self.requirements = args.requirements
        self.directory = args.directory[0]
        self.keep_broken = bool(args.keep_broken)
        self.fix_pip = bool(args.fix_pip)
        self.verbose = bool(args.verbose)

        self.activate_script = None
        if args.activate_script:
            self.activate_script = args.activate_script[0]


class KeyBase(object):
    ''' Base class for representing a specific distinguishible kind of
    a virtual environment. '''

    def __init__(self, options):
        self.options = options

    def get_key(self):
        ''' Construct a key string. '''

        raise NotImplementedError

    def initialize(self, ve):
        ''' Initialize a virtual environment to be representing specific
        kind of virtual environments. '''

        raise NotImplementedError


class RequirementsKey(KeyBase):
    ''' A key that distinguishes virtual environments based on a list of
    packages installed in it. '''

    def __init__(self, options):
        KeyBase.__init__(self, options)

        with contextlib.closing(fileinput.input(options.requirements)) \
        as handle:
            self.requirements = requirements.Requirements(handle)

    def get_key(self):
        keyhash = hashlib.md5()
        keyhash.update('\n'.join(str(r) for r in self.requirements.reqs))
        return keyhash.hexdigest()

    def initialize(self, ve):
        filename = os.path.join(ve.path, 'requirements.txt')

        with open(filename, 'w') as handle:
            self.requirements.store(handle)

        ve.execlp("pip", "install", "-r", filename)


class VirtualEnv(object):
    ''' Object representing a single virtual environment. '''

    def __init__(self, path):
        self.path = path

    @classmethod
    def build(cls, path, key, options, force=False):
        ''' Build a virtual environment in specified path, according to given
        key and options. '''

        virtualenv.logger = virtualenv.Logger(
            [(virtualenv.Logger.level_for_integer(2), sys.stderr)])

        # a simple check that what we want to remove looks like a ve name :)
        if force and os.path.exists(path):
            if len(os.path.basename(path)) == 32:
                shutil.rmtree(path)
            else:
                raise AssertionError("Ah, you probably do not want to delete "
                                     "%s, do you?" % path)

        os.makedirs(path)
        virtualenv.create_environment(home_dir=path)
        ve = VirtualEnv(path)

        # "fix" bug in pip
        # (see: http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=677801)
        if options.fix_pip:
            fragments_file = 'local/lib/python2.7/site-packages/' \
                             'pip-1.1-py2.7.egg/pip/vcs/__init__.py'
            ve.execlp("sed", "-ie",
                "/urlparse.uses_fragment.extend(self.schemes)/d",
                ve.local_path(fragments_file))
            ve.unlink(fragments_file + 'c')

        key.initialize(ve)

        ve.mark_as_good()

        return ve

    def local_path(self, filename):
        ''' Show absolute path for file relative to virtual environment. '''
        return os.path.join(os.path.abspath(self.path), filename)

    def __goodmark_file_name(self):
        return self.local_path('1335_HaXx0r_approved')

    def mark_as_bad(self):
        ''' Mark virtual environment as faulty. '''
        if os.path.exists(self.__goodmark_file_name()):
            os.unlink(self.__goodmark_file_name())

    def mark_as_good(self):
        ''' Mark virtual environment as non-faulty. '''
        with open(self.__goodmark_file_name(), 'w'):
            pass

    def is_good(self):
        '''Checks if given virtual environment is blessed.'''
        return os.path.exists(self.__goodmark_file_name())

    def is_bad(self):
        ''' Checks if given virtual environment is faulty. '''
        return not self.is_good()

    def execlp(self, call, *args):
        ''' Execute a command inside virtual environment. '''

        def thread(path, call, args):
            imp.load_source('activate_this',
                            os.path.join(path, 'bin/activate_this.py'))

            os.execlp(call, call, *args)

        thread = multiprocessing.Process(
            target=thread, args=(self.path, call, args))

        thread.start()
        thread.join()

        if thread.exitcode != 0:
            raise BuildingVEUnsuccessfulError(
                "Call {!r} (args={!r}) returned error code {}.".format(
                    call, args, thread.exitcode))

    def unlink(self, filename):
        ''' Remove a file relative to virtual environment home directory. '''
        return os.unlink(os.path.join(self.path, filename))


class VirtualEnvCache(object):
    ''' A cache full of virtual environments. '''

    def __init__(self, options):
        self.options = options

    def __path(self, key):
        return os.path.join(self.options.directory, key.get_key())

    def get(self, key):
        ''' Get (and create if not exists) a virtual environment for specified
        key. '''
        log.debug('try to get cached virtualenv')

        log.debug('check whether virtualenv is good: %s' % self.__path(key))
        ve = VirtualEnv(self.__path(key))
        if ve.is_good():
            log.debug('virtualenv is good, cache that bastard!')
            return ve
        else:
            log.info('virtualenv is bad: %s' % self.__path(key))
            try:
                log.debug('trying to rebuild virtualenv in: %s' % self.__path(key))
                return VirtualEnv.build(self.__path(key), key, self.options,
                                        force=True)
            except Exception:
                log.exception('error ocured while building virtualenv')
                if not self.options.keep_broken and\
                    os.path.exists(self.__path(key)):
                    log.debug('removing broken virtualenv')
                    shutil.rmtree(self.__path(key))
                else:
                    log.debug('keeping broken virtualenv')
                raise


def main():
    ''' Entry point. '''
    logger = log.getLogger()
    logger.setLevel(log.INFO)
    console = log.StreamHandler()
    console.setFormatter(log.Formatter("%(levelname)10s - %(message)s"))
    logger.addHandler(console)
    log.info('start virtualenvcache')

    opts = Options()
    opts.parse()

    if opts.verbose:
        logger.setLevel(log.DEBUG)
        log.debug('Turn on debug mode')

    reqs = RequirementsKey(opts)

    ve = VirtualEnvCache(opts).get(reqs)
    log.debug('VE returned from VirtualEnvCache: %s' % ve)

    if opts.activate_script and ve:
        activation_link = opts.activate_script
        log.debug('want to set activation link at: %s' % activation_link)
        if os.path.lexists(activation_link):
            os.unlink(activation_link)
        os.symlink(ve.local_path('bin/activate'), activation_link)
        log.info('activation link saved to: %s' % activation_link)


if __name__ == '__main__':
    main()
