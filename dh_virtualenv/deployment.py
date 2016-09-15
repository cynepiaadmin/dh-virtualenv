# -*- coding: utf-8 -*-
# Copyright (c) 2013 - 2014 Spotify AB

# This file is part of dh-virtualenv.

# dh-virtualenv is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 2 of the
# License, or (at your option) any later version.

# dh-virtualenv is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with dh-virtualenv. If not, see
# <http://www.gnu.org/licenses/>.

import os
import re
import shutil
import subprocess
import tempfile

ROOT_ENV_KEY = 'DH_VIRTUALENV_INSTALL_ROOT'
DEFAULT_INSTALL_DIR = '/usr/share/python/'
PYTHON_INTERPRETERS = ['python', 'pypy', 'ipy', 'jython']
_PYTHON_INTERPRETERS_REGEX = r'\(' + r'\|'.join(PYTHON_INTERPRETERS) + r'\)'


class Deployment(object):
    def __init__(self,
                 package,
                 extra_urls=[],
                 preinstall=[],
                 pip_tool='pip',
                 upgrade_pip=False,
                 index_url=None,
                 setuptools=False,
                 python=None,
                 builtin_venv=False,
                 sourcedirectory=None,
                 verbose=False,
                 extra_pip_arg=[],
                 extra_virtualenv_arg=[],
                 use_system_packages=False,
                 skip_install=False,
                 install_suffix=None,
                 requirements_filename='requirements.txt'):

        self.package = package
        install_root = os.environ.get(ROOT_ENV_KEY, DEFAULT_INSTALL_DIR)
        self.install_suffix = install_suffix

        self.debian_root = os.path.join(
            'debian', package, install_root.lstrip('/'))

        if install_suffix is None:
            self.virtualenv_install_dir = os.path.join(install_root, self.package)
            self.package_dir = os.path.join(self.debian_root, package)
        else:
            self.virtualenv_install_dir = os.path.join(install_root, install_suffix)
            self.package_dir = os.path.join(self.debian_root, install_suffix)

        self.bin_dir = os.path.join(self.package_dir, 'bin')
        self.local_bin_dir = os.path.join(self.package_dir, 'local', 'bin')

        self.preinstall = preinstall
        self.upgrade_pip = upgrade_pip
        self.extra_virtualenv_arg = extra_virtualenv_arg
        self.log_file = tempfile.NamedTemporaryFile()
        self.verbose = verbose
        self.setuptools = setuptools
        self.python = python
        self.builtin_venv = builtin_venv
        self.sourcedirectory = '.' if sourcedirectory is None else sourcedirectory
        self.use_system_packages = use_system_packages
        self.skip_install = skip_install
        self.requirements_filename = requirements_filename

        # We need to prefix the pip run with the location of python
        # executable. Otherwise it would just blow up due to too long
        # shebang-line.
        python = self.venv_bin('python')
        self.pip_preinstall_prefix = [python, self.venv_bin('pip')]
        self.pip_prefix = [python, self.venv_bin(pip_tool)]
        self.pip_args = ['install']

        if self.verbose:
            self.pip_args.append('-v')

        if index_url:
            self.pip_args.append('--index-url={0}'.format(index_url))
        self.pip_args.extend([
            '--extra-index-url={0}'.format(url) for url in extra_urls
        ])
        self.pip_args.append('--log={0}'.format(os.path.abspath(self.log_file.name)))
        # Add in any user supplied pip args
        self.pip_args.extend(extra_pip_arg)

    @classmethod
    def from_options(cls, package, options):
        verbose = options.verbose or os.environ.get('DH_VERBOSE') == '1'
        return cls(package,
                   extra_urls=options.extra_index_url,
                   preinstall=options.preinstall,
                   pip_tool=options.pip_tool,
                   upgrade_pip=options.upgrade_pip,
                   index_url=options.index_url,
                   setuptools=options.setuptools,
                   python=options.python,
                   builtin_venv=options.builtin_venv,
                   sourcedirectory=options.sourcedirectory,
                   verbose=verbose,
                   extra_pip_arg=options.extra_pip_arg,
                   extra_virtualenv_arg=options.extra_virtualenv_arg,
                   use_system_packages=options.use_system_packages,
                   skip_install=options.skip_install,
                   install_suffix=options.install_suffix,
                   requirements_filename=options.requirements_filename)

    def clean(self):
        shutil.rmtree(self.debian_root)

    def create_virtualenv(self):
        if self.builtin_venv:
            virtualenv = [self.python, '-m', 'venv']
        else:
            virtualenv = ['virtualenv']

            if self.use_system_packages:
                virtualenv.append('--system-site-packages')
            else:
                virtualenv.append('--no-site-packages')

            if self.setuptools:
                virtualenv.append('--setuptools')

            if self.verbose:
                virtualenv.append('--verbose')

            if self.python:
                virtualenv.extend(('--python', self.python))

            # Add in any user supplied pip args
            if self.extra_virtualenv_arg:
                virtualenv.extend(self.extra_virtualenv_arg)

        virtualenv.append(self.package_dir)
        subprocess.check_call(virtualenv)

    def venv_bin(self, binary_name):
        return os.path.abspath(os.path.join(self.bin_dir, binary_name))

    def pip_preinstall(self, *args):
        return self.pip_preinstall_prefix + self.pip_args + list(args)

    def pip(self, *args):
        return self.pip_prefix + self.pip_args + list(args)

    def install_dependencies(self):
        # Install preinstall stage packages. This is handy if you need
        # a custom package to install dependencies (think something
        # along lines of setuptools), but that does not get installed
        # by default virtualenv.
        if self.upgrade_pip:
            subprocess.check_call(self.pip_preinstall('-U', 'pip'))
        if self.preinstall:
            subprocess.check_call(self.pip_preinstall(*self.preinstall))

        requirements_path = os.path.join(self.sourcedirectory, self.requirements_filename)
        if os.path.exists(requirements_path):
            subprocess.check_call(self.pip('-r', requirements_path))

    def run_tests(self):
        python = self.venv_bin('python')
        setup_py = os.path.join(self.sourcedirectory, 'setup.py')
        if os.path.exists(setup_py):
            subprocess.check_call([python, 'setup.py', 'test'], cwd=self.sourcedirectory)

    def find_script_files(self):
        """Find list of files containing python shebangs in the bin directory"""
        command = ['grep', '-l', '-r', '-e',
                   r'^#!.*bin/\(env \)\?{0}'.format(_PYTHON_INTERPRETERS_REGEX),
                   self.bin_dir]
        grep_proc = subprocess.Popen(command, stdout=subprocess.PIPE)
        files, stderr = grep_proc.communicate()
        return files.strip().split('\n')

    def fix_shebangs(self):
        """Translate /usr/bin/python and /usr/bin/env python sheband
        lines to point to our virtualenv python.
        """
        pythonpath = os.path.join(self.virtualenv_install_dir, 'bin/python')
        for f in self.find_script_files():
            regex = r's-^#!.*bin/\(env \)\?{names}\"\?-#!{pythonpath}-'\
                .format(names=_PYTHON_INTERPRETERS_REGEX, pythonpath=re.escape(pythonpath))
            subprocess.check_call(['sed', '-i', regex, f])

    def fix_activate_path(self):
        """Replace the `VIRTUAL_ENV` path in bin/activate to reflect the
        post-install path of the virtualenv.
        """
        activate_settings = [
            [
                'VIRTUAL_ENV="{0}"'.format(self.virtualenv_install_dir),
                r'^VIRTUAL_ENV=.*$',
                "activate"
            ],
            [
                'setenv VIRTUAL_ENV "{0}"'.format(self.virtualenv_install_dir),
                r'^setenv VIRTUAL_ENV.*$',
                "activate.csh"
            ],
            [
                'set -gx VIRTUAL_ENV "{0}"'.format(self.virtualenv_install_dir),
                r'^set -gx VIRTUAL_ENV.*$',
                "activate.fish"
            ],
        ]

        for activate_args in activate_settings:
            virtualenv_path = activate_args[0]
            pattern = re.compile(activate_args[1], flags=re.M)
            activate_file = activate_args[2]

            with open(self.venv_bin(activate_file), 'r+') as fh:
                content = pattern.sub(virtualenv_path, fh.read())
                fh.seek(0)
                fh.truncate()
                fh.write(content)

    def install_package(self):
        if not self.skip_install:
            subprocess.check_call(self.pip('.'), cwd=os.path.abspath(self.sourcedirectory))

    def fix_local_symlinks(self):
        # The virtualenv might end up with a local folder that points outside the package
        # Specifically it might point at the build environment that created it!
        # Make those links relative
        # See https://github.com/pypa/virtualenv/commit/5cb7cd652953441a6696c15bdac3c4f9746dfaa1
        local_dir = os.path.join(self.package_dir, "local")
        if not os.path.isdir(local_dir):
            return
        elif os.path.samefile(self.package_dir, local_dir):
            # "local" points directly to its containing directory
            os.unlink(local_dir)
            os.symlink(".", local_dir)
            return

        for d in os.listdir(local_dir):
            path = os.path.join(local_dir, d)
            if not os.path.islink(path):
                continue

            existing_target = os.readlink(path)
            if not os.path.isabs(existing_target):
                # If the symlink is already relative, we don't
                # want to touch it.
                continue

            new_target = os.path.relpath(existing_target, local_dir)
            os.unlink(path)
            os.symlink(new_target, path)
