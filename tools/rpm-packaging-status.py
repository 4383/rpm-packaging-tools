#!/usr/bin/python
# Copyright (c) 2016 SUSE Linux GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from __future__ import print_function

import argparse
from collections import namedtuple
import os
from packaging import version
from packaging.requirements import Requirement
import re
import sys
import yaml


# do some project name corrections if needed
projects_mapping = {
    "keystoneauth": "keystoneauth1"
}


V = namedtuple('V', ['release', 'upper_constraints', 'rpm_packaging_pkg',
                     'obs_published'])


def process_args():
    parser = argparse.ArgumentParser(
        description='Compare rpm-packaging with OpenStack releases')
    parser.add_argument('releases-git-dir',
                        help='Base directory of the openstack/releases '
                        'git repo', default='releases')
    parser.add_argument('rpm-packaging-git-dir',
                        help='Base directory of the openstack/rpm-packaging '
                        'git repo', default='rpm-packaging')
    parser.add_argument('requirements-git-dir',
                        help='Base directory of the openstack/requirements '
                        'git repo', default='requirements')
    parser.add_argument('--obs-published-xml',
                        help='path to a published xml file from the '
                        'openbuildservice')
    parser.add_argument('release',
                        help='name of the release. I.e. "mitaka"',
                        default='mitaka')
    parser.add_argument('--include-projects', nargs='*', metavar='project-name',
                        default=[], help='If non-empty, only the given '
                        'projects will be checked. default: %(default)s')
    parser.add_argument('--format',
                        help='output format', choices=('text', 'html'),
                        default='text')
    return vars(parser.parse_args())


def find_highest_release_version(releases):
    """get a list of dicts with a version key and find the highest version
    using PEP440 to compare the different versions"""
    return max(version.parse(r['version']) for r in releases)


def _rpm_split_filename(filename):
      """Taken from yum's rpmUtils.miscutils.py file
      Pass in a standard style rpm fullname
      Return a name, version, release, epoch, arch, e.g.::
          foo-1.0-1.i386.rpm returns foo, 1.0, 1, i386
          1:bar-9-123a.ia64.rpm returns bar, 9, 123a, 1, ia64
      """
      if filename[-4:] == '.rpm':
          filename = filename[:-4]

      archIndex = filename.rfind('.')
      arch = filename[archIndex+1:]

      relIndex = filename[:archIndex].rfind('-')
      rel = filename[relIndex+1:archIndex]

      verIndex = filename[:relIndex].rfind('-')
      ver = filename[verIndex+1:relIndex]

      epochIndex = filename.find(':')
      if epochIndex == -1:
          epoch = ''
      else:
          epoch = filename[:epochIndex]

      name = filename[epochIndex + 1:verIndex]
      return name, ver, rel, epoch, arch


def find_openbuildservice_pkg_version(published_xml, pkg_name):
    """find the version in the openbuildservice published xml for the given
    pkg name"""
    import pymod2pkg
    import xml.etree.ElementTree as ET

    if published_xml and os.path.exists(published_xml):
        with open(published_xml) as f:
            tree = ET.fromstring(f.read())

        distro_pkg_name = pymod2pkg.module2package(pkg_name, 'suse')
        for child in tree:
            if not child.attrib['name'].startswith('_') and \
               child.attrib['name'].endswith('.rpm') and not \
               child.attrib['name'].endswith('.src.rpm'):
                (name, ver, release, epoch, arch) = _rpm_split_filename(
                child.attrib['name'])
                if name == distro_pkg_name:
                    return version.parse(ver)
    return version.parse('0')


def find_rpm_packaging_pkg_version(pkg_project_spec):
    """get a spec.j2 template and get the version"""
    if os.path.exists(pkg_project_spec):
        with open(pkg_project_spec) as f:
            for l in f:
                m = re.search('^Version:\s*(?P<version>.*)\s*$', l)
                if m:
                    return version.parse(m.group('version'))
        # no version in spec found
        print('ERROR: no version in %s found' % pkg_project_spec)
        return version.parse('0')
    return version.parse('0')


def _pretty_table(release, projects, include_obs):
    from prettytable import PrettyTable
    tb = PrettyTable()
    fn = ['name',
          'release (%s)' % release,
          'u-c (%s)' % release,
          'rpm packaging (%s)' % release]
    if include_obs:
        fn += ['obs']
    fn += ['comment']
    tb.field_names = fn

    for p_name, x in projects.items():
        if x.rpm_packaging_pkg == version.parse('0'):
            comment = 'needs packaging'
        elif x.rpm_packaging_pkg < x.release:
            comment = 'needs upgrade'
        elif x.rpm_packaging_pkg == x.release:
            if x.release > x.upper_constraints:
                comment = 'needs downgrade (u-c)'
            comment = 'perfect'
        elif x.rpm_packaging_pkg > x.release:
            comment = 'needs downgrade'
        else:
            comment = ''
        row = [p_name, x.release, x.upper_constraints, x.rpm_packaging_pkg]
        if include_obs:
            row += [x.obs_published]
        row += [comment]

        tb.add_row(row)

    return tb


def output_text(release, projects, include_obs):
    tb = _pretty_table(release, projects, include_obs)
    print(tb.get_string(sortby='name'))


def output_html(release, projects, include_obs):
    """adjust the comment color a big with an ugly hack"""
    from lxml import html
    tb = _pretty_table(release, projects, include_obs)
    s = tb.get_html_string(sortby='name')
    tree = html.document_fromstring(s)
    tab = tree.cssselect('table')
    tab[0].attrib['style'] = 'border-collapse: collapse;'
    trs = tree.cssselect('tr')
    for t in trs:
        t.attrib['style'] = 'border-bottom:1pt solid black;'
    tds = tree.cssselect('td')
    for t in tds:
        if t.text_content() == 'needs packaging':
            t.attrib['style'] = 'background-color:yellow'
        elif t.text_content() == 'needs upgrade':
            t.attrib['style'] = 'background-color:LightYellow'
        elif t.text_content() == ('needs downgrade' or 'needs downgrade (uc)'):
            t.attrib['style'] = 'background-color:red'
        elif t.text_content() == 'perfect':
            t.attrib['style'] = 'background-color:green'
    print(html.tostring(tree))


def read_upper_constraints(filename):
    uc = dict()
    with open(filename) as f:
        for l in f.readlines():
            # ignore markers for now
            l = l.split(';')[0]
            r = Requirement(l)
            for s in r.specifier:
                uc[r.name] = s.version
                # there is only a single version in upper constraints
                break
    return uc


def main():
    args = process_args()

    projects = {}

    upper_constraints = read_upper_constraints(
        os.path.join(args['requirements-git-dir'], 'upper-constraints.txt'))

    # directory which contains all yaml files from the openstack/release git dir
    releases_yaml_dir = os.path.join(args['releases-git-dir'], 'deliverables',
                            args['release'])
    for yaml_file in os.listdir(releases_yaml_dir):
        project_name = re.sub('\.ya?ml$', '', yaml_file)
        # skip projects if include list is given
        if len(args['include_projects']) and \
           project_name not in args['include_projects']:
            continue
        with open(os.path.join(releases_yaml_dir, yaml_file)) as f:
            data = yaml.load(f.read())
            v_release = find_highest_release_version(data['releases'])

        # do some mapping if pkg name is different to the name from release repo
        if project_name in projects_mapping:
            project_name_pkg = projects_mapping[project_name]
        else:
            project_name_pkg = project_name

        # get version from upper-constraints.txt
        if project_name in upper_constraints:
            v_upper_constraints = upper_constraints[project_name]
        else:
            v_upper_constraints = '-'

        # path to the corresponding .spec.j2 file
        rpm_packaging_pkg_project_spec = os.path.join(
            args['rpm-packaging-git-dir'],
            'openstack', project_name_pkg,
            '%s.spec.j2' % project_name_pkg)
        v_rpm_packaging_pkg = find_rpm_packaging_pkg_version(rpm_packaging_pkg_project_spec)

        # version from build service published file
        v_obs_published = find_openbuildservice_pkg_version(
            args['obs_published_xml'], project_name)

        # add both versions to the project dict
        projects[project_name] = V(v_release,
                                   v_upper_constraints,
                                   v_rpm_packaging_pkg,
                                   v_obs_published)

    include_obs = args['obs_published_xml']
    if args['format'] == 'text':
        output_text(args['release'], projects, include_obs)
    elif args['format'] == 'html':
        output_html(args['release'], projects, include_obs)

    return 0


if __name__ == '__main__':
    sys.exit(main())
