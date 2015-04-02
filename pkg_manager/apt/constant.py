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

DSC_SERVICE_NAME = "com.linuxdeepin.softwarecenter"
DSC_SERVICE_PATH = "/com/linuxdeepin/softwarecenter"

DSC_FRONTEND_NAME = "com.linuxdeepin.softwarecenter_frontend"
DSC_FRONTEND_PATH = "/com/linuxdeepin/softwarecenter_frontend"

ACTION_INSTALL = 1
ACTION_UNINSTALL = 2
ACTION_UPGRADE = 3

DOWNLOAD_STATUS_OK = 0
DOWNLOAD_STATUS_NOTNEED = 1
DOWNLOAD_STATUS_ERROR = 2

UPDATE_DATA_URL = "http://dsc-update-data.b0.upaiyun.com"

PKG_SIZE_OWN = 0
PKG_SIZE_DOWNLOAD = 1
PKG_SIZE_ERROR = 2

UPDATE_LIST_LOG_PATH = '/tmp/dsc-update-list.log'
UPGRADE_LOG_PATH = '/tmp/dsc-upgrade.log'
LOG_PATH = "/tmp/dsc-backend.log"

"""Please note that modify the BACKEND_PID to notify the other testing program
eg: deepin-software-center fontend, deepin-system-settings power module etc."""
BACKEND_PID = "/var/run/dsc_backend_running.pid"

SYS_CONFIG_INFO_PATH = "/var/cache/deepin-software-center/config_info.ini"

SYS_PKG_WHITE_LIST = [
"base-files",
"pulseaudio",
"xserver-xorg",
"compiz",
"lightdm",
"deepin-icon-theme",
"startdde",
"dde-workspace",
"dde-control-center",
"dde-dock-applets",
"dde-daemon",
"deepin-ui",
"deepin-software-center-data",
"deepin-software-center",
"deepin-menu",
]
