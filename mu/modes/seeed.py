"""
A mode for working with Seeed's line of  MicroPython boards.

Copyright (c) 2015-2019 Nicholas H.Tollervey and others (see the AUTHORS file).

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import logging
import time
import json
import wget
import datetime
import os
import subprocess
import shutil
from serial import Serial
from mu.modes.api import SEEED_APIS, SHARED_APIS
from mu.modes.base import MicroPythonMode, FileManager
from mu.interface.themes import Font, DEFAULT_FONT_SIZE
from mu.interface.panes import CHARTS, \
    MicroPythonDeviceFileList, FileSystemPane, PANE_ZOOM_SIZES
from PyQt5.QtCore import pyqtSignal, QThread, Qt
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo
from PyQt5.QtWidgets import QMessageBox, QFrame, QGridLayout, \
    QLabel, QMenu, QTreeWidget, QTreeWidgetItem, QAbstractItemView
from PyQt5.QtGui import QIcon

logger = logging.getLogger(__name__)


class Info:
    __stty = None
    __config = None
    board_normal = []
    board_boot = []
    dic_config = {}
    board_id = None
    board_name = None

    resources_path = 'mu/resources/seeed/'
    info_path = resources_path + 'info.json'
    icon_path = resources_path + 'icon/'

    def __init__(self):
        file = open(Info.info_path, 'r')
        cfg = json.loads(file.read())
        Info.board_boot.clear()
        Info.board_normal.clear()
        Info.dic_config.clear()
        fmt = 'config-%s.json'

        for board in cfg['boot']:
            name = board['name']
            pvid = board['pvid']
            keyv = (pvid[0], pvid[1])
            Info.dic_config.setdefault(str(keyv), fmt % name)
            Info.board_boot.append(keyv)

        for board in cfg['normal']:
            name = board['name']
            pvid = board['pvid']
            keyv = (pvid[0], pvid[1])
            Info.dic_config.setdefault(str(keyv), fmt % name)
            Info.board_normal.append(keyv)

        if os.name == 'posix':
            self.__stty = 'stty -F %s 1200'
        elif os.name == 'nt':
            self.__stty = 'MODE %s:BAUD=1200'
        else:
            raise NotImplementedError('not implement stty.')
        self.__bossac = self.resources_path + \
            'bossac.exe -i -d --port=%s -U true -i -e -w -v %s -R'

    def load_config(self):
        file = open(self.config_path, 'r')
        self.__config = json.loads(file.read())

    @property
    def cloud_config_path(self):
        return 'https://seeed-studio.github.io/ArduPy/' + \
            self.dic_config[self.board_id]

    @property
    def config_path(self):
        return self.resources_path + self.dic_config[self.board_id]

    @property
    def version(self):
        return strptime(self.__config['firmware']['version'])

    @property
    def cloud_firmware(self):
        return self.__config['firmware']['path']

    @property
    def local_firmware(self):
        return self.resources_path + self.__config['firmware']['name']

    @property
    def firmware_name(self):
        return self.__config['firmware']['name']

    @property
    def short_device_name(self):
        if os.name == 'posix':
            return self.board_name[self.board_name.rindex('/') + 1:]
        else:
            return self.board_name

    @property
    def bossac(self):
        return self.__bossac % (self.short_device_name, self.local_firmware)

    @property
    def stty(self):
        return self.__stty % self.board_name


class ConfirmFlag:
    hint = None
    confirm = None


class LocalFileTree(QTreeWidget):
    put = pyqtSignal(str)
    delete = pyqtSignal(str)
    set_message = pyqtSignal(str)
    open_file = pyqtSignal(str)
    get = pyqtSignal(str, str)
    list_files = pyqtSignal()
    disable = pyqtSignal()

    def __build_list(self, control, parent_dir):
        for _, dirnames, filesnames in os.walk(parent_dir):
            dirnames.sort()
            filesnames.sort()
            for dir in dirnames:
                item = QTreeWidgetItem(control)
                item.setText(0, dir)
                item.setIcon(0, self.__icon_folder)
                item.name = dir
                item.dir = parent_dir
                item.is_file = False
                self.__build_list(item, os.path.join(parent_dir, dir))
            for file in filesnames:
                item = QTreeWidgetItem(control)
                item.setText(0, file)
                item.setIcon(0, self.__icon_firmware)
                item.name = file
                item.dir = parent_dir
                item.is_file = True
            return

    def __init__(self, home, parent=None):
        super(LocalFileTree, self).__init__(parent)
        self.home = home
        self.setStyleSheet('border:1px solid darkgray;')
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.header().setVisible(False)
        self.__icon_firmware = \
            QIcon(os.path.join(Info.icon_path, 'firmware.png'))
        self.__icon_folder = \
            QIcon(os.path.join(Info.icon_path, 'folder.png'))

    def ls(self):
        self.clear()
        self.__build_list(self, self.home)

    def on_get(self, ardupy_file):
        """
        Fired when the get event is completed for the given filename.
        """
        msg = _("Successfully copied '{}' "
                "from the ardupy to your computer.").format(ardupy_file)
        self.set_message.emit(msg)
        self.list_files.emit()

    def on_put(self, ardupy_file):
        """
        Fired when the put event is completed for the given filename.
        """
        msg = _("'{}' successfully copied to ardupy.").format(ardupy_file)
        self.set_message.emit(msg)
        self.list_files.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        delete_action = menu.addAction(_("Delete (cannot be undone)"))
        action = menu.exec_(self.mapToGlobal(event.pos()))

        if action == delete_action:
            self.disable.emit()
            item = self.currentItem()
            path = os.path.join(item.dir, item.name)

            if item.is_file:
                os.remove(path)
            else:
                shutil.rmtree(path)
            self.on_delete(item.name)

    def on_delete(self, ardupy_file):
        """
        Fired when the delete event is completed for the given filename.
        """
        msg = "'%s' successfully deleted from ardupy." % ardupy_file
        logger.info(msg)
        self.set_message.emit(msg)
        self.list_files.emit()


class ArdupyDeviceFileList(MicroPythonDeviceFileList):
    info = None

    def __init__(self, home):
        super().__init__(home)

    def dropEvent(self, event):
        source = event.source()
        item = source.currentItem()

        if not isinstance(source, LocalFileTree):
            return
        if not item.is_file:
            msg = 'Not successfuly, current version just support copy file.'
            logger.info(msg)
            self.set_message.emit(msg)
            return

        name = item.name
        path = os.path.join(item.dir, name)

        if not os.path.exists(path):
            self.set_message.emit('Sorry, ' + name +
                                  ' not exist in current folder, ' +
                                  'place reopen file panel.')
            return

        if self.findItems(name, Qt.MatchExactly) and \
                not self.show_confirm_overwrite_dialog():
            return

        self.com = Serial(self.info.board_name, 115200, timeout=1, parity='N')
        if self.com.is_open is False:
            self.com.open()
        self.com.write(b'\x03')
        self.com.write(b'\x02')
        self.com.write(b"import os\r")
        self.com.write(b"os.statvfs('/')\r")

        while True:
            try:
                back = str(self.com.readline())
                back.index("statvfs")
                back = str(self.com.readline())
                back = back.replace('\\r', '').replace('\\n', '')
                back = back[3:len(back) - 2].split(', ')
                break
            except Exception as ex:
                print(ex)
                continue

        avaliable_byte = int(back[1]) * int(back[4])
        file_size = os.path.getsize(path)

        if avaliable_byte > file_size:
            msg = "Copying '%s' to seeed board." % name
            self.disable.emit()
            self.set_message.emit(msg)
            self.put.emit(path)
        else:
            msg = "Fail! target device doesn't have enough space."
            self.set_message.emit(msg)
        logger.info(msg)


class SeeedFileSystemPane(FileSystemPane):
    def __init__(self, home):
        super().__init__(home)
        self.microbit_fs = ArdupyDeviceFileList(home)


def strptime(value):
    return datetime.datetime.strptime(value, '%Y-%m-%d')


def download(des_path, source_path, timeout=5, try_time=3):
    for i in range(0, try_time):
        try:
            if os.path.exists(des_path):
                os.remove(des_path)
            wget.download(source_path, des_path)
            print("finish download.")
            return True
        except subprocess.TimeoutExpired:
            print('download timeout.')
    return False


class FirmwareUpdater(QThread):
    show_status = pyqtSignal(str)
    confirm = pyqtSignal(ConfirmFlag)
    flashing_result = pyqtSignal(str)
    detected = False
    need_confirm = True
    hint_flashing = 'Flashing...'
    hint_flashing_success = 'Flashing success.'
    hint_flashing_fail = 'Flashing fail.'

    def __init__(self, confirm, show_status, flashing_result, parent=None):
        super(FirmwareUpdater, self).__init__(parent)
        self.confirm.connect(confirm)
        self.show_status.connect(show_status)
        self.flashing_result.connect(flashing_result)

    def run(self):
        while True:
            while not self.detected:
                time.sleep(1)
            self.info.board_name = self.info.new_board_name
            self.info.board_id = self.info.new_board_id
            self.detected = False
            self.update()

    def go_download_mode(self):
        os.system(self.info.stty)

    def flashing(self):
        return 0 == os.system(self.info.bossac)

    def on_put(self, file):
        msg = "'%s' successfully copied to seeed board." % file
        self.set_message.emit(msg)
        self.list_files.emit()

    def on_delete(self, file):
        msg = "'%s' successfully deleted from micro:bit." % file
        self.set_message.emit(msg)
        self.list_files.emit()

    def update(self):
        print("download config.")
        if os.path.exists(self.info.config_path):
            self.info.load_config()
            old_version = self.info.version
        else:
            old_version = datetime.datetime(2000, 1, 1)

        if not download(self.info.config_path, self.info.cloud_config_path):
            return None

        self.info.load_config()
        new_version = self.info.version

        if old_version < new_version or \
                not os.path.exists(self.info.local_firmware):
            print("download firmware.")
            success = download(
                self.info.local_firmware,
                self.info.cloud_firmware,
                timeout=16
            )
            if not success:
                return
            print("finish download.")

        def try_ask():
            need_update = True
            has_seeed_firmware = True
            com = QSerialPort()
            com.setPortName(self.info.board_name)
            com.setBaudRate(115200)

            if com.open(QSerialPort.ReadWrite) is False:
                print("can't open serial.")
                return not need_update, not has_seeed_firmware

            print('write 0x2 0x3')
            end_token = '; Ardupy with seeed'
            com.write(b'\x03')
            ok = com.waitForBytesWritten(100)
            com.write(b'\x02')
            ok = ok and com.waitForBytesWritten(100)
            print('finish write ', ok)

            if not ok or not com.waitForReadyRead(100):
                com.close()
                print('close serial')
                return need_update, not has_seeed_firmware

            try:
                print('read')
                tmp = com.read(100)
                tmp = str(tmp, 'utf-8')
                print(tmp)
                r = tmp.index(end_token)
                tmp = tmp[r - 10:r]
                need_update = new_version > strptime(tmp)
                print(tmp)
            except Exception as ex:
                print(ex)
                has_seeed_firmware = False

            com.close()
            print('close serial')
            return need_update, has_seeed_firmware

        need_update, has_seeed_firmware = try_ask()

        if not need_update:
            return

        if self.need_confirm:
            flag = ConfirmFlag()
            if has_seeed_firmware:
                flag.hint = 'there is a new available firmware, ' + \
                    'would you like to update it to you board ?'
            else:
                flag.hint = 'there is no firmware in your board, ' + \
                    'would you like to flashing a firmware ?'
            self.confirm.emit(flag)

            while flag.confirm is None:
                time.sleep(0.7)
            if flag.confirm is False:
                return

        self.go_download_mode()

        for i in range(3):
            '''
            wait serial available
            a dectect message will show in the message line after 1sec
            so we also wait it show up and override it.
            '''
            time.sleep(1.2)
            self.show_status.emit(self.hint_flashing)

            if self.flashing():
                version = '%d.%d.%d' % \
                    (new_version.year, new_version.month, new_version.day)
                self.flashing_result.emit(version)
                return
        self.flashing_result.emit(None)


class SeeedMode(MicroPythonMode):
    """
    Represents the functionality required for running MicroPython on Seeed's
    line of boards
    """
    name = _('Seeed MicroPython')
    description = _("Use MicroPython on Seeed's line of boards.")
    icon = 'seeed'
    fs = None
    second_of_show = 4
    info = Info()
    # There are many boards which use ESP microcontrollers but they often use
    # the same USB / serial chips (which actually define the Vendor ID and
    # Product ID for the connected devices.

    # VID  , PID
    valid_boards = info.board_normal + info.board_boot

    def __init__(self, editor, view):
        super().__init__(editor, view)
        self.invoke = FirmwareUpdater(
            confirm=self.__confirm,
            show_status=self.__show_status,
            flashing_result=self.__flashing_result
        )
        self.invoke.info = SeeedMode.info
        self.invoke.start()
        ArdupyDeviceFileList.info = SeeedMode.info
        editor.detect_new_device_handle = \
            self.__asyc_detect_new_device_handle

    def __set_all_button(self, state):
        self.set_buttons(files=state, run=state, repl=state, plotter=state)

    def __show_status(self, msg):
        if msg == self.invoke.hint_flashing_fail or \
                msg == self.invoke.hint_flashing_success:
            self.__set_all_button(True)
        self.editor.show_status_message(msg)

    def __confirm(self, flag):
        flag.confirm = QMessageBox.Ok == \
            self.view.show_confirmation(flag.hint, icon='Question')
        if flag.confirm:
            self.__set_all_button(False)

    def __flashing_result(self, version):
        self.msg = QMessageBox()
        self.msg.setWindowTitle('Hint')
        self.msg.setDefaultButton(self.msg.Ok)

        if version:
            self.msg.setText('your board update to version ' + version +
                             ' successfully!')
        else:
            self.msg.setText('there is something wrong, update fail!')
        self.msg.show()

    def __asyc_detect_new_device_handle(self, device_name):
        self.invoke.need_confirm = True
        self.invoke.info.new_board_id = None
        self.invoke.info.new_board_name = device_name
        available_ports = QSerialPortInfo.availablePorts()

        def match(pvid, ids):
            for valid in ids:
                if pvid == valid:
                    self.invoke.info.new_board_id = str(valid)
                    return True
            return False

        for port in available_ports:
            pvid = (
                port.vendorIdentifier(),
                port.productIdentifier()
            )
            if match(pvid, self.invoke.info.board_normal):
                break
            if match(pvid, self.invoke.info.board_boot):
                self.invoke.need_confirm = False
                break

        if self.invoke.info.new_board_id is not None:
            self.invoke.detected = True

    def actions(self):
        """
        Return an ordered list of actions provided by this module. An action
        is a name (also used to identify the icon) , description, and handler.
        """
        buttons = [
            {
                'name': 'run',
                'display_name': ('Run'),
                'description': _("Run your code directly on the Seeed's"
                                 " line of boards. via the REPL."),
                'handler': self.run,
                'shortcut': 'F5',
            },
            {
                'name': 'files',
                'display_name': ('Files'),
                'description': _("Access the file system on "
                                 "Seeed's line of boards."),
                'handler': self.toggle_files,
                'shortcut': 'F4',
            },
            {
                'name': 'repl',
                'display_name': ('REPL'),
                'description': _("Use the REPL to live-code on the "
                                 "Seeed's line of boards."),
                'handler': self.toggle_repl,
                'shortcut': 'Ctrl+Shift+I',
            }, ]
        if CHARTS:
            buttons.append({
                'name': 'plotter',
                'display_name': ('Plotter'),
                'description': ('Plot incoming REPL data.'),
                'handler': self.toggle_plotter,
                'shortcut': 'CTRL+Shift+P',
            })

        return buttons

    def api(self):
        """
        Return a list of API specifications to be used by auto-suggest and call
        tips.
        """
        return SHARED_APIS + SEEED_APIS

    def toggle_repl(self, event):
        if self.fs is None:
            if self.repl:
                # Remove REPL
                super().toggle_repl(event)
                self.set_buttons(files=True)
            elif not (self.repl):
                # Add REPL
                super().toggle_repl(event)
                if self.repl:
                    self.set_buttons(files=False)
        else:
            message = _("REPL and file system cannot work at the same time.")
            information = _("The REPL and file system both use the same USB "
                            "serial connection. Only one can be active "
                            "at any time. Toggle the file system off and "
                            "try again.")
            self.view.show_message(message, information)

    def toggle_plotter(self, event):
        """
        Check for the existence of the file pane before toggling plotter.
        """
        if self.fs is None:
            super().toggle_plotter(event)
            if self.plotter:
                self.set_buttons(files=False)
            elif not (self.repl or self.plotter):
                self.set_buttons(files=True)
        else:
            message = _("The plotter and file system cannot work at the same "
                        "time.")
            information = _("The plotter and file system both use the same "
                            "USB serial connection. Only one can be active "
                            "at any time. Toggle the file system off and "
                            "try again.")
            self.view.show_message(message, information)

    def run(self):
        """
        Takes the currently active tab, compiles the Python script therein into
        a hex file and flashes it all onto the connected device.
        """
        """
        if self.repl:
            message = _("Flashing cannot be performed at the same time as the "
                        "REPL is active.")
            information = _("File transfers use the same "
                            "USB serial connection as the REPL. Toggle the "
                            "REPL off and try again.")
            self.view.show_message(message, information)
            return
        """
        logger.info('Running script.')
        # Grab the Python script.
        tab = self.view.current_tab
        if tab is None:
            # There is no active text editor.
            message = _("Cannot run anything without any active editor tabs.")
            information = _("Running transfers the content of the current tab"
                            " onto the device. It seems like you don't have "
                            " any tabs open.")
            self.view.show_message(message, information)
            return
        python_script = tab.text().split('\n')
        if not self.repl:
            self.toggle_repl(None)
        if self.repl:
            self.view.repl_pane.send_commands(python_script)

    def toggle_files(self, event):
        """
        Check for the existence of the REPL or plotter before toggling the file
        system navigator for the MicroPython device on or off.
        """
        if self.repl:
            message = _("File system cannot work at the same time as the "
                        "REPL or plotter.")
            information = _("The file system and the REPL and plotter "
                            "use the same USB serial connection. Toggle the "
                            "REPL and plotter off and try again.")
            self.view.show_message(message, information)
        else:
            if self.fs is None:
                self.add_fs()
                if self.fs:
                    logger.info('Toggle filesystem on.')
                    self.set_buttons(run=False, repl=False, plotter=False)
            else:
                self.remove_fs()
                logger.info('Toggle filesystem off.')
                self.set_buttons(run=True, repl=True, plotter=True)

    def add_fs(self):
        """
        Add the file system navigator to the UI.
        """

        # Find serial port boards is connected to
        device_port, serial_number = self.find_device()

        # Check for MicroPython device
        if not device_port:
            message = _("Could not find an attached Seeed's line of boards.")
            information = _("Please make sure the device is plugged "
                            "into this computer.\n\nThe device must "
                            "have MicroPython flashed onto it before "
                            "the file system will work.\n\n"
                            "Finally, press the device's reset button "
                            "and wait a few seconds before trying "
                            "again.")
            self.view.show_message(message, information)
            return
        self.file_manager_thread = QThread(self)
        self.file_manager = FileManager(device_port)
        self.file_manager.moveToThread(self.file_manager_thread)
        self.file_manager_thread.started.connect(self.file_manager.on_start)
        self.view.default_pane = SeeedFileSystemPane
        self.fs = self.view.add_filesystem(
            self.workspace_dir(),
            self.file_manager,
            "Seeed's line of boards"
        )
        self.fs.set_message.connect(self.editor.show_status_message)
        self.fs.set_warning.connect(self.view.show_message)
        self.file_manager_thread.start()

    def remove_fs(self):
        """
        Remove the file system navigator from the UI.
        """
        self.view.remove_filesystem()
        self.file_manager = None
        self.file_manager_thread = None
        self.fs = None

    def on_data_flood(self):
        """
        Ensure the Files button is active before the REPL is killed off when
        a data flood of the plotter is detected.
        """
        self.set_buttons(files=True)
        super().on_data_flood()
