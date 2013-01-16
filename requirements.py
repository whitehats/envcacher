'''
Created on 03-07-2012

@author: liori
'''

import re


class Requirement(object):
    ''' A single requirement. '''
    def __init__(self):
        self.params = set()
        self.name = None
        self.url = None
        self.op = None
        self.version = None

    def __str__(self):
        return '{}{}{}{}'.format(
            ''.join('{} '.format(param) for param in self.params),
            self.url,
            self.op or '',
            self.version or '')

    def __repr__(self):
        return '{{Requirement: {}}}'.format(self.__str__())


class ConflictingRequirementsError(Exception):
    ''' Thrown when two requirements conflict with each other. '''
    pass


def is_vcs(word):
    ''' Is a word a VCS url? '''
    vcs_protocols = [
        'git', 'git+http', 'git+ssh',
        'hg+http', 'hg+https', 'hg+static-http', 'hg+ssh',
        'bzr+http', 'bzr+https', 'bzr+ssh', 'bzr+sftp', 'bzr+ftp', 'bzr+lp',
        'svn', 'svn+svn', 'svn+http', 'svn+https', 'svn+ssh']

    return any(word.startswith(proto) for proto in vcs_protocols)


def natural_sort(l):
    ''' Sort list of strings according to natural keys. '''
    convert = lambda text:int(text) if text.isdigit() else text.lower()
    alphanum_key = lambda key:[convert(c) for c in re.split('([0-9]+)', key)]
    return sorted(l, key = alphanum_key)


def common_req(a, b, d):
    ''' Store in `d` a common subset of requirements `a` and `b`. '''
    c = Requirement()
    c.params = a.params | b.params

    assert a.name == b.name
    c.name = a.name

    if is_vcs(a.url) and is_vcs(b.url):
        if a.url != b.url:
            raise ConflictingRequirementsError('Two different VCS sources for a single package: {!r}, {!r}'.format(a, b))
        c.url = a.url
    elif is_vcs(b.url):
        c.url = b.url
    else:
        c.url = a.url

    if a.op and b.op and is_vcs(c.url):
        raise ConflictingRequirementsError('Cannot specify a version for a VCS source: {!r}, {!r}'.format(a, b))

    if a.op is None:
        # a has no version requirements, we can copy whatever b has
        c.op = b.op
        c.version = b.version
    elif b.op is None:
        # b has no version requirements, we can copy whatever a has
        c.op = a.op
        c.version = a.version
    else:
        # take the higher version, then check if there are any problems with equalities
        c.version = natural_sort([a.version, b.version])[-1]
        if ((a.op == '==' and a.version != c.version) or
            (b.op == '==' and b.version != c.version)):
            raise ConflictingRequirementsError('Required version mismatch: {!r}, {!r}'.format(a,b))

    d.params = c.params
    d.name = c.name
    d.url = c.url
    d.op = c.op
    d.version = c.version


class Requirements(object):
    ''' List of requirements. '''
    def __init__(self, handle=None):
        self.reqs = []
        self.reqs_by_name = {}

        if handle is not None:
            self.load(handle)

    def __add_req(self, new_req):
        if new_req.name in self.reqs_by_name:
            old_req = self.reqs_by_name[new_req.name]
            common_req(old_req, new_req, old_req)

        else:
            self.reqs_by_name[new_req.name] = new_req
            self.reqs.append(new_req)

    def load(self, handle):
        ''' Load requirements from a pip requirements file. '''

        re_package = '(?P<package>[A-Za-z][A-Za-z0-9_.-]*)'
        re_version = '(?P<version>[0-9][0-9.]*)'
        re_eq_operator = '(?P<eqop>==)'
        re_geq_operator = '(?P<geqop>>=)'
        re_any_operator = '(?:{re_eq_operator}|{re_geq_operator})'.format(**locals())
        re_version_requirement = '(?:{re_any_operator}{re_version})'.format(**locals())
        re_package_version = '{re_package}{re_version_requirement}?$'.format(**locals())

        for line in handle:
            line = line.strip()
            if len(line) == 0:
                continue

            words = line.split()
            req = Requirement()

            if words[0] == '-r':
                with open(words[1]) as subhandle:
                    self.load(subhandle)

                continue

            if words[0] == '-e':
                req.params.add('-e')
                words = words[1:]

            if is_vcs(words[0]):
                match = re.search('#egg=({})$'.format(re_package), words[0])
                req.name = match.group('package')
                req.url = words[0]
            elif words[0].startswith('http://') or words[0].startswith('https://'):
                req.name = words[0]
                req.url = words[0]

            else:
                match = re.match(re_package_version, words[0]).groupdict()
                req.name = match['package']
                req.url = match['package']
                req.op = match['eqop'] or match['geqop']
                req.version = match['version']

            self.__add_req(req)

    def store(self, handle):
        ''' Store requirements to a pip requirements file. '''

        for req in self.reqs:
            handle.write('{}\n'.format(req))
