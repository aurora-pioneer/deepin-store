#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2011 ~ 2012 Deepin, Inc.
#               2011 ~ 2012 Wang Yong
#
# Author:     Wang Yong <lazycat.manatee@gmail.com>
# Maintainer: Wang Yong <lazycat.manatee@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import apt
import apt_pkg
import json

class AptCache(apt.Cache):
    '''
    class docs
    '''

    PKG_STATUS_INSTALLED = 1
    PKG_STATUS_UNINSTALLED = 2
    PKG_STATUS_UPGRADED = 3
    PKG_STATUS_INSTALLING = 4
    PKG_STATUS_UNINSTALLING = 5
    PKG_STATUS_UPGRADING = 5

    def __init__(self):
        '''
        init docs
        '''
        apt_pkg.init()
        apt.Cache.__init__(self, apt.progress.base.OpProgress())
        self.packages_status = {}

        cache_instance = self
        class dep_init(object):
            def __init__(self):
                self.cache = cache_instance

            def __enter__(self):
                self.cache._depcache.init()
                return self.cache

            def __exit__(self, *args):
                self.cache._depcache.init()
        self.dep_init = dep_init

    def get_upgrade_pkgs(self):
        pkg_infos = []

        for pkg in self:
            if self.is_pkg_upgradable(pkg.name):
                pkg_version = pkg.versions[0].version
                pkg_infos.append(json.dumps((pkg.name, pkg_version)))
        return pkg_infos

    def get_dist_upgrade_changes(self):
        change_pkg_status = {"delete": [], "downgrade": [], "install": [], "keep": [], "reinstall": [], "upgrade": []}
        with self.dep_init():
            self.upgrade(True)
            change_pkgs = self.get_changes()
            for pkg in change_pkgs:
                if not pkg.is_installed and pkg.marked_install:
                    change_pkg_status["install"].append(pkg)
                elif pkg.marked_upgrade:
                    change_pkg_status["upgrade"].append(pkg)
                elif pkg.marked_delete:
                    change_pkg_status["delete"].append(pkg)
                elif pkg.marked_reinstall:
                    change_pkg_status["reinstall"].append(pkg)
                elif pkg.marked_keep:
                    change_pkg_status["keep"].append(pkg)
                elif pkg.marked_downgrade:
                    change_pkg_status["downgrade"].append(pkg)
        return change_pkg_status

    def set_pkg_status(self, pkg_name, status):
        self._depcache.init()
        self.packages_status[pkg_name] = status

    def get_pkg_status(self, pkg_name):
        status = self.packages_status.get(pkg_name)
        if status == None:
            try:
                if self[pkg_name].is_installed:
                    status = self.PKG_STATUS_INSTALLED
                else:
                    status = self.PKG_STATUS_UNINSTALLED
            except:
                return self.PKG_STATUS_UNINSTALLED
        return status

    def get_uninstall_pkgs(self):
        pkg_infos = []
        for pkg in self:
            if self.is_pkg_installed(pkg.name):
                pkg_version = pkg.installed.version
                pkg_infos.append([pkg.name, pkg_version])
        return pkg_infos

    def get_pkgs_uninstall_version(self, pkg_names):
        pkg_infos = []
        for pkg_name in pkg_names:
            try:
                pkg = self[pkg_name]
                if pkg.is_installed:
                    pkg_version = pkg.installed.version
                # This not just happended when simulate test.
                else:
                    pkg_version = pkg.versions[0].version

                pkg_infos.append(pkg_version)
            except:
                print "%s not in cache" % pkg_name
                pkg_infos.append(None)

        return pkg_infos

    def get_pkg_short_desc(self, pkg_name):
        return self[pkg_name].candidate.summary.encode("utf-8", "ignore")

    def is_pkg_installed(self, pkg_name):
        status = self.packages_status.get(pkg_name)
        if status == self.PKG_STATUS_INSTALLED or status == self.PKG_STATUS_UPGRADED:
            return True
        elif status == self.PKG_STATUS_UNINSTALLED:
            return False
        elif status == None:
            try:
                return self[pkg_name].is_installed
            except:
                try:
                    return self[pkg_name+":i386"].is_installed
                except:
                    return False

    def is_pkg_upgradable(self, pkg_name):
        status = self.packages_status.get(pkg_name)
        if status == self.PKG_STATUS_UPGRADED:
            return False
        else:
            try:
                return self[pkg_name].is_upgradable
            except Exception:
                return False

if __name__ == "__main__":
    pkg_cache = AptCache()
    changes = pkg_cache.get_dist_upgrade_changes()
    for key in changes:
        if len(changes[key]) > 0:
            print "%s(%s):" % (key, len(changes[key]))
            for item in changes[key]:
                print item
