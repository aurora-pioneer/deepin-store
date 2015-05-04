#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
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

import os
from skin import app_theme
from nls import _

import glib
from data import data_exit
import gtk
import gobject
import dbus
import dbus.service
import time
import json
import sys
import traceback

from dtk.ui.theme import DynamicPixbuf
from dtk.ui.menu import Menu
from dtk.ui.constant import WIDGET_POS_BOTTOM_LEFT
from dtk.ui.button import LinkButton
from dtk.ui.slider import Wizard
from dtk.ui.navigatebar import Navigatebar
from dtk.ui.timeline import Timeline, CURVE_SINE
from deepin_utils.process import run_command
from deepin_utils.math_lib import solve_parabola
from deepin_utils.file import read_file, write_file, touch_file, get_parent_dir
from deepin_utils.multithread import create_thread
from dtk.ui.utils import container_remove_all, set_cursor, get_widget_root_coordinate
from dtk.ui.statusbar import Statusbar
from dtk.ui.slider import HSlider
from dtk.ui.label import Label
from dtk.ui.iconview import IconView
from dtk.ui.treeview import TreeView
from dtk.ui.application import Application

from inhibit import InhibitObject
from icon_window import IconWindow
from detail_page import DetailPage
from home_page import HomePage
from uninstall_page import UninstallPage
from install_page import InstallPage
from upgrade_page import UpgradePage
from data_manager import DataManager
from events import global_event
from start_desktop_window import StartDesktopWindow
from utils import (
        handle_dbus_reply,
        handle_dbus_error,
        bit_to_human_str,
        get_software_download_dir,
        )
import utils
from tooltip import ToolTip
from server_action import SendVote, SendDownloadCount, SendUninstallCount, SendErrorLog
from preference import DscPreferenceDialog
from paned_box import PanedBox
from widgets import BottomTipBar
from star_buffer import StarView, DscStarBuffer
from mirror_test import all_mirrors
from constant import (
            DSC_SERVICE_NAME, DSC_SERVICE_PATH,
            DSC_FRONTEND_NAME, DSC_FRONTEND_PATH,
            ACTION_INSTALL, ACTION_UNINSTALL, ACTION_UPGRADE,
            CONFIG_DIR, ONE_DAY_SECONDS,
            LANGUAGE,
        )
import logging
global_logger = logging.getLogger("dstore.ui.software_center")

tool_tip = ToolTip()
global tooltip_timeout_id
tooltip_timeout_id = None

def log(message):
    global debug_flag
    if debug_flag:
        print message

global current_status_pkg_page
current_status_pkg_page = None
def update_current_status_pkg_page(obj):
    global current_status_pkg_page
    current_status_pkg_page = obj

def refresh_current_page_status(pkg_name, pkg_info_list, bus_interface):
    change_pkgs = [info[0] for info in pkg_info_list]
    if isinstance(current_status_pkg_page, IconView):
        for item in current_status_pkg_page.items:
            if item.pkg_name in change_pkgs:
                item.is_installed = bus_interface.request_pkgs_install_status([pkg_name])[0]
                item.emit_redraw_request()
    elif isinstance(current_status_pkg_page, DetailPage):
        if current_status_pkg_page.pkg_name in change_pkgs:
            current_status_pkg_page.fetch_pkg_status()
    elif isinstance(current_status_pkg_page, TreeView):
        for item in current_status_pkg_page.visible_items:
            if item.pkg_name in change_pkgs:
                item.is_installed = bus_interface.request_pkgs_install_status([pkg_name])[0]
                item.emit_redraw_request()

def update_navigatebar_number(navigatebar, page_index, notify_number):
    navigatebar.update_notify_num(navigatebar.nav_items[page_index], notify_number)

def jump_to_category(page_switcher, page_box, home_page, detail_page, first_category_name, second_category_name):
    switch_page(page_switcher, page_box, home_page, detail_page)
    home_page.jump_to_category(first_category_name, second_category_name)

def start_pkg(alias_name, desktop_infos, (offset_x, offset_y, popup_x, popup_y), window):
    desktop_infos_num = len(desktop_infos)
    if desktop_infos_num == 0:
        global_event.emit("show-message", _("%s haven't any desktop file") % (alias_name))
    elif desktop_infos_num == 1:
        try:
            desktop_infos[0].launch()
            global_event.emit("show-message", _("%s: request for starting applications sent") % alias_name, 5000)
        except:
            global_logger.error("Launch error: %s" % desktop_infos[0])
    else:
        (screen, px, py, modifier_type) = window.get_display().get_pointer()
        StartDesktopWindow().start(alias_name, desktop_infos, (px - offset_x + popup_x, py - offset_y + popup_y))

global hide_timeout_id
hide_timeout_id = None

def show_message(statusbar, message_label, message, hide_timeout=0):
    global hide_timeout_id
    if hide_timeout_id:
        gobject.source_remove(hide_timeout_id)
        hide_timeout_id = None

    hide_message(message_label)

    message_label.set_text(message)
    statusbar.show_all()

    if hide_timeout:
        hide_timeout_id = gtk.timeout_add(hide_timeout, lambda : hide_message(message_label))

def hide_message(message_label):
    message_label.set_text("")
    return False

def request_status_reply_hander(result, install_page, upgrade_page, uninstall_page, pkg_info_list=None):
    (download_status, action_status) = map(eval, result)

    install_page.update_download_status(download_status[ACTION_INSTALL])
    install_page.update_action_status(action_status[ACTION_INSTALL])

    upgrade_page.update_download_status(download_status[ACTION_UPGRADE])
    upgrade_page.update_action_status(action_status[ACTION_UPGRADE])

    uninstall_page.update_action_status(action_status[ACTION_UNINSTALL])

    if pkg_info_list:
        global_event.emit("request-clear-action-pages", pkg_info_list)

def get_grade_config():
    grade_config_path = os.path.join(CONFIG_DIR, "grade_pkgs")
    if not os.path.exists(grade_config_path):
        touch_file(grade_config_path)

    grade_config_str = read_file(grade_config_path)
    try:
        grade_config = eval(grade_config_str)

        if type(grade_config).__name__ != "dict":
            grade_config = {}
    except Exception:
        grade_config = {}
    return (grade_config_path, grade_config)

def grade_pkg(window, pkg, star):
    pkg_name = pkg[0]
    grade_config = get_grade_config()[1]

    current_time = time.time()
    if not grade_config.has_key(pkg_name) or (current_time - grade_config[pkg_name]) > ONE_DAY_SECONDS:
        show_tooltip(window, _("Sending rating..."))
        SendVote(pkg_name, star, pkg[1]).start()

    else:
        show_tooltip(window, _("You have already scored.  ;)"))

def vote_send_success_callback(infos, window):
    pkg_name = infos[0]
    grade_config_path, grade_config = get_grade_config()

    global_event.emit("show-message", _("Rated successfully. Thanks for your involvement."), 5000)
    tool_tip.hide_all()
    current_time = time.time()

    grade_config[pkg_name] = current_time
    write_file(grade_config_path, str(grade_config))
    if infos[1] != None:
        obj = infos[1]
        star = float(infos[2][pkg_name][0])
        if isinstance(obj, StarView):
            obj.set_star_level(int(star))
        elif isinstance(obj, DscStarBuffer):
            obj.update_star(star)

def vote_send_failed_callback(pkg_name, window):

    global_event.emit('show-message', _("Rating failed. Please check your network connection!"))
    tool_tip.hide_all()

def show_tooltip(window, message):
    global tooltip_timeout_id
    tool_tip.set_text(message)
    (screen, px, py, modifier_type) = window.get_display().get_pointer()
    tool_tip.show_all()
    tool_tip.move(px, py)
    #show-pkg-name-tooltip
    if tooltip_timeout_id:
        gobject.source_remove(tooltip_timeout_id)
    tooltip_timeout_id = gtk.timeout_add(2000, tool_tip.hide_all)
    gtk.timeout_add(2000, tool_tip.hide_all)

def switch_from_detail_page(page_switcher, detail_page, page_box):
    page_switcher.slide_to_page(page_box, "left")

def switch_to_detail_page(page_switcher, detail_page, pkg_name):
    log("start switch to detail_page")
    page_switcher.slide_to_page(detail_page, "right")
    # ThreadMethod(detail_page.update_pkg_info, (pkg_name,)).start()
    detail_page.update_pkg_info(pkg_name)
    log("end switch to detail_page")
    global_event.emit("update-current-status-pkg-page", detail_page)

def switch_page(page_switcher, page_box, page, detail_page):
    log("slide to page")
    if page_switcher.active_widget == detail_page:
        page_switcher.slide_to_page(page_box, "left")
    else:
        page_switcher.slide_to_page(page_box, "right")

    log("remove widgets from page_box")
    container_remove_all(page_box)

    log("page_box pack widgets")
    page_box.pack_start(page, True, True)

    log("page_box show all")
    page_box.show_all()

    log("init widget in page_box")
    if isinstance(page, HomePage):
        log("page.recommend_item.show_page()")
        page.recommend_item.show_page()

        log("page.category_view.select_first_item()")
        page.category_view.select_first_item()
    #elif isinstance(page, UpgradePage):
        #page.fetch_upgrade_info()
        #if page.in_no_notify_page:
            #page.show_init_page()

def message_handler(messages, bus_interface, upgrade_page, uninstall_page, install_page, home_page, inhibit_obj):
    for message in messages:
        try:
            (signal_type, action_content) = message

            if signal_type == "ready-download-start":
                (pkg_name, action_type) = action_content
                if action_type == ACTION_INSTALL:
                    install_page.download_ready(pkg_name)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.download_ready(pkg_name)

            elif signal_type == 'ready-download-finish':
                (pkg_name, action_type) = action_content
                if action_type == ACTION_INSTALL:
                    install_page.download_wait(pkg_name)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.download_wait(pkg_name)

            elif signal_type == 'pkgs-not-in-cache':
                (not_in_cache, action_type) = action_content
                global_logger.error("pkgs-not-in-cache:%s, action_type:%s" % (not_in_cache, action_type))
                if action_type == ACTION_INSTALL:
                    pass
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.upgrading_view.show_error("pkgs_not_in_cache", json.loads(not_in_cache))

            elif signal_type == 'pkgs-mark-failed':
                (pkg_list, action_type) = action_content
                global_logger.error("pkgs-mark-failed:%s, action_type:%s" % (pkg_list, action_type))
                if action_type == ACTION_INSTALL:
                    pass
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.upgrading_view.show_error("pkgs_mark_failed", pkg_list)

            elif signal_type == 'remove-pkgs-in-white-list':
                if action_type == ACTION_UPGRADE:
                    (pkgs, action_type) = action_content
                    global_logger.error("marked-delete-system-pkgs:%s, action_type:%s" % (pkgs, action_type))
                    upgrade_page.upgrading_view.show_error("marked_delete_system_pkgs", json.loads(pkgs))

            elif signal_type == 'pkgs-parse-download-error':
                (error, action_type) = action_content
                global_logger.error("pkgs-parse-download-error:%s, action_type:%s" % (error, action_type))
                if action_type == ACTION_INSTALL:
                    pass
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.upgrading_view.show_error("pkgs_parse_download_error", error)

            elif signal_type == "download-start":
                (pkg_name, action_type) = action_content
                if action_type == ACTION_INSTALL:
                    install_page.download_start(pkg_name)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.download_start(pkg_name)

            elif signal_type == "download-update":
                (pkg_name, action_type, data) = action_content
                (percent, speed, finish_number, total, downloaded_size, total_size) = data
                if action_type == ACTION_INSTALL:
                    install_page.download_update(pkg_name, percent, speed)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.download_update(pkg_name, percent, speed, finish_number, total, downloaded_size, total_size)

            elif signal_type == "download-finish":
                (pkg_name, action_type) = action_content
                if action_type == ACTION_INSTALL:
                    install_page.download_finish(pkg_name)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.download_finish(pkg_name)

            elif signal_type == "download-stop":
                (pkg_name, action_type) = action_content
                if action_type == ACTION_INSTALL:
                    install_page.download_stop(pkg_name)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.download_stop(pkg_name)

            elif signal_type == "download-failed":
                (pkg_name, action_type, error) = action_content
                global_logger.error("download-failed:%s, action_type:%s" % (error, action_type))
                if action_type == ACTION_INSTALL:
                    install_page.download_failed(pkg_name)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.download_failed(pkg_name, error)

            elif signal_type == "action-start":
                (pkg_name, action_type) = action_content
                if action_type == ACTION_UNINSTALL:
                    uninstall_page.action_start(pkg_name)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.action_start(pkg_name)
                elif action_type == ACTION_INSTALL:
                    install_page.action_start(pkg_name)
                inhibit_obj.set_inhibit()

            elif signal_type == "action-update":
                (pkg_name, action_type, percent, status) = action_content
                if action_type == ACTION_UNINSTALL:
                    uninstall_page.action_update(pkg_name, percent)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.action_update(pkg_name, percent, utils.l18n_status_info(status))
                elif action_type == ACTION_INSTALL:
                    install_page.action_update(pkg_name, percent)

            elif signal_type == "action-finish":
                (pkg_name, action_type, pkg_info_list) = action_content
                if action_type == ACTION_UNINSTALL:
                    uninstall_page.action_finish(pkg_name, pkg_info_list)
                    utils.show_notify(_("Uninstall %s Successfully.") % pkg_name, _("Uninstall"))
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.action_finish(pkg_name, pkg_info_list)
                    global_event.emit("upgrade-finish-action", pkg_info_list)
                    utils.set_last_upgrade_time()
                    upgrade_page.refresh_status(pkg_info_list)
                    utils.show_notify(_("%s packages upgrade successfully.") % len(pkg_info_list), _("Upgrade"))
                elif action_type == ACTION_INSTALL:
                    install_page.action_finish(pkg_name, pkg_info_list)
                    utils.show_notify(_("Install %s Successfully.") % pkg_name, _("Install"))
                inhibit_obj.unset_inhibit()

                refresh_current_page_status(pkg_name, pkg_info_list, bus_interface)
                if action_type != ACTION_UPGRADE:
                    bus_interface.request_status(
                            reply_handler=lambda reply: request_status_reply_hander(
                                reply, install_page, upgrade_page, uninstall_page, pkg_info_list),
                            error_handler=lambda e: action_finish_handle_dbus_error(pkg_info_list),
                            )

            elif signal_type == 'action-failed':
                # FIXME: change failed action dealing
                (pkg_name, action_type, pkg_info_list, errormsg) = action_content
                pkg_list = [str(info[0]) for info in pkg_info_list]
                global_logger.error("action-failed:%s, action_type:%s, pkg_list: %s" % (errormsg, action_type, pkg_list))
                if action_type == ACTION_UNINSTALL:
                    uninstall_page.action_finish(pkg_name, pkg_info_list)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.upgrading_view.show_error("upgrade_failed", errormsg)
                    utils.set_last_upgrade_time()
                elif action_type == ACTION_INSTALL:
                    install_page.action_finish(pkg_name, pkg_info_list)
                inhibit_obj.unset_inhibit()

                refresh_current_page_status(pkg_name, pkg_info_list, bus_interface)
                bus_interface.request_status(
                        reply_handler=lambda reply: request_status_reply_hander(
                            reply, install_page, upgrade_page, uninstall_page),
                        error_handler=lambda e:handle_dbus_error("request_status", e),
                        )

            elif signal_type == "update-list-update":
                percent = "[%i%%] " % float(action_content[0])
                status = str(action_content[1])
                speed_str = str(action_content[2])
                status = utils.update_l18n_status_info(status)

                list_message = []
                list_message.append(percent + status)
                list_message.append(speed_str)
                global_event.emit("show-message", list_message)

            elif signal_type == "update-list-merge":
                global_event.emit("show-message", [_("Generating package list database..."), ''], 0)

            elif signal_type == "update-list-finish":
                upgrade_page.fetch_upgrade_info()
                bus_interface.request_status(
                        reply_handler=lambda reply: request_status_reply_hander(reply, install_page, upgrade_page, uninstall_page),
                        error_handler=lambda e:handle_dbus_error("request_status", e),
                        )
                global_event.emit("show-message", [_("Package lists refreshed completely."), ''], 5000)
                global_event.emit('update-list-finish')
                global_event.emit("hide-update-list-dialog")

            elif signal_type == 'update-list-failed':
                # FIXME: change failed action dealing
                upgrade_page.fetch_upgrade_info()
                bus_interface.request_status(
                        reply_handler=lambda reply: request_status_reply_hander(reply, install_page, upgrade_page, uninstall_page),
                        error_handler=lambda e:handle_dbus_error("request_status", e),
                        )
                list_message = []
                list_message.append(_("Failed to refresh package lists."))
                list_message.append(_('Try again'))
                list_message.append(lambda:global_event.emit('start-update-list'))
                global_event.emit("show-message", list_message, 0)
                global_event.emit('update-list-finish')
                global_event.emit("hide-update-list-dialog")

            elif signal_type == "parse-download-error":
                (pkg_name, action_type) = action_content
                if action_type == ACTION_INSTALL:
                    install_page.download_parse_failed(pkg_name)
                    global_event.emit("show-message", _("Problem occurred when analyzing dependencies for %s. Installation aborted.") % pkg_name)
                elif action_type == ACTION_UPGRADE:
                    upgrade_page.download_parse_failed(pkg_name)
                    global_event.emit("show-message", _("Problem occurred when analyzing dependencies for %s. Upgrade aborted.") % pkg_name)

            elif signal_type == "pkg-not-in-cache":
                pkg_name = action_content
                list_message = []
                list_message.append(_('The requested package \"%s\" was not found in the package list.') % pkg_name)
                list_message.append(_('Refresh package lists again and try again.'))
                list_message.append(lambda:global_event.emit('start-update-list'))
                global_event.emit("show-message", list_message, 0)
        except Exception, e:
            traceback.print_exc(file=sys.stdout)
            print "Message Handler Error:", e

    return True

install_stop_list = []
def request_stop_install_actions(pkg_names):
    global install_stop_list

    install_stop_list += pkg_names

def clear_install_stop_list(install_page):
    global install_stop_list

    if len(install_stop_list) > 0:
        for pkg_name in install_stop_list:
            for item in install_page.treeview.visible_items:
                if item.pkg_name == pkg_name:
                    install_page.treeview.delete_items([item])
                    break

        install_stop_list = []

    return True

def install_pkg(bus_interface, install_page, pkg_names, window):
    for install_item in install_page.treeview.visible_items:
        if install_item.pkg_name in pkg_names and install_item.status != install_item.STATUS_DOWNLOAD_FAILED:
            pkg_names.remove(install_item.pkg_name)
    if pkg_names == []:
        return

    # Add install animation.
    (screen, px, py, modifier_type) = window.get_display().get_pointer()
    ax, ay = px, py

    (wx, wy) = window.window.get_origin()
    offset_bx = 430
    offset_by = -20
    bx, by = wx + offset_bx, wy + offset_by

    offset_cx = 10
    offset_cy = 10
    if ax < bx:
        cx, cy = wx + offset_bx + offset_cx, wy + offset_by + offset_cy
    else:
        cx, cy = wx + offset_bx - offset_cx, wy + offset_by + offset_cy

    [[a], [b], [c]] = solve_parabola((ax, ay), (bx, by), (cx, cy))

    icon_window = IconWindow(pkg_names[0])
    icon_window.move(ax, ay)
    icon_window.show_all()

    timeline = Timeline(500, CURVE_SINE)
    timeline.connect("update", lambda source, status: update(source, status, icon_window, (ax, ay), (bx, by), (cx, cy), (a, b, c)))
    timeline.connect("completed", lambda source: finish(source, icon_window, bus_interface, pkg_names))
    timeline.run()

    # Add to install page.
    #install_page.add_install_actions(pkg_names)


def update(source, status, icon_window, (ax, ay), (bx, by), (cx, cy), (a, b, c)):
    move_x = ax + (cx - ax) * status
    move_y = a * pow(move_x, 2) + b * move_x + c

    icon_window.move(int(move_x), int(move_y))
    icon_window.show_all()

def finish(source, icon_window, bus_interface, pkg_names):
    icon_window.destroy()

    # Send install command.
    create_thread(lambda : bus_interface.install_pkg(
                                pkg_names,
                                reply_handler=lambda :handle_dbus_reply("install_pkg"),
                                error_handler=lambda e:handle_dbus_error("install_pkg", e))).start()
    for pkg_name in pkg_names:
        SendDownloadCount(pkg_name).start()

clear_failed_action_dict = {
    ACTION_INSTALL : [],
    ACTION_UPGRADE : [],
    }
def request_clear_failed_action(pkg_name, action_type):
    global clear_failed_action_dict

    if action_type == ACTION_INSTALL:
        clear_failed_action_dict[ACTION_INSTALL].append(pkg_name)
    elif action_type == ACTION_UPGRADE:
        clear_failed_action_dict[ACTION_UPGRADE].append(pkg_name)

def clear_failed_action(install_page, upgrade_page):
    global clear_failed_action_dict

    install_items = []
    upgrade_items = []

    for pkg_name in clear_failed_action_dict[ACTION_INSTALL]:
        for item in install_page.treeview.visible_items:
            if item.pkg_name == pkg_name:
                install_items.append(item)

    for pkg_name in clear_failed_action_dict[ACTION_UPGRADE]:
        for item in upgrade_page.upgrade_treeview.visible_items:
            if item.pkg_name == pkg_name:
                upgrade_items.append(item)

    install_page.treeview.delete_items(install_items)
    upgrade_page.upgrade_treeview.delete_items(upgrade_items)

    clear_failed_action_dict = {
        ACTION_INSTALL : [],
        ACTION_UPGRADE : [],
        }

    return True

clear_action_list = []
def request_clear_action_pages(pkg_info_list):
    global clear_action_list

    clear_action_list += pkg_info_list

def clear_action_pages(bus_interface, upgrade_page, uninstall_page, install_page):
    global clear_action_list

    if len(clear_action_list) > 0:
        # Delete items from treeview.
        installed_items = []
        uninstalled_items = []
        upgraded_items = []
        install_pkgs = []

        for (pkg_name, marked_delete, marked_install, marked_upgrade) in clear_action_list:
            if marked_delete:
                for item in uninstall_page.treeview.visible_items:
                    if item.pkg_name == pkg_name:
                        uninstalled_items.append(item)
                        break
            elif marked_install:
                for item in install_page.treeview.visible_items:
                    if item.pkg_name == pkg_name:
                        installed_items.append(item)

                        install_pkgs.append(pkg_name)
                        break
            elif marked_upgrade:
                for item in upgrade_page.upgrade_treeview.visible_items:
                    if item.pkg_name == pkg_name:
                        upgraded_items.append(item)

                        install_pkgs.append(pkg_name)
                        break
        clear_action_list = []

        uninstall_page.delete_uninstall_items(uninstalled_items)
        install_page.update_install_status()
        upgrade_page.upgrade_treeview.delete_items(upgraded_items)

        # Add installed package in uninstall page.
        for item in uninstall_page.treeview.visible_items:
            if item.pkg_name in install_pkgs:
                install_pkgs.remove(item.pkg_name)

        install_pkg_versions = bus_interface.request_pkgs_install_version(install_pkgs)
        install_pkg_infos = []
        for (pkg_name, pkg_version) in zip(install_pkgs, install_pkg_versions):
            install_pkg_infos.append([pkg_name, pkg_version])
        uninstall_page.add_uninstall_items(json.dumps(install_pkg_infos), True)

    return True

def action_finish_handle_dbus_error(pkg_info_list):
    if pkg_info_list:
        global_event.emit("request-clear-action-pages", pkg_info_list)

debug_flag = False

class DeepinSoftwareCenter(dbus.service.Object):
    '''
    class docs
    '''

    pages = ['home', 'upgrade', 'uninstall', 'install']

    def __init__(self, session_bus, arguments):
        '''
        init docs
        '''
        dbus.service.Object.__init__(self, session_bus, DSC_FRONTEND_PATH)

        self.simulate = "--simulate" in arguments

        global debug_flag
        debug_flag = "--debug" in arguments
        self.in_wizard_showing = False
        self.init_hide = False

    def exit(self):
        gtk.main_quit()

    def open_download_directory(self):
        run_command("xdg-open %s" % get_software_download_dir())

    def switch_page(self, page):
        switch_page(self.page_switcher, self.page_box, page, self.detail_page)

    def show_home_page(self):
        if self.detail_page and self.home_page:
            self.switch_page(self.home_page)

    def show_upgrade_page(self):
        if self.detail_page and self.upgrade_page:
            self.switch_page(self.upgrade_page)

    def show_uninstall_page(self):
        if self.detail_page and self.uninstall_page:
            self.switch_page(self.uninstall_page)

    def show_install_page(self):
        if self.detail_page and self.install_page:
            self.switch_page(self.install_page)

    @dbus.service.method(DSC_FRONTEND_NAME, in_signature="s", out_signature="")
    def show_page(self, key):
        try:
            index = self.pages.index(key)
            if index != self.navigatebar.get_index():
                method = "show_%s_page" % key
                getattr(self, method)()
                self.navigatebar.set_index(index)
        except:
            print "Unknow page:", key

    @dbus.service.method(DSC_FRONTEND_NAME, in_signature="s", out_signature="")
    def show_detail(self, pkg_name):
        global_event.emit("switch-to-detail-page", pkg_name)

    def init_ui(self):
        global_logger.info("Init ui")
        # Init application.
        self.application = Application(
            resizable=False,
            destroy_func=self.application_close_window,
            )
        self.application.set_default_size(888, 634)
        self.application.set_skin_preview(utils.get_common_image("frame.png"))
        self.application.set_icon(utils.get_common_image("logo48.png"))
        self.application.add_titlebar(
                ["theme", "menu", "min", "close"],
                show_title=False
                )
        self.application.window.set_title(_("Deepin Store"))
        self.application.window.connect("delete-event", self.application_close_window)

        # Init page box.
        self.page_box = gtk.VBox()

        # Init page switcher.
        self.page_switcher = HSlider(200)
        self.page_switcher.append_page(self.page_box)
        self.page_switcher.set_to_page(self.page_box)

        # Init page align.
        self.page_align = gtk.Alignment()
        self.page_align.set(0.5, 0.5, 1, 1)
        self.page_align.set_padding(0, 0, 2, 2)

        # Append page to switcher.
        self.paned_box = PanedBox(24)
        self.paned_box.add_content_widget(self.page_switcher)
        self.bottom_tip_bar = BottomTipBar()
        self.bottom_tip_bar.close_button.connect('clicked', lambda w: self.paned_box.bottom_window.hide())
        self.paned_box.add_bottom_widget(self.bottom_tip_bar)
        self.page_align.add(self.paned_box)
        self.application.main_box.pack_start(self.page_align, True, True)

        # Init status bar.
        self.statusbar = Statusbar(24)
        status_box = gtk.HBox()
        self.message_box = gtk.HBox()

        self.message_label = Label("", enable_gaussian=True)
        label_align = gtk.Alignment()
        label_align.set(0.0, 0.5, 0, 0)
        label_align.set_padding(0, 0, 10, 0)
        label_align.add(self.message_label)
        self.message_box.pack_start(label_align)

        join_us_button = LinkButton(_("Join us"), "http://www.linuxdeepin.com/joinus/job")
        join_us_button_align = gtk.Alignment()
        join_us_button_align.set(0.5, 0.5, 0, 0)
        join_us_button_align.set_padding(0, 3, 0, 10)
        join_us_button_align.add(join_us_button)
        status_box.pack_start(self.message_box, True, True)
        status_box.pack_start(join_us_button_align, False, False)
        self.statusbar.status_box.pack_start(status_box, True, True)
        self.application.main_box.pack_start(self.statusbar, False, False)

        # Init navigatebar.
        self.detail_page = None
        self.home_page = None
        self.upgrade_page = None
        self.uninstall_page = None
        self.install_page = None

        self.navigatebar = Navigatebar(
                [
                (DynamicPixbuf(utils.get_common_image("navigatebar/nav_home.png")), _("Home"), self.show_home_page),
                (DynamicPixbuf(utils.get_common_image("navigatebar/nav_update.png")), _("Upgrade"), self.show_upgrade_page),
                (DynamicPixbuf(utils.get_common_image("navigatebar/nav_uninstall.png")), _("Uninstall"), self.show_uninstall_page),
                (DynamicPixbuf(utils.get_common_image("navigatebar/nav_download.png")), _("Installation"), self.show_install_page),
                ],
                font_size = 11,
                padding_x = 2,
                padding_y = 2,
                vertical=False,
                item_hover_pixbuf=DynamicPixbuf(utils.get_common_image("navigatebar/nav_hover.png")),
                item_press_pixbuf=DynamicPixbuf(utils.get_common_image("navigatebar/nav_press.png")),
                )
        self.navigatebar.set_size_request(-1, 56)
        self.navigatebar_align = gtk.Alignment(0, 0, 1, 1)
        self.navigatebar_align.set_padding(0, 0, 4, 0)
        self.navigatebar_align.add(self.navigatebar)
        self.application.titlebar.set_size_request(-1, 56)
        self.application.titlebar.left_box.pack_start(self.navigatebar_align, True, True)
        self.application.window.add_move_event(self.navigatebar)

        # Init menu.
        if LANGUAGE == 'en_US':
            menu_min_width = 185
        else:
            menu_min_width = 150
        menu = Menu(
            [
             (None, _("Refresh package lists"), lambda:global_event.emit('start-update-list')),
             (None, _("Open download directory"), self.open_download_directory),
             (None, _("Clear up cached packages"), self.clean_download_cache),
             #(None, _("View new features"), lambda : self.show_wizard_win()),
             (self.get_pixbuf_group("menu", "setting"), _("Preferences"), self.show_preference_dialog),
             (self.get_pixbuf_group("menu", "close"), _("Quit"), self.exit),
             ],
            is_root_menu=True,
            menu_min_width=menu_min_width,
            )
        self.application.set_menu_callback(
            lambda button:
                menu.show(
                get_widget_root_coordinate(button, WIDGET_POS_BOTTOM_LEFT),
                (button.get_allocation().width, 0)))


        if hasattr(self, 'recommend_status'):
            self.init_home_page(self.recommend_status)
        else:
            self.init_home_page()

    def get_pixbuf_group(self, folder, name):
        return (app_theme.get_pixbuf("%s/%s_normal.png" % (folder, name)),
                app_theme.get_pixbuf("%s/%s_hover.png" % (folder, name)),
                app_theme.get_pixbuf("%s/%s_disable.png" % (folder, name)),
                )

    def application_close_window(self, widget=None, event=None):
        self.application.window.hide_all()
        gtk.main_quit()

        return True

    def upgrade_finish_action(self, pkg_info_list):
        return
        """
        if len(pkg_info_list) > 0:
            # Delete items from treeview.
            upgraded_items = []

            for (pkg_name, marked_delete, marked_install, marked_upgrade) in pkg_info_list:
                for item in self.upgrade_page.upgrade_treeview.visible_items:
                    if item.pkg_name == pkg_name:
                        upgraded_items.append(item)
                        break

            print upgraded_items
            self.upgrade_page.upgrade_treeview.delete_items(upgraded_items)
            print len(self.upgrade_page.upgrade_treeview.visible_items)
        """

    def show_preference_dialog(self):
        self.preference_dialog.show_all()

    def ready_show(self):
        self.preference_dialog = DscPreferenceDialog()
        if utils.is_first_started():
            self.in_wizard_showing = True
            if len(all_mirrors) > 0:
                self.show_test_mirror(callback=self.wizard_callback)
            else:
                self.show_wizard_win(callback=self.wizard_callback)
            utils.set_first_started()
            self.init_ui()
        else:
            self.init_ui()
            if not self.init_hide:
                self.application.window.show_all()
        #self.paned_box.bottom_window.set_composited(True)

    def show_test_mirror(self, callback=None):
        if callback:
            self.preference_dialog.waiting_dialog.hide_callback = callback
        mirrors_box = self.preference_dialog.mirrors_box
        mirrors_box.select_best_mirror(mirrors_box.select_best_mirror_button)

    def show_wizard_win(self, show_button=False, callback=None):
        program_dir = get_parent_dir(__file__, 2)
        wizard_dir = os.path.join(program_dir, 'wizard', LANGUAGE)
        if not os.path.exists(wizard_dir):
            wizard_dir = os.path.join(program_dir, 'wizard', 'en_US')
        wizard_root_dir = os.path.dirname(wizard_dir)

        self.wizard = Wizard(
            [os.path.join(wizard_dir, "%d.png" % i) for i in range(3)],
            (os.path.join(wizard_root_dir, "dot_normal.png"),
             os.path.join(wizard_root_dir, "dot_active.png"),
             ),
            (os.path.join(wizard_dir, "start_normal.png"),
             os.path.join(wizard_dir, "start_press.png"),
             ),
            show_button,
            callback
            )
        self.wizard.set_icon(utils.get_common_image_pixbuf("logo48.png"))
        if not self.init_hide:
            self.wizard.show_all()

    def wizard_callback(self):
        self.in_wizard_showing = False
        self.application.window.show_all()
        gtk.timeout_add(200, self.application.raise_to_top)

    def init_home_page(self, recommend_status="publish"):

        # Init DBus.
        self.system_bus = dbus.SystemBus()
        bus_object = self.system_bus.get_object(DSC_SERVICE_NAME, DSC_SERVICE_PATH)
        self.bus_interface = dbus.Interface(bus_object, DSC_SERVICE_NAME)
        # Say hello to backend.
        #self.bus_interface.say_hello(self.simulate)
        self.set_software_download_dir()
        self.inhibit_obj = InhibitObject()

        global_logger.info("Init data manager")

        # Init data manager.
        self.data_manager = DataManager(self.bus_interface, debug_flag)

        # Init packages status
        self.packages_status = {}

        # Init home page.
        self.home_page = HomePage(self.data_manager, recommend_status)

        # Init switch page.
        self.switch_page(self.home_page)

        self.in_update_list = False

        self.init_backend()

    def init_backend(self):

        # Init detail view.
        self.detail_page = DetailPage(self.data_manager)

        self.page_switcher.append_page(self.detail_page)

        log("Init pages.")

        global_logger.info("Init pages")
        self.upgrade_page = UpgradePage(self.bus_interface, self.data_manager, self.preference_dialog)
        self.uninstall_page = UninstallPage(self.bus_interface, self.data_manager)
        self.install_page = InstallPage(self.bus_interface, self.data_manager)


        log("Handle global event.")

        # Handle global event.
        global_event.register_event("install-pkg", lambda pkg_names: install_pkg(
            self.bus_interface, self.install_page, pkg_names, self.application.window))
        global_event.register_event("upgrade-pkg", self.upgrade_pkgs)
        global_event.register_event("uninstall-pkg", lambda pkg_name, purge_flag: self.uninstall_pkg(pkg_name, purge_flag))
        global_event.register_event("stop-download-pkg", self.bus_interface.stop_download_pkg)
        global_event.register_event("switch-to-detail-page", lambda pkg_name : switch_to_detail_page(self.page_switcher, self.detail_page, pkg_name))
        global_event.register_event("switch-from-detail-page", lambda : switch_from_detail_page(self.page_switcher, self.detail_page, self.page_box))
        global_event.register_event("remove-wait-action", self.bus_interface.RemoveWaitMissions)
        global_event.register_event("remove-wait-download", self.bus_interface.remove_wait_downloads)
        global_event.register_event("request-clear-action-pages", request_clear_action_pages)
        global_event.register_event("request-stop-install-actions", request_stop_install_actions)
        global_event.register_event("request-clear-failed-action", request_clear_failed_action)
        global_event.register_event("update-upgrade-notify-number", lambda number: update_navigatebar_number(self.navigatebar, 1, number))
        global_event.register_event("update-install-notify-number", lambda number: update_navigatebar_number(self.navigatebar, 3, number))
        global_event.register_event("jump-to-category",
                                    lambda first_category_name, second_category_name:
                                    jump_to_category(self.page_switcher,
                                                     self.page_box,
                                                     self.home_page,
                                                     self.detail_page,
                                                     first_category_name,
                                                     second_category_name))
        global_event.register_event("grade-pkg", lambda pkg, star: grade_pkg(self.application.window, pkg, star))
        global_event.register_event("set-cursor", lambda cursor: set_cursor(self.application.window, cursor))
        global_event.register_event("show-message", self.update_status_bar_message)
        global_event.register_event("start-pkg", lambda alias_name, desktop_infos, offset: start_pkg(
            alias_name, desktop_infos, offset, self.application.window))
        global_event.register_event("show-pkg-name-tooltip", lambda pkg_name: show_tooltip(self.application.window, pkg_name))
        global_event.register_event("hide-pkg-name-tooltip", lambda :tool_tip.hide())
        global_event.register_event("update-current-status-pkg-page", update_current_status_pkg_page)
        global_event.register_event('start-change-mirror', self.change_mirror_action)
        global_event.register_event('download-directory-changed', self.set_software_download_dir)
        global_event.register_event('vote-send-success', lambda p: vote_send_success_callback(p, self.application.window))
        global_event.register_event('vote-send-failed', lambda p: vote_send_failed_callback(p, self.application.window))
        global_event.register_event('max-download-number-changed', self.init_download_manager)
        global_event.register_event('update-list-finish', self.update_list_finish)
        global_event.register_event('start-update-list', self.update_list_handler)
        global_event.register_event("upgrade-finish-action", self.upgrade_finish_action)
        global_event.register_event("upload-error-log", self.exec_upload_error_log)

        self.bus_interface.connect_to_signal(
                signal_name="update_signal",
                handler_function=lambda messages: message_handler(messages,
                                         self.bus_interface,
                                         self.upgrade_page,
                                         self.uninstall_page,
                                         self.install_page,
                                         self.home_page,
                                         self.inhibit_obj,
                                         ),
                )
        glib.timeout_add(1000, lambda : clear_action_pages(self.bus_interface, self.upgrade_page, self.uninstall_page, self.install_page))
        glib.timeout_add(1000, lambda : clear_install_stop_list(self.install_page))
        glib.timeout_add(1000, lambda : clear_failed_action(self.install_page, self.upgrade_page))

        #self.init_download_manager()

        #self.request_update_list()
        self.upgrade_page.fetch_upgrade_info(utils.get_backend_running())

    def change_mirror_action(self, mirror):
        repo_urls = mirror.get_repo_urls()
        self.bus_interface.change_source_list(
            repo_urls,
            reply_handler=lambda :self.handle_mirror_change_reply(mirror),
            error_handler=lambda e:handle_dbus_error("change_source_list", e)
            )

    def exec_upload_error_log(self):
        SendErrorLog().start()

    @dbus.service.method(DSC_FRONTEND_NAME, in_signature="sb", out_signature="")
    def uninstall_pkg(self, pkg_name, purge_flag):
        self.bus_interface.uninstall_pkg(pkg_name, purge_flag,
                reply_handler=lambda :handle_dbus_reply("uninstall_pkg"),
                error_handler=lambda e:handle_dbus_error("uninstall_pkg", e))
        SendUninstallCount(pkg_name).start()

        self.install_page.delete_item_match_pkgname(pkg_name)

    def init_download_manager(self, v=5):
        self.bus_interface.init_download_manager(
                v,
                reply_handler=lambda :self.init_download_manager_handler(),
                error_handler=lambda e:handle_dbus_error("init_download_manager", e))

    def init_download_manager_handler(self):
        self.dbus_request_status()
        global_logger.info("Init download manager")

    def dbus_request_status(self):
        self.bus_interface.request_status(
            reply_handler=lambda reply: request_status_reply_hander(reply, self.install_page, self.upgrade_page, self.uninstall_page),
            error_handler=lambda e:handle_dbus_error("request_status", e),
            )

    def set_software_download_dir(self):
        self.bus_interface.set_download_dir(
                get_software_download_dir(),
                reply_handler=lambda :handle_dbus_reply("set_download_dir"),
                error_handler=lambda e:handle_dbus_error("set_download_dir", e))

    def update_list_handler(self):
        self.show_page("upgrade")
        if not self.in_update_list:
            self.request_update_list()
            global_event.emit('show-updating-view')

    def update_list_finish(self):
        try:
            self.hide_dialog('update_list_dialog')
        except:
            pass
        self.in_update_list = False
        self.data_manager.init_cache_soft_db()

    def hide_dialog(self, name):
        getattr(self, name).hide_all()

    def show_dialog(self, name):
        getattr(self, name).show_all()

    def handle_mirror_change_reply(self, mirror):
        global_event.emit("mirror-backend-changed", mirror)

    def update_status_bar_message(self, message, hide_timeout=0):
        if not self.paned_box.bottom_window.is_visible():
            self.paned_box.bottom_window.show()
        if isinstance(message, list) and len(message) == 4:
            self.bottom_tip_bar.update_info(message[0], message[2], message[3])
            self.bottom_tip_bar.update_end_info(message[1])
        elif isinstance(message, list) and len(message) == 3:
            self.bottom_tip_bar.update_info(*message)
            self.bottom_tip_bar.update_end_info("")
        elif isinstance(message, list) and len(message) == 2:
            self.bottom_tip_bar.update_info(message[0])
            self.bottom_tip_bar.update_end_info(message[1])
        else:
            self.bottom_tip_bar.update_info(message)
            self.bottom_tip_bar.update_end_info("")
        if hide_timeout != 0:
            gtk.timeout_add(hide_timeout, lambda:self.paned_box.bottom_window.hide())

    def request_update_list(self):
        self.in_update_list = True
        self.bus_interface.start_update_list(
                reply_handler=lambda :handle_dbus_reply("start_update_list"),
                error_handler=lambda e:handle_dbus_error("start_update_list", e),)

    def upgrade_pkgs(self, pkg_names):
        self.bus_interface.DistUpgrade(
                pkg_names,
                reply_handler=lambda :handle_dbus_reply("upgrade_pkgs"),
                error_handler=lambda e:handle_dbus_error("upgrade_pkgs", e))
        return False

    def clean_download_cache(self):
        self.bus_interface.clean_download_cache(
                reply_handler=self.clean_download_cache_reply,
                error_handler=lambda e:handle_dbus_error("clean_download_cache", e),
                )

    def clean_download_cache_reply(obj, result):
        num, size = result
        if num != 0:
            message = _("You have cleared up %s packages and saved %s of space.") % (num, bit_to_human_str(size))
        else:
            message = _("Your system cache is empty.")
        global_event.emit("show-message", message, 5000)

    def run(self):
        self.ready_show()
        gtk.main()

        # Send exit request to backend when frontend exit.
        self.bus_interface.request_quit(
                reply_handler=lambda :handle_dbus_reply("request_quit"),
                error_handler=lambda e:handle_dbus_error("request_quit", e))

        # Remove id from config file.
        data_exit()
        global_logger.info('Data id removed')

    @dbus.service.method(DSC_FRONTEND_NAME, in_signature="", out_signature="")
    def request_exit(self):
        self.exit()
        self.bus_interface.request_quit(
                reply_handler=lambda :handle_dbus_reply("request_quit"),
                error_handler=lambda e:handle_dbus_error("request_quit", e))
        data_exit()
        global_logger.info('Data id removed')

    @dbus.service.method(DSC_FRONTEND_NAME, in_signature="as", out_signature="")
    def install_pkgs(self, pkg_names):
        for pkg_name in pkg_names:
            self.install_page.download_wait(pkg_name)
        create_thread(lambda : self.bus_interface.install_pkg(
                                    pkg_names,
                                    reply_handler=lambda :handle_dbus_reply("install_pkg"),
                                    error_handler=lambda e:handle_dbus_error("install_pkg", e))).start()
        for pkg_name in pkg_names:
            SendDownloadCount(pkg_name).start()

    @dbus.service.method(DSC_FRONTEND_NAME, in_signature="", out_signature="")
    def raise_to_top(self):
        if not self.in_wizard_showing:
            self.application.window.show_all()
            self.application.raise_to_top()
        else:
            self.wizard.present()

    @dbus.service.signal(DSC_FRONTEND_NAME)
    def update_signal(self, message):
        pass
