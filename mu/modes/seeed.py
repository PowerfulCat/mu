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
import datetime
import os
import platform
import subprocess
import shutil
import zipfile
import requests
from mu.contrib.microfs import execute
from mu.modes.api import SEEED_APIS, SHARED_APIS
from mu.modes.base import MicroPythonMode, FileManager
from mu.interface.panes import CHARTS, PANE_ZOOM_SIZES, \
    MicroPythonDeviceFileList
from mu.interface.themes import Font, DEFAULT_FONT_SIZE
from mu.resources import load_icon, path
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo
from PyQt5.QtCore import pyqtSignal, QThread, Qt
from PyQt5.QtWidgets import QMessageBox, \
    QMenu, QTreeWidget, QTreeWidgetItem, QAbstractItemView
from PyQt5.QtWidgets import QGridLayout, QLabel, QFrame

logger = logging.getLogger(__name__)


class Info:
    __stty = None
    __config = None
    has_firmware = False
    board_normal = []
    board_boot = []
    dic_config = {}
    com = None
    board_id = None
    board_name = None

    def __init__(self):
        inf = open(self.info_path, 'r')
        inf = json.loads(inf.read())
        self.lib_dic = {}
        self.board_boot.clear()
        self.board_normal.clear()
        self.dic_config.clear()
        fmt = 'config-%s.json'

        for board in inf['boot']:
            name = board['name']
            pvid = board['pvid']
            keyv = (pvid[0], pvid[1])
            self.dic_config.setdefault(str(keyv), fmt % name)
            self.board_boot.append(keyv)

        for board in inf['normal']:
            name = board['name']
            pvid = board['pvid']
            keyv = (pvid[0], pvid[1])
            self.dic_config.setdefault(str(keyv), fmt % name)
            self.board_normal.append(keyv)

        inf = open(self.info_path, 'r')
        inf = json.loads(inf.read())

        for lib in inf['lib']:
            self.lib_dic.setdefault(lib['name'], lib['version'])

    def load_config(self):
        file = open(self.config_path, 'r')
        self.__config = json.loads(file.read())

    @staticmethod
    def path(child):
        return path(child, 'seeed/')

    @staticmethod
    def path_tools(child):
        if os.name == 'posix':
            if platform.uname().system == 'Darwin':
                return path(child, 'seeed/tools-darwin/')
            return path(child, 'seeed/tools-linux/')
        else:
            return path(child, 'seeed/tools-win/')

    @property
    def cloud_config_path(self):
        return 'https://seeed-studio.github.io/ArduPy/' + \
            self.dic_config[self.board_id]

    @property
    def cloud_libaray_info_path(self):
        return 'https://seeed-studio.github.io/ArduPy/libaray.json'

    @property
    def config_path(self):
        return self.path(self.dic_config[self.board_id])

    @property
    def version(self):
        return strptime(self.__config['firmware']['version'])

    @property
    def cloud_firmware(self):
        return self.__config['firmware']['path']

    @property
    def local_firmware(self):
        return self.path(self.__config['firmware']['name'])

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
        cmd = 'bossac.exe -i -d --port=%s -U true -i -e -w -v %s -R' \
            % (self.short_device_name, self.local_firmware)
        cmd = self.path_tools(cmd)
        print(cmd)
        return cmd

    @property
    def stty(self):
        if os.name == 'posix':
            if platform.uname().system == 'Darwin':
                return 'stty -f ' + self.board_name + ' %d'
            return 'stty -F ' + self.board_name + ' %d'
        elif os.name == 'nt':
            return 'MODE ' + self.board_name + ':BAUD=%d PARITY=N DATA=8'
        return ['echo not support']

    @property
    def info_path(self):
        return self.path('info.json')

    @property
    def libaray_info_path(self):
        return self.path('libaray.json')


class ConfirmFlag:
    hint = None
    confirm = None

    @property
    def is_confirm(self):
        while self.confirm is None:
            time.sleep(0.7)
        return self.confirm


class LocalFileTree(QTreeWidget):
    put = pyqtSignal(str)
    delete = pyqtSignal(str)
    set_message = pyqtSignal(str)
    open_file = pyqtSignal(str)
    get = pyqtSignal(str, str)
    list_files = pyqtSignal()
    disable = pyqtSignal()
    enable = pyqtSignal()
    need_update_tree = True
    info = None

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
        self.__icon_firmware = load_icon('firmware.png')
        self.__icon_folder = load_icon('folder.png')

    def ls(self):
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
        cur = self.currentItem()
        if cur.is_file:
            hint_cant_delete = _("This Libaray file can't be deleted.")
        else:
            hint_cant_delete = _("This Libaray folder can't be deleted.")
        while cur.parent() is not None:
            cur = cur.parent()
        name = cur.text(0)

        for item in LocalFileTree.info.lib_dic.keys():
            if os.path.splitext(item)[0] != name:
                continue
            menu = QMenu(self)
            delete_action = menu.addAction(hint_cant_delete)
            menu.exec_(self.mapToGlobal(event.pos()))
            return

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
            parent = item.parent() or self.invisibleRootItem()
            parent.removeChild(item)
            msg = "'%s' successfully deleted from local machine." % item.name
            logger.info(msg)
            self.set_message.emit(msg)
            self.enable.emit()


class ArdupyDeviceFileList(MicroPythonDeviceFileList):
    info = None
    serial = None

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
        source.need_update_tree = False
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

        try:
            msg = execute([
                'import os',
                'print(os.statvfs(\'/\'), end=\'\')',
            ], ArdupyDeviceFileList.serial)
            msg = str(msg[0], 'utf-8')
            print(msg)
        except Exception as ex:
            print(ex)
            msg = "Fail! serial error."
            self.set_message.emit(msg)
            return

        val = msg.split(', ')
        avaliable_byte = int(val[1]) * int(val[4])
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


class SeeedFileSystemPane(QFrame):
    set_message = pyqtSignal(str)
    set_warning = pyqtSignal(str)
    list_files = pyqtSignal()
    open_file = pyqtSignal(str)

    def __init__(self, home):
        super().__init__()
        self.home = home
        self.font = Font().load()
        microbit_fs = ArdupyDeviceFileList(home)
        local_fs = LocalFileTree(home)

        @local_fs.open_file.connect
        def on_open_file(file):
            # Bubble the signal up
            self.open_file.emit(file)

        layout = QGridLayout()
        self.setLayout(layout)
        microbit_label = QLabel()
        microbit_label.setText(_('Files on your device:'))
        local_label = QLabel()
        local_label.setText(_('Files on your computer:'))
        self.microbit_label = microbit_label
        self.local_label = local_label
        self.microbit_fs = microbit_fs
        self.local_fs = local_fs
        self.set_font_size()
        layout.addWidget(microbit_label, 0, 0)
        layout.addWidget(local_label, 0, 1)
        layout.addWidget(microbit_fs, 1, 0)
        layout.addWidget(local_fs, 1, 1)
        self.microbit_fs.disable.connect(self.disable)
        self.microbit_fs.set_message.connect(self.show_message)
        self.local_fs.disable.connect(self.disable)
        self.local_fs.enable.connect(self.enable)
        self.local_fs.set_message.connect(self.show_message)

    def disable(self):
        """
        Stops interaction with the list widgets.
        """
        self.microbit_fs.setDisabled(True)
        self.local_fs.setDisabled(True)
        self.microbit_fs.setAcceptDrops(False)
        self.local_fs.setAcceptDrops(False)

    def enable(self):
        """
        Allows interaction with the list widgets.
        """
        self.microbit_fs.setDisabled(False)
        self.local_fs.setDisabled(False)
        self.microbit_fs.setAcceptDrops(True)
        self.local_fs.setAcceptDrops(True)

    def show_message(self, message):
        """
        Emits the set_message signal.
        """
        self.set_message.emit(message)

    def show_warning(self, message):
        """
        Emits the set_warning signal.
        """
        self.set_warning.emit(message)

    def on_ls(self, microbit_files):
        """
        Displays a list of the files on the seeed board.

        Since listing files is always the final event in any interaction
        between Mu and the seeed board, this enables the controls again for
        further interactions to take place.
        """
        self.microbit_fs.clear()
        for f in microbit_files:
            self.microbit_fs.addItem(f)

        if self.local_fs.need_update_tree:
            self.local_fs.clear()
            self.local_fs.ls()
        else:
            self.local_fs.need_update_tree = True
        self.enable()

    def on_ls_fail(self):
        """
        Fired when listing files fails.
        """
        self.show_warning(_("There was a problem getting the list of files on "
                            "the device. Please check Mu's logs for "
                            "technical information. Alternatively, try "
                            "unplugging/plugging-in your device and/or "
                            "restarting Mu."))
        self.disable()

    def on_put_fail(self, filename):
        """
        Fired when the referenced file cannot be copied onto the device.
        """
        self.show_warning(_("There was a problem copying the file '{}' onto "
                            "the device. Please check Mu's logs for "
                            "more information.").format(filename))

    def on_delete_fail(self, filename):
        """
        Fired when a deletion on the device for the given file failed.
        """
        self.show_warning(_("There was a problem deleting '{}' from the "
                            "device. Please check Mu's logs for "
                            "more information.").format(filename))

    def on_get_fail(self, filename):
        """
        Fired when getting the referenced file on the device failed.
        """
        self.show_warning(_("There was a problem getting '{}' from the "
                            "device. Please check Mu's logs for "
                            "more information.").format(filename))

    def set_theme(self, theme):
        pass

    def set_font_size(self, new_size=DEFAULT_FONT_SIZE):
        """
        Sets the font size for all the textual elements in this pane.
        """
        self.font.setPointSize(new_size)
        self.microbit_label.setFont(self.font)
        self.local_label.setFont(self.font)
        self.microbit_fs.setFont(self.font)
        self.local_fs.setFont(self.font)

    def set_zoom(self, size):
        """
        Set the current zoom level given the "t-shirt" size.
        """
        self.set_font_size(PANE_ZOOM_SIZES[size])


def strptime(value):
    return datetime.datetime.strptime(value, '%Y-%m-%d')


def download(des_path, source_path, timeout=5, try_time=3):
    tmp = des_path + '.tmp'

    for i in range(0, try_time):
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            get = requests.get(source_path)
            get.raise_for_status()
            file = open(tmp, 'wb')
            for block in get.iter_content(16 * 1024):
                file.write(block)
            file.close()
            shutil.move(tmp, des_path)
            print("finish download.")
            return True
        except Exception as ex:
            print(ex)
    return False


class FirmwareUpdater(QThread):
    show_status = pyqtSignal(str, float)
    confirm = pyqtSignal(ConfirmFlag)
    show_message_box = pyqtSignal(str)
    set_all_button = pyqtSignal(bool)
    detected = False
    in_bootload_mode = False
    need_confirm = True
    hint_flashing = 'Flashing...'
    hint_flashing_success = 'Flashing success.'
    hint_flashing_fail = 'Flashing fail.'

    def __init__(
            self,
            mu_code_path,
            confirm,
            show_status,
            show_message_box,
            set_all_button,
            parent=None):
        super(FirmwareUpdater, self).__init__(parent)
        self.mu_code_path = mu_code_path
        self.confirm.connect(confirm)
        self.show_status.connect(show_status)
        self.show_message_box.connect(show_message_box)
        self.set_all_button.connect(set_all_button)

    def run(self):
        self.update_lib()
        while True:
            while not self.detected:
                time.sleep(1)
            self.update()
            self.detected = False

    def show_status_short_time(self, msg):
        self.show_status.emit(msg, 5)

    def show_status_always(self, msg):
        self.show_status.emit(msg, 1000 * 1000)

    def update_lib(self):
        self.extract()
        if not download(self.info.libaray_info_path,
                        self.info.cloud_libaray_info_path):
            print('network error')
            return

        lib = open(self.info.libaray_info_path, 'r')
        inf = open(self.info.info_path, 'r')
        lib = json.loads(lib.read())
        inf = json.loads(inf.read())
        network_error = 'libaray update failure, please check your network.'
        has_new = False

        # check new
        for new in lib:
            need_download = True
            new_nam = new['name']
            new_ver = new['version']

            if new_nam not in self.info.lib_dic.keys():
                self.show_status_always('downloading %s...' % new_nam)
            elif strptime(new_ver) > strptime(self.info.lib_dic[new_nam]):
                self.show_status_always('updating %s...' % new_nam)
            else:
                need_download = False
            if not need_download:
                continue
            if not download(self.info.path(new_nam), new['path'], timeout=16):
                self.show_status_short_time(network_error)
                return

            self.show_status_always('extracting %s...' % new_nam)

            if not self.unzip(new_nam):
                self.show_status_short_time('%s extract failure' % new_nam)
                return
            has_new = True

        if not has_new:
            return

        inf['lib'] = lib

        with open(self.info.info_path, 'w') as f:
            json.dump(inf, f)
            print('lib has been updated successfully!')
        self.show_status_short_time('libaray update successfully!')

    def extract(self):
        # extract to mu_code dir
        inf = open(self.info.info_path, 'r')
        inf = json.loads(inf.read())
        for lib in inf['lib']:
            self.unzip(lib['name'])

    def unzip(self, lib_zip_name):
        lib_path_zip = self.info.path(lib_zip_name)
        lib_path_mu_code = os.path.join(
            self.mu_code_path,
            lib_zip_name.replace('.zip', '')
        )

        print('mu_code =', lib_path_mu_code)
        print('lib_path_zip =', lib_path_zip)

        try:
            if not os.path.exists(lib_path_mu_code):
                zf = zipfile.ZipFile(lib_path_zip, 'r')
                for f in zf.namelist():
                    zf.extract(f, lib_path_mu_code)
                print('unzip circuitpython-bundle to mu_code dir')
            return True
        except Exception as ex:
            if os.path.exists(lib_path_mu_code):
                shutil.rmtree(lib_path_mu_code)
            print(ex)
            return False

    def flashing(self):
        sp = subprocess.Popen(self.info.bossac, shell=True)
        sp.wait()
        return sp.returncode == 0

    def on_put(self, file):
        msg = "'%s' successfully copied to seeed board." % file
        self.set_message.emit(msg)
        self.list_files.emit()

    def on_delete(self, file):
        msg = "'%s' successfully deleted from seeed board." % file
        self.set_message.emit(msg)
        self.list_files.emit()

    def download_to_board(
            self,
            new_version,
            need_update=True,
            has_seeed_firmware=False):
        if self.need_confirm:
            flag = ConfirmFlag()
            if has_seeed_firmware:
                flag.hint = 'there is a new available firmware, ' + \
                    'would you like to update it to you board ?'
            elif self.in_bootload_mode:
                flag.hint = 'your board on bootload download mode, ' + \
                    'would you like to flashing a firmware ?'
            else:
                flag.hint = 'there is no firmware in your board, ' + \
                    'would you like to flashing a firmware ?'
            self.confirm.emit(flag)

            if not flag.is_confirm:
                return
        elif not self.in_bootload_mode:
            self.set_all_button.emit(True)
            return
        else:
            self.need_confirm = True

        self.set_all_button.emit(False)

        if not self.in_bootload_mode:
            print('setting baud rate...')
            subprocess.call(self.info.stty % 1200, shell=True)
            self.need_confirm = False
            return

        self.show_status_always(self.hint_flashing)
        if self.flashing():
            version = 'your board update to version %d.%d.%d sucessfully!' % \
                (new_version.year, new_version.month, new_version.day)
            self.show_message_box.emit(version)
            self.show_status_short_time(self.hint_flashing_success)
            self.has_firmware = True
        else:
            self.show_status_short_time(self.hint_flashing_fail)
            self.show_status_short_time('flashing fail.')
        self.set_all_button.emit(True)

    def update(self):
        need_update = True
        has_seeed_firmware = True

        if self.need_confirm:
            print("download config.")
            if os.path.exists(self.info.config_path):
                self.info.load_config()
                old_version = self.info.version
            else:
                old_version = datetime.datetime(2000, 1, 1)

            if download(self.info.config_path,
                        self.info.cloud_config_path):
                print('finished download')
                self.info.load_config()
                new_version = self.info.version

                if old_version < new_version and \
                        not os.path.exists(self.info.local_firmware):
                    print("download firmware.")
                    success = download(
                        self.info.local_firmware,
                        self.info.cloud_firmware,
                        timeout=16
                    )
                    if not success:
                        print("download failure.")
                    else:
                        print("finish download.")
            else:
                new_version = old_version
        else:
            self.info.load_config()
            new_version = self.info.version

        if self.in_bootload_mode:
            self.download_to_board(new_version)
            return

        for i in range(3):
            com = QSerialPort()
            com.setBaudRate(115200)
            com.setPortName(self.info.board_name)
            if not com.open(QSerialPort.ReadWrite):
                print("can't open com, waiting...")
                time.sleep(5)
                continue
            buf = bytearray()
            com.write(b'\x03')
            com.write(b'\x03')
            com.write(b'\x02')
            while com.waitForReadyRead(400) and len(buf) < 200:
                buf = buf + com.readAll()
            try:
                tmp = str(buf, 'utf-8')
                print(tmp)
                r = tmp.index('; Ardupy with seeed')
                ver = tmp[r - 10:r]
                need_update = new_version > strptime(ver)
                print(ver)
                self.info.has_firmware = True
            except Exception as ex:
                print(ex)
                has_seeed_firmware = False
            if com.isOpen():
                com.close()
                print('com close')
            if not need_update:
                print('has latest firmware.')
            else:
                self.download_to_board(
                    new_version,
                    need_update,
                    has_seeed_firmware)
            return
        print("giveup")


class SeeedMode(MicroPythonMode):
    """
    Represents the functionality required for running MicroPython on Seeed's
    line of boards
    """
    name = _('Seeed MicroPython')
    description = _("Use MicroPython on Seeed's line of boards.")
    icon = 'seeed'
    fs = None
    info = Info()
    # There are many boards which use ESP microcontrollers but they often use
    # the same USB / serial chips (which actually define the Vendor ID and
    # Product ID for the connected devices.

    # VID  , PID
    valid_boards = info.board_normal + info.board_boot

    def __init__(self, editor, view):
        super().__init__(editor, view)
        self.invoke = FirmwareUpdater(
            mu_code_path=super().workspace_dir(),  # mu_code/
            confirm=self.__confirm,
            show_status=self.editor.show_status_message,
            show_message_box=self.__show_message_box,
            set_all_button=self.__set_all_button
        )
        self.invoke.info = SeeedMode.info
        self.invoke.start()
        self.view.default_pane = SeeedFileSystemPane
        ArdupyDeviceFileList.info = SeeedMode.info
        LocalFileTree.info = SeeedMode.info
        editor.detect_new_device_handle = \
            self.__asyc_detect_new_device_handle

    def __set_all_button(self, state):
        print('button Enable=' + str(state))
        self.set_buttons(files=state, run=state, repl=state, plotter=state)

    def __confirm(self, flag):
        flag.confirm = QMessageBox.Ok == \
            self.view.show_confirmation(flag.hint, icon='Question')

    def __show_message_box(self, text):
        self.msg = QMessageBox()
        self.msg.setWindowTitle('Hint')
        self.msg.setDefaultButton(self.msg.Ok)
        self.msg.setText(text)
        self.msg.show()

    def __asyc_detect_new_device_handle(self, device_name):
        self.info.has_firmware = False
        self.info.board_id = None
        self.info.board_name = device_name
        available_ports = QSerialPortInfo.availablePorts()

        def match(pvid, ids):
            for valid in ids:
                if pvid == valid:
                    self.info.board_id = str(valid)
                    return True
            return False

        for port in available_ports:
            pvid = (
                port.vendorIdentifier(),
                port.productIdentifier()
            )
            if match(pvid, self.info.board_normal):
                self.invoke.in_bootload_mode = False
                print('detect a normal mode borad')
                break
            if match(pvid, self.info.board_boot):
                self.invoke.in_bootload_mode = True
                print('detect a bootload mode borad')
                break

        self.invoke.detected = True

    def actions(self):
        """
        Return an ordered list of actions provided by this module. An action
        is a name (also used to identify the icon) , description, and handler.
        """
        buttons = [
            {
                'name': 'run',
                'display_name': _('Run'),
                'description': _("Run your code directly on the Seeed's"
                                 " line of boards. via the REPL."),
                'handler': self.run,
                'shortcut': 'F5',
            },
            {
                'name': 'files',
                'display_name': _('Files'),
                'description': _("Access the file system on "
                                 "Seeed's line of boards."),
                'handler': self.toggle_files,
                'shortcut': 'F4',
            },
            {
                'name': 'repl',
                'display_name': _('REPL'),
                'description': _("Use the REPL to live-code on the "
                                 "Seeed's line of boards."),
                'handler': self.toggle_repl,
                'shortcut': 'Ctrl+Shift+I',
            }, ]
        if CHARTS:
            buttons.append({
                'name': 'plotter',
                'display_name': _('Plotter'),
                'description': _('Plot incoming REPL data.'),
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

    def check_firmware_existence(self):
        hint = 'denit! please make sure your board connected to ' + \
            'the computer and there is a Ardupy firmware in your board.'
        if self.info.has_firmware:
            return True
        self.__show_message_box(hint)
        return False

    def toggle_repl(self, event):
        if not self.check_firmware_existence():
            return
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
        if not self.check_firmware_existence():
            return
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
        if not self.check_firmware_existence():
            return
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

        def on_start():
            self.file_manager.on_start()
            try:
                ArdupyDeviceFileList.serial = self.file_manager.serial
            except Exception as ex:
                print(ex)

        self.file_manager_thread = QThread(self)
        self.file_manager = FileManager(device_port)
        self.file_manager.moveToThread(self.file_manager_thread)
        self.file_manager_thread.started.connect(on_start)
        self.fs = self.view.add_filesystem(self.workspace_dir(),
                                           self.file_manager,
                                           _("Seeed's line of boards"))
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
        ArdupyDeviceFileList.serial = None

    def on_data_flood(self):
        """
        Ensure the Files button is active before the REPL is killed off when
        a data flood of the plotter is detected.
        """
        self.set_buttons(files=True)
        super().on_data_flood()
