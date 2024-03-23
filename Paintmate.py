import itertools
import os
import sqlite3
import sys
import csv
import datetime
import webbrowser
import cv2
import numpy
import threading

import uicuis.AboutProgramUi as AboutProgramUi
import uicuis.ChangeObjectWindowUi as ChangeObjectWindowUi
import uicuis.ChooseProjectWindowUi as ChooseProjectWindowUi
import uicuis.PaintmateRenderWindowUi as PaintmateRenderWindowUi
import uicuis.ProjectWindowUi as ProjectWindowUi
import uicuis.RenderAnimationUi as RenderAnimationUi
import uicuis.RenderSequenceUi as RenderSequenceUi

from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QBrush, QImage, QFont
from PyQt5.QtCore import QTimer, QPoint
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QWidget, QLabel, QApplication, QDesktopWidget, QInputDialog, QMessageBox, \
    QFileDialog, QSizePolicy, QRadioButton, QColorDialog


def resource_path(relative_path):
    """
    Helps pyinstaller to find packed files
    :param relative_path:
    :return:
    """

    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# constants
valid_characters = "abcdefghijklmnopqrstuvwxyz0123456789"
useless_time_offset_ms = 1000
with open(resource_path("texts/style.csv"), 'r') as file:
    style = list(csv.DictReader(file, delimiter=','))
timeline_constant_step = 50
timeline_label_width = 40
canvas_size_limit = 200
# saveable settings
fps = "fps"
current_frame = "current_frame"
width = "width"
height = "height"
timeline_multiplier = "timeline_multiplier"
count_of_frames = "count_of_frames"
scale_step = "scale_step"
stroke_width = "stroke_width"
color = "color"
fill_color = "fill_color"
ghost = "ghost"
# tools
manipulator = "manipulator"
pen = "pen"
line = "line"
ellipse = "ellipse"
filler = "filler"


class DeviceInfo:
    """
    Class that contains current device display information. Inheritors often use its method "position_to_center"
    """

    def __init__(self):
        self.desktop_widget = QDesktopWidget()
        self.device_width, self.device_height = self.desktop_widget.width(), self.desktop_widget.height()

    def position_to_center(self):
        """
        Moves a QWidget object to the center of the user's screen
        :return:
        """

        if self.width() < self.device_width and self.height() < self.device_height:
            self.move(self.device_width // 2 - self.width() // 2, self.device_height // 2 - self.height() // 2)


class Paintmate(QMainWindow, DeviceInfo, ProjectWindowUi.Ui_MainWindow):
    """
    The main class of Paintmate software from which every process is managed
    """

    def __init__(self):
        super().__init__()
        self.loading_window = LoadingWindow()
        self.loading_window.show()
        self.choose_project_window = None
        self.canvas = None
        self.about_window = None
        self.render_animation_window = None
        self.render_sequence_window = None
        self.render_window = None
        self.now_playing = False
        self.change_object_window = None
        self.frame_for_copying = 1
        self.database = Database()
        self.current_tool = manipulator
        QTimer.singleShot(useless_time_offset_ms, self.open_select_project_window)

    def open_select_project_window(self):
        self.choose_project_window = ChooseProjectWindow(self.open_project, self.create_project)
        self.choose_project_window.show()
        self.loading_window.hide()

    def check_input(self, name, extension):
        if not name:
            self.warning("Пустой ввод")
        elif set(name) - set(valid_characters + valid_characters.upper()):
            self.warning("Некорректное название, \nразрешены символы A-Z; a-z; 0-9")
        elif len(name) > 200:
            self.warning("Слишком длинное название")
        elif name + f".{extension}" in os.listdir():
            self.warning("Файл с таким названием уже существует")
        else:
            return True
        return False

    def create_project(self):
        input_window = QInputDialog(self)
        input_window.setStyleSheet(next(filter(lambda elem: elem["widget_name"] == "QInputDialog", style))["style"])
        input_window.setWindowTitle("Создать проект")
        input_window.setLabelText("Введите название")
        ok = input_window.exec()
        name = input_window.textValue()
        if ok and self.check_input(name, "sqlite"):
            self.open_project(name + ".sqlite")

    def open_project(self, database_file=None):
        if not database_file:
            database_file = QFileDialog.getOpenFileName(self, "Выберите данные проекта", '')[0]
            if not database_file:
                return
            self.database.connect(database_file)
        else:
            self.database.connect(database_file)
            self.database.populate()
        self.loading_window.show()
        self.choose_project_window.hide()
        QTimer.singleShot(useless_time_offset_ms, self.init_ui)

    def init_ui(self):
        self.setupUi(self)
        # appyling saved settings
        self.database.load_settings()
        self.frame_rate.setValue(self.database.settings[fps])
        self.current_frame.setValue(self.database.settings[current_frame])
        self.timeline_visual_multiplier.setValue(self.database.settings[timeline_multiplier])
        self.timeline_visual_multiplier_description.setText("Размер таймлайна "
                                                            f"{self.database.settings[timeline_multiplier]}%")
        # spawning windows and binding buttons
        self.about_window = AboutWindow()
        self.render_animation_window = RenderAnimationWindow(self)
        self.render_sequence_window = RenderSequenceWindow(self)
        self.canvas = Canvas(self)
        self.position_to_center()
        self.update_timeline()
        self.pencil_tool.clicked.connect(lambda: self.change_tool(pen))
        self.line_tool.clicked.connect(lambda: self.change_tool(line))
        self.ellipse_tool.clicked.connect(lambda: self.change_tool(ellipse))
        self.fill_tool.clicked.connect(lambda: self.change_tool(filler))
        self.radio_group.buttonClicked.connect(lambda: self.change_tool(manipulator))
        self.radioButton.hide()
        self.create_frame.clicked.connect(self.create_new_frame)
        self.timeline_visual_multiplier.valueChanged.connect(
            lambda: self.update_timeline(self.timeline_visual_multiplier.value()))
        self.timeline.valueChanged.connect(self.change_current_frame)
        self.current_frame.valueChanged.connect(self.change_current_frame)
        self.frame_rate.valueChanged.connect(self.change_fps)
        self.copy_frame.clicked.connect(lambda: self.change_frame_for_copying(self.timeline.value()))
        self.paste_frame.clicked.connect(lambda: self.paste_copied_frame_after(self.timeline.value()))
        self.delete_frame.clicked.connect(self.delete_current_frame)
        self.first_frame.clicked.connect(self.to_first_frame)
        self.last_frame.clicked.connect(self.to_last_frame)
        self.previous_frame.clicked.connect(self.to_previous_frame)
        self.next_frame.clicked.connect(self.to_next_frame)
        self.change_object.clicked.connect(self.change_object_info)
        self.move_to_background.clicked.connect(lambda: self.lift(-1))
        self.move_to_overground.clicked.connect(lambda: self.lift(1))
        self.delete_object.clicked.connect(self.delete_selected_object)
        self.to_choose_project_window.triggered.connect(self.restart)
        self.play.triggered.connect(lambda: self.playing(True))
        self.set_canvas_width.triggered.connect(lambda: self.change_canvas_size(width))
        self.set_canvas_height.triggered.connect(lambda: self.change_canvas_size(height))
        self.set_canvas_scale_step.triggered.connect(
            lambda: self.database.update_settings(scale_step=QInputDialog.getInt(self, "Масштабирование",
                                                                                 "Пикселей в тик", 40, 1, 500)))
        self.set_default_stroke_width.triggered.connect(
            lambda: self.database.update_settings(stroke_width=QInputDialog.getInt(self, "Обводка",
                                                                                   "Ширина по умолчанию", 4, 1, 500)))
        self.set_default_stroke_color.triggered.connect(lambda: self.change_default_color(color))
        self.set_default_filler_color.triggered.connect(lambda: self.change_default_color(fill_color))
        self.about.triggered.connect(self.about_window.show)
        self.documentation.triggered.connect(lambda: webbrowser.open("austiniar.itch.io/paintmate"))
        self.render_sequence.triggered.connect(self.render_sequence_window.show)
        self.render_animation.triggered.connect(self.render_animation_window.show)
        self.set_ghost.triggered.connect(lambda: self.database.update_settings(ghost=(1 if self.set_ghost.isChecked()
                                                                                      else 0)))
        self.set_ghost.setChecked(bool(self.database.settings[ghost]))
        self.set_ghost.triggered.connect(self.canvas.repaint)
        # show
        self.canvas.show()
        self.show()
        self.loading_window.hide()

    def restart(self):
        """
        The function reloads Paintmate shell, re-receives and rerecreates the database object
        :return:
        """

        self.hide()
        self.loading_window = LoadingWindow()
        self.loading_window.show()
        self.choose_project_window = None
        self.canvas = None
        self.change_object_window = None
        self.about_window = None
        self.render_animation_window = None
        self.render_sequence_window = None
        self.render_window = None
        self.now_playing = False
        self.frame_for_copying = 1
        self.database = Database()
        self.current_tool = manipulator
        QTimer.singleShot(useless_time_offset_ms, self.open_select_project_window)

    def create_new_frame(self):
        self.database.update_settings(current_frame=self.database.settings[count_of_frames] + 1)
        self.update_timeline()
        self.canvas.repaint()

    def change_frame_for_copying(self, frame):
        self.frame_for_copying = frame

    def change_canvas_size(self, parameter):
        if parameter == width:
            self.database.update_settings(width=QInputDialog.getInt(self, "Холст", "Ширина", 1920, 100, 16384))
        else:
            self.database.update_settings(height=QInputDialog.getInt(self, "Холст", "Высота", 1920, 100, 16384))
        self.canvas.hand_resize(self.database.settings[width], self.database.settings[height])

    def change_default_color(self, parameter):
        """
        The function executes color selection window and apply that color as default for the entire project
        :param parameter: "color" or "fill_color" strings
        :return:
        """

        color_window = QColorDialog(self)
        color_window.setWindowTitle("Выберите цвет по умолчанию")
        color_window.setOption(QColorDialog.ShowAlphaChannel, on=True)
        color_window.exec()
        if color_window.currentColor().isValid():
            col = '|'.join(map(str,
                               (color_window.currentColor().red(), color_window.currentColor().green(),
                                color_window.currentColor().blue(), color_window.currentColor().alpha())))
            col = "'" + col + "'"
            if parameter == color:
                self.database.update_settings(color=col)
            else:
                self.database.update_settings(fill_color=col)
        color_window.deleteLater()

    def change_object_info(self, new_name=None, new_stroke_width=None, new_stroke_color=None, new_filler_color=None):
        """
        This function executes the custom window for changing properties of a seleted from frame objects area database
        entity
        :param new_name:
        :param new_stroke_width:
        :param new_stroke_color:
        :param new_filler_color:
        :return:
        """

        for elem in self.radio_group.buttons()[1:]:
            if elem.isChecked():
                if not (new_name or new_stroke_width or new_stroke_color or new_filler_color):
                    self.change_object_window = ChangeObjectWindow(self.change_object_info, self.database.get_object_poperties(elem.text()))
                else:
                    self.database.set_object_properties(elem.text(), new_name, new_stroke_width, new_stroke_color,
                                                        new_filler_color)
                    for el in self.radio_group.buttons()[1:]:
                        el.deleteLater()
                    self.canvas.repaint()
                    break

    def delete_selected_object(self):
        for elem in self.radio_group.buttons()[1:]:
            if elem.isChecked():
                self.database.remove_object(elem.text())
                for el in self.radio_group.buttons()[1:]:
                    el.deleteLater()
                    self.radio_group.removeButton(el)
                self.canvas.repaint()
                break

    def lift(self, addition):
        """
        The separated function for changing z-index of the selected frame object
        :param addition:
        :return:
        """

        for elem in self.radio_group.buttons()[1:]:
            if elem.isChecked():
                self.database.set_z_index(elem.text(), addition)
        self.repaint()

    def paste_copied_frame_after(self, frame):
        self.database.duplicate_frame(self.frame_for_copying, frame)
        self.create_new_frame()
        self.current_frame.setValue(frame + 1)

    def delete_current_frame(self):
        if self.timeline.value() != self.timeline.maximum():
            for elem in self.radio_group.buttons()[1:]:
                elem.deleteLater()
        self.database.delete_frame(self.timeline.value())
        self.update_timeline()
        self.canvas.repaint()

    def change_current_frame(self):
        """
        This function generally switches frames
        :return:
        """

        if self.sender() == self.current_frame:
            if 1 > self.current_frame.value():
                self.timeline.setValue(1)
                self.current_frame.setValue(1)
            elif self.current_frame.value() > self.database.settings[count_of_frames]:
                self.timeline.setValue(self.database.settings[count_of_frames])
                self.current_frame.setValue(self.database.settings[count_of_frames])
            else:
                self.timeline.setValue(self.sender().value())
            return
        self.current_frame.setValue(self.timeline.value())
        self.database.update_settings(current_frame=self.timeline.value())
        for elem in self.radio_group.buttons()[1:]:
            elem.deleteLater()
        self.canvas.repaint()

    def to_first_frame(self):
        self.timeline.setValue(1)

    def to_last_frame(self):
        self.timeline.setValue(self.timeline.maximum())

    def to_previous_frame(self):
        self.current_frame.setValue(self.timeline.value() - 1)

    def to_next_frame(self):
        self.current_frame.setValue(self.timeline.value() + 1 if self.timeline.value() + 1 <= self.timeline.maximum()
                                    else 1)

    def change_fps(self):
        if 1 > self.sender().value():
            self.sender().setValue(1)
            return
        if self.sender().value() > 144:
            self.sender().setValue(144)
            return
        self.database.update_settings(fps=self.frame_rate.value())

    def change_tool(self, tool):
        """
        This function changes the active drawable primitive
        :param tool:
        :return:
        """

        self.current_tool = tool

    def playing(self, signal=None):
        if signal:
            self.now_playing = not self.now_playing
            if self.now_playing:
                self.objects_area_layout_widget.hide()
            else:
                self.objects_area_layout_widget.show()
        if self.now_playing:
            self.to_next_frame()
            QTimer.singleShot(int(1 / self.frame_rate.value() * 1000), self.playing)

    def update_timeline(self, value=None):
        """
        Recalculates timeline visual metrics and redraw it.
        It is called first from the init_ui function
        :return: None
        """

        if value:
            self.timeline_visual_multiplier_description.setText(
                ' '.join(self.timeline_visual_multiplier_description.text().split()[:2]) + f" {value}%")
            self.database.update_settings(timeline_multiplier=value)
        self.database.load_settings()
        frames = list(range(1, self.database.settings[count_of_frames] + 1))
        self.timeline.setMaximum(len(frames))
        timeline_step = int(timeline_constant_step * self.database.settings[timeline_multiplier] / 100)
        self.timeline.setFixedWidth(timeline_step * (len(frames) - 1 if len(frames) - 1 else 1))
        self.ruler.setFixedWidth(self.timeline.width() + timeline_label_width)
        self.timeline.setFixedWidth(13 + self.timeline.width())
        self.timeline.setValue(self.database.settings[current_frame])
        chunk_width = self.timeline.width() / ((len(frames) - 1) if len(frames) - 1 else 1)
        while chunk_width < timeline_label_width:
            frames = frames[::2]
            try:
                chunk_width = self.timeline.width() / (len(frames) - 1)
            except ZeroDivisionError:
                break
        font = QFont()
        font.setPointSize(10)
        for elem in self.ruler.children():
            elem.deleteLater()
        for i in frames:
            label = QLabel(str(i), self.ruler)
            label.show()
            label.setFixedWidth(timeline_label_width)
            label.setFixedHeight(16)
            label.setFont(font)
            label.move(timeline_step * (i - 1), 0)

    def warning(self, message):
        """
        Displays error information
        :param message:
        :return:
        """

        message_window = QMessageBox()
        message_window.setText(message)
        message_window.setStyleSheet(next(filter(lambda elem: elem["widget_name"] == "QMessageBox", style))["style"])
        message_window.setWindowTitle("Ошибка")
        message_window.exec()


class LoadingWindow(QWidget, DeviceInfo):
    """
    Decorative class for displaying image while loading
    """

    def __init__(self):
        super().__init__()
        self.loading_picture = QPixmap(resource_path("images/loading.png"))
        self.setFixedSize(self.loading_picture.width(), self.loading_picture.height())
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.position_to_center()
        self.label = QLabel(self)
        self.label.setPixmap(self.loading_picture)


class AboutWindow(QWidget, DeviceInfo, AboutProgramUi.Ui_Form):
    """
    Decorative class that displays version of the software
    """

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.position_to_center()


class RenderAnimationWindow(QWidget, DeviceInfo, RenderAnimationUi.Ui_Form):
    """
    Class that executes the window with render settings, its name doesn't correspond to its functional
    """

    def __init__(self, paintmate):
        super().__init__()
        self.paintmate = paintmate
        self.setupUi(self)
        self.position_to_center()
        self.cancel_button.clicked.connect(self.hide)
        self.render_button.clicked.connect(self.start)

    def start(self):
        if self.codec.currentText() == "VP9" and self.container.currentText() == "avi":
            self.paintmate.warning("Контейнер avi\nНе пожжерживает VP9")
        elif self.codec.currentText() == "YUY2" and self.container.currentText() == "mp4":
            self.paintmate.warning("Контейнер mp4\nНе пожжерживает YUY2")
        elif self.codec.currentText() == "MJPG" and self.container.currentText() == "mp4":
            self.paintmate.warning("Контейнер mp4\nНе пожжерживает MJPG")
        elif self.paintmate.check_input(self.file_name.text(), self.container.currentText()):
            self.paintmate.render_window = PaintmateRender(self.file_name.text() + f".{self.container.currentText()}",
                                                           False,
                                                           self.paintmate, self.codec.currentText())
            self.hide()


class RenderSequenceWindow(QWidget, DeviceInfo, RenderSequenceUi.Ui_Form):
    def __init__(self, paintmate):
        super().__init__()
        self.paintmate = paintmate
        self.setupUi(self)
        self.position_to_center()
        self.cancel_button.clicked.connect(self.hide)
        self.render_button.clicked.connect(self.start)

    def start(self):
        if self.paintmate.check_input(self.file_name.text(), ''):
            self.paintmate.render_window = PaintmateRender(self.file_name.text(), True,
                                                           self.paintmate, self.type.currentText())
            self.hide()


class PaintmateRender(QWidget, DeviceInfo, PaintmateRenderWindowUi.Ui_Form):
    """
    The async renderer with its own window, uses daemon threading for numpy and video encoding operations (produce_2)
    """

    def __init__(self, object_name, is_sequence, paintmate, codec):
        super().__init__()
        self.object_name, self.is_sequence, self.paintmate, self.codec = object_name, is_sequence, paintmate, codec
        self.paintmate.loading_window.show()
        self.start_time_value = datetime.datetime.now()
        self.start_frame_time_value = self.start_time_value
        self.frames = int()
        if not is_sequence:
            self.video = cv2.VideoWriter(self.object_name, cv2.VideoWriter.fourcc(*{
                "h264": "MP4V",
                "VP9": "VP9 ",
                "Motion JPG": "MJPG",
                "YUY2": "YUY2"
            }[codec]), self.paintmate.database.settings[fps],
                                         (self.paintmate.database.settings[width],
                                          self.paintmate.database.settings[height]))
        QTimer.singleShot(useless_time_offset_ms, self.init_ui)

    def init_ui(self):
        self.paintmate.database.load_settings()
        self.setupUi(self)
        self.setWindowTitle("Paintmate рендер")
        self.total_frame.setText(str(self.paintmate.database.settings[count_of_frames]))
        self.paintmate.hide()
        self.show()
        self.paintmate.to_first_frame()
        self.paintmate.loading_window.hide()
        self.paintmate.canvas.hand_resize(self.paintmate.database.settings[width],
                                          self.paintmate.database.settings[height])
        self.placeholder.setMinimumWidth(self.paintmate.database.settings[width])
        self.placeholder.setMinimumHeight(self.paintmate.database.settings[height])
        self.produce_1()

    def produce_1(self):
        self.start_frame_time_value = datetime.datetime.now()
        threading.Thread(target=self.produce_2, daemon=True).start()

    def produce_2(self):
        image = self.paintmate.canvas.render_self()
        if not self.is_sequence:
            pixels = list()
            for i in range(self.paintmate.database.settings[height]):
                pixel_row = list()
                for j in range(self.paintmate.database.settings[width]):
                    pixel_row.append(((pixel_color := image.pixelColor(j, i)).red(), pixel_color.green(),
                                      pixel_color.blue()))
                pixels.append(pixel_row)
            pixels = numpy.array(pixels).astype("uint8")
            self.video.write(pixels)
        else:
            if self.object_name not in os.listdir():
                os.mkdir(os.getcwd() + f"\\{self.object_name}")
            image.save(f"{self.object_name}/{self.frames}.{self.codec}")
        self.produce_3(image)

    def produce_3(self, image):
        self.frames += 1
        self.current_frame.setText(str(self.frames))
        self.delta_time.setText(str((datetime.datetime.now() - self.start_frame_time_value).seconds))
        self.total_time.setText(str((datetime.datetime.now() - self.start_time_value).seconds))
        self.placeholder.setPixmap(QPixmap.fromImage(image))
        if self.frames != self.paintmate.database.settings[count_of_frames]:
            self.produce_1()
            return
        if not self.is_sequence:
            cv2.destroyAllWindows()
            self.video.release()
        self.render_status.setText(f"завершено, время начала: {self.start_time_value.strftime('%H:%M:%S')}, "
                                   f"время конца: {datetime.datetime.now().strftime('%H:%M:%S')}")

    def closeEvent(self, event):
        self.paintmate.show()

    def wheelEvent(self, event):
        if not (event.modifiers() & Qt.ControlModifier):
            return
        aspect_ratio = self.placeholder.minimumWidth() / self.placeholder.minimumHeight()
        if event.angleDelta().y() > 0:
            new_width = self.placeholder.minimumWidth() + self.paintmate.database.settings[scale_step]
            self.placeholder.setMinimumWidth(new_width)
            self.placeholder.setMinimumHeight(int(new_width / aspect_ratio))
        else:
            if self.placeholder.minimumWidth() < canvas_size_limit or \
                    self.placeholder.minimumHeight() < canvas_size_limit:
                return
            new_width = self.placeholder.minimumWidth() - self.paintmate.database.settings[scale_step]
            self.placeholder.setMinimumWidth(new_width)
            self.placeholder.setMinimumHeight(int(new_width / aspect_ratio))


class ChangeObjectWindow(QWidget, DeviceInfo, ChangeObjectWindowUi.Ui_Form):
    def __init__(self, action, current_object_properties):
        super().__init__()
        self.setupUi(self)
        self.position_to_center()
        self.action = action
        self.name_value = current_object_properties[0]
        self.stroke_width_value = current_object_properties[2]
        self.stroke_color_value = current_object_properties[3]
        self.filler_color_value = current_object_properties[4]
        self.show()
        self.stroke_width_label.hide()
        self.filler_color_label.hide()
        self.stroke_color_label.hide()
        self.stroke_width.hide()
        self.filler_color.hide()
        self.filler_color.hide()
        self.init_ui()

    def init_ui(self):
        self.cancel.clicked.connect(self.hide)
        self.ok.clicked.connect(self.ok_click)
        self.stroke_color.mousePressEvent = self.stroke_click
        self.filler_color.mousePressEvent = self.filler_click
        self.name.setText(self.name_value)
        if self.stroke_width_value:
            self.stroke_width.setValue(self.stroke_width_value)
            self.stroke_width.show()
            self.stroke_width_label.show()
        if self.stroke_color_value:
            self.stroke_color.setStyleSheet(
                f"background-color: #"
                f"{''.join(map(lambda elem: hex(int(elem))[2:], self.stroke_color_value.split('|')[:3]))};")
            self.stroke_color.show()
            self.stroke_color_label.show()
        if self.filler_color_value:
            self.filler_color.setStyleSheet(
                f"background-color: #"
                f"{''.join(map(lambda elem: hex(int(elem))[2:], self.filler_color_value.split('|')[:3]))};")
            self.filler_color.show()
            self.filler_color_label.show()

    def ok_click(self):
        self.hide()
        self.action(self.name.text().replace('_', ' '), self.stroke_width.value(), self.stroke_color_value,
                    self.filler_color_value)

    def stroke_click(self, event):
        color_window = QColorDialog(self)
        color_window.setWindowTitle("Выберите цвет")
        color_window.setOption(QColorDialog.ShowAlphaChannel, on=True)
        color_window.exec()
        if color_window.currentColor().isValid():
            self.stroke_color.setStyleSheet(f"background-color: {color_window.currentColor().name()};")
            self.stroke_color_value = (color_window.currentColor().red(), color_window.currentColor().green(),
                                       color_window.currentColor().blue(), color_window.currentColor().alpha())

    def filler_click(self, event):
        color_window = QColorDialog(self)
        color_window.setWindowTitle("Выберите цвет")
        color_window.setOption(QColorDialog.ShowAlphaChannel, on=True)
        color_window.exec()
        if color_window.currentColor().isValid():
            self.filler_color.setStyleSheet(f"background-color: {color_window.currentColor().name()};")
            self.filler_color_value = (color_window.currentColor().red(), color_window.currentColor().green(),
                                       color_window.currentColor().blue(), color_window.currentColor().alpha())


class ChooseProjectWindow(QWidget, DeviceInfo, ChooseProjectWindowUi.Ui_Form):
    def __init__(self, open_project, create_project):
        super().__init__()
        self.setupUi(self)
        self.position_to_center()
        self.create_button.clicked.connect(create_project)
        self.open_button.clicked.connect(open_project)


class Canvas(QWidget, DeviceInfo):
    """
    A widget that represents a drawing area, always has a fixed size and a universal paintEvent.
    Can be scaled with mouse wheel and Ctrl at runtime
    """

    def __init__(self, paintmate):
        super().__init__(paintmate.canvas_placeholder)
        self.paintmate = paintmate
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.parent().setMinimumWidth(self.paintmate.database.settings[width])
        self.parent().setMinimumHeight(self.paintmate.database.settings[height])
        self.setMinimumWidth(self.paintmate.database.settings[width])
        self.setMinimumHeight(self.paintmate.database.settings[height])
        self.delta_bounds = ([0, 0], [0, 0])
        self.alpha_divisor = 10

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.begin(self)
        painter.setPen(QPen(QColor(0, 0, 0, 0), 0))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawRect(0, 0, self.minimumWidth(), self.minimumHeight())
        if self.paintmate.database.settings[ghost]:
            self.ghost_paint(painter)
        for elem in self.paintmate.database.objects():
            (identifier, frame_id, object_stroke_width, object_color, x, y, xx, yy,
             object_z_index, object_fill_color, name) = elem
            if object_stroke_width is not None:
                object_stroke_width = (object_stroke_width / self.paintmate.database.settings[width] *
                                       self.minimumWidth())
            if all(map(lambda el: (False if el is None else True), elem[:-1])):  # ellipse
                painter.setPen(QPen(QColor(*map(int, object_color.split('|'))), object_stroke_width))
                painter.setBrush(QBrush(QColor(*map(int, object_fill_color.split('|')))))
                x = int(x * self.minimumWidth() / self.paintmate.database.settings[width])
                y = int(y * self.minimumHeight() / self.paintmate.database.settings[height])
                xx = int(xx * self.minimumWidth() / self.paintmate.database.settings[width])
                yy = int(yy * self.minimumHeight() / self.paintmate.database.settings[height])
                painter.drawEllipse(x, y, xx - x, yy - y)
                if (f"{name}_ellipse_{identifier}" not in
                        map(lambda e: e.text(), self.paintmate.radio_group.buttons())):
                    button = QRadioButton(f"{name}_ellipse_{identifier}", self.paintmate.objects_area_layout_widget)
                    self.paintmate.objects_area_layout.addWidget(button)
                    self.paintmate.radio_group.addButton(button)
            elif all(map(lambda el: (False if el[0] is None else True) == el[1],
                         zip(elem[:-1], (True,) * 9 + (False,)))):  # line
                painter.setPen(QPen(QColor(*map(int, object_color.split('|'))), object_stroke_width))
                x = int(x * self.minimumWidth() / self.paintmate.database.settings[width])
                y = int(y * self.minimumHeight() / self.paintmate.database.settings[height])
                xx = int(xx * self.minimumWidth() / self.paintmate.database.settings[width])
                yy = int(yy * self.minimumHeight() / self.paintmate.database.settings[height])
                painter.drawLine(x, y, xx, yy)
                if f"{name}_line_{identifier}" not in map(lambda e: e.text(), self.paintmate.radio_group.buttons()):
                    button = QRadioButton(f"{name}_line_{identifier}", self.paintmate.objects_area_layout_widget)
                    self.paintmate.objects_area_layout.addWidget(button)
                    self.paintmate.radio_group.addButton(button)
            elif all(map(lambda el: (False if el[0] is None else True) == el[1],
                         zip(elem[:-1], (True,) * 4 + (False,) * 4 + (True,) + (False,)))):  # pen
                painter.setBrush(QBrush(QColor(*map(int, object_color.split('|')))))
                painter.setPen(QPen(QColor(0, 0, 0, 0), 0))
                for _, __, x, y in self.paintmate.database.object_points(identifier, pen):
                    x = x * self.minimumWidth() / self.paintmate.database.settings[width]
                    y = y * self.minimumHeight() / self.paintmate.database.settings[height]
                    painter.drawEllipse(QPoint(int(x), int(y)), object_stroke_width, object_stroke_width)
                if f"{name}_pen_{identifier}" not in map(lambda e: e.text(), self.paintmate.radio_group.buttons()):
                    button = QRadioButton(f"{name}_pen_{identifier}", self.paintmate.objects_area_layout_widget)
                    self.paintmate.objects_area_layout.addWidget(button)
                    self.paintmate.radio_group.addButton(button)
            else:  # filler
                points = list()
                for _, __, x, y in self.paintmate.database.object_points(identifier, filler):
                    x = x * self.minimumWidth() / self.paintmate.database.settings[width]
                    y = y * self.minimumHeight() / self.paintmate.database.settings[height]
                    points.append(QPoint(int(x), int(y)))
                painter.setPen(QPen(QColor(0, 0, 0, 0), 0))
                painter.setBrush(QBrush(QColor(*map(int, object_color.split('|')))))
                painter.drawPolygon(points)
                if f"{name}_filler_{identifier}" not in map(lambda e: e.text(),
                                                            self.paintmate.radio_group.buttons()):
                    button = QRadioButton(f"{name}_filler_{identifier}", self.paintmate.objects_area_layout_widget)
                    self.paintmate.objects_area_layout.addWidget(button)
                    self.paintmate.radio_group.addButton(button)
        painter.end()

    def ghost_paint(self, painter):
        """
        paintEvent-like function that is used for displaying the previous frame under the current as a trail
        :param painter:
        :return:
        """

        for elem in self.paintmate.database.objects(1):
            (identifier, frame_id, object_stroke_width, object_color, x, y, xx, yy,
             object_z_index, object_fill_color, name) = elem
            if object_stroke_width is not None:
                object_stroke_width = (object_stroke_width / self.paintmate.database.settings[width] *
                                       self.minimumWidth())
            if all(map(lambda el: (False if el is None else True), elem[:-1])):  # ellipse
                painter.setPen(QPen(QColor(0, 0, 0, 255 // self.alpha_divisor), object_stroke_width))
                x = int(x * self.minimumWidth() / self.paintmate.database.settings[width])
                y = int(y * self.minimumHeight() / self.paintmate.database.settings[height])
                xx = int(xx * self.minimumWidth() / self.paintmate.database.settings[width])
                yy = int(yy * self.minimumHeight() / self.paintmate.database.settings[height])
                painter.drawEllipse(x, y, xx - x, yy - y)
            elif all(map(lambda el: (False if el[0] is None else True) == el[1],
                         zip(elem[:-1], (True,) * 9 + (False,)))):  # line
                painter.setPen(QPen(QColor(0, 0, 0, 255 // self.alpha_divisor), object_stroke_width))
                x = int(x * self.minimumWidth() / self.paintmate.database.settings[width])
                y = int(y * self.minimumHeight() / self.paintmate.database.settings[height])
                xx = int(xx * self.minimumWidth() / self.paintmate.database.settings[width])
                yy = int(yy * self.minimumHeight() / self.paintmate.database.settings[height])
                painter.drawLine(x, y, xx, yy)
            elif all(map(lambda el: (False if el[0] is None else True) == el[1],
                         zip(elem[:-1], (True,) * 4 + (False,) * 4 + (True,) + (False,)))):  # pen
                painter.setBrush(QBrush(QColor(0, 0, 0, 255 // self.alpha_divisor)))
                for _, __, x, y in self.paintmate.database.object_points(identifier, pen):
                    x = x * self.minimumWidth() / self.paintmate.database.settings[width]
                    y = y * self.minimumHeight() / self.paintmate.database.settings[height]
                    painter.drawEllipse(QPoint(int(x), int(y)), object_stroke_width, object_stroke_width)
            else:  # filler
                points = list()
                for _, __, x, y in self.paintmate.database.object_points(identifier, filler):
                    x = x * self.minimumWidth() / self.paintmate.database.settings[width]
                    y = y * self.minimumHeight() / self.paintmate.database.settings[height]
                    points.append(QPoint(int(x), int(y)))
                painter.setBrush(QBrush(QColor(0, 0, 0, 255 // self.alpha_divisor)))
                painter.drawPolygon(points)

    def render_self(self):
        image = QImage(self.minimumWidth(), self.minimumHeight(), QImage.Format_ARGB32)
        # image.setDevicePixelRatio(2)
        self.render(image)
        if self.paintmate.database.settings[current_frame] < self.paintmate.database.settings[count_of_frames]:
            self.paintmate.database.update_settings(current_frame=self.paintmate.database.settings[current_frame] + 1)
        return image

    def wheelEvent(self, event):
        if not (event.modifiers() & Qt.ControlModifier):
            self.paintmate.drawing_area.verticalScrollBar().setEnabled(True)
            return
        self.paintmate.drawing_area.verticalScrollBar().setEnabled(False)
        aspect_ratio = self.minimumWidth() / self.minimumHeight()
        if event.angleDelta().y() > 0:
            new_width = self.minimumWidth() + self.paintmate.database.settings[scale_step]
            self.parent().setMinimumWidth(new_width)
            self.parent().setMinimumHeight(int(new_width / aspect_ratio))
            self.setMinimumWidth(new_width)
            self.setMinimumHeight(int(new_width / aspect_ratio))
        else:
            if self.minimumWidth() < canvas_size_limit or self.minimumHeight() < canvas_size_limit:
                return
            new_width = self.minimumWidth() - self.paintmate.database.settings[scale_step]
            self.setMinimumWidth(new_width)
            self.setMinimumHeight(int(new_width / aspect_ratio))
            self.parent().setMinimumWidth(new_width)
            self.parent().setMinimumHeight(int(new_width / aspect_ratio))

    def hand_resize(self, new_width, new_height):
        if new_width != self.minimumWidth():
            self.parent().setMinimumWidth(new_width)
            self.setMinimumWidth(new_width)
        if new_height != self.minimumHeight():
            self.parent().setMinimumHeight(new_height)
            self.setMinimumHeight(new_height)

    def mouseMoveEvent(self, event):
        self.delta_bounds[0][1], self.delta_bounds[1][1] = event.x(), event.y()
        if self.paintmate.current_tool == manipulator:
            for elem in self.paintmate.radio_group.buttons()[1:]:
                if elem.isChecked():
                    self.paintmate.database.reposition(elem.text(), *map(lambda e: e[1] - e[0], self.delta_bounds))
        elif self.paintmate.current_tool == pen:
            self.paintmate.database.create_pen_point(event.x(), event.y(), self.minimumWidth(), self.minimumHeight())
        elif self.paintmate.current_tool == filler:
            self.paintmate.database.create_filler_point(event.x(), event.y(), self.minimumWidth(), self.minimumHeight())
        elif self.paintmate.current_tool == line:
            self.paintmate.database.update_last_line_object(event.x(), event.y(),
                                                            self.minimumWidth(), self.minimumHeight())
        elif self.paintmate.current_tool == ellipse:
            self.paintmate.database.update_last_ellipse_object(event.x(),
                                                               event.y(), self.minimumWidth(), self.minimumHeight())
        self.delta_bounds[0][0], self.delta_bounds[1][0] = event.x(), event.y()
        self.repaint()

    def mousePressEvent(self, event):
        self.delta_bounds[0][0], self.delta_bounds[1][0] = event.x(), event.y()
        if self.paintmate.current_tool == pen:
            self.paintmate.database.create_pen_object()
            self.paintmate.database.create_pen_point(event.x(), event.y(), self.minimumWidth(), self.minimumHeight())
        elif self.paintmate.current_tool == filler:
            self.paintmate.database.create_filler_object()
            self.paintmate.database.create_filler_point(event.x(), event.y(), self.minimumWidth(), self.minimumHeight())
        elif self.paintmate.current_tool == line:
            self.paintmate.database.create_line_object(event.x(), event.y(), self.minimumWidth(), self.minimumHeight())
        elif self.paintmate.current_tool == ellipse:
            self.paintmate.database.create_ellipse_object(event.x(), event.y(),
                                                          self.minimumWidth(), self.minimumHeight())
        self.repaint()


class Database(DeviceInfo):
    def __init__(self):
        super().__init__()
        self.database = None
        self.query = None
        self.settings = dict()
        self.tables_description = {
            "setting": "fps INTEGER, current_frame INTEGER, count_of_frames INTEGER, width INTEGER, height INTEGER, "
                       "timeline_multiplier INTEGER, scale_step INTEGER, stroke_width INTEGER, color TEXT, "
                       "fill_color TEXT, ghost INTEGER",
            "pen_point": "pen_id INTEGER, x INTEGER, y INTEGER",
            "pen": "frame_id INTEGER, stroke_width INTEGER, color TEXT, z_index INTEGER, name TEXT",
            "line": "frame_id INTEGER, stroke_width INTEGER, color TEXT, x INTEGER, y INTEGER, xx INTEGER, yy INTEGER, "
                    "z_index INTEGER, name TEXT",
            "ellipse": "frame_id INTEGER, stroke_width INTEGER, color TEXT, "
                       "x INTEGER, y INTEGER, xx INTEGER, yy INTEGER, fill_color TEXT, z_index INTEGER, name TEXT",
            "filler_point": "filler_id INTEGER, x INTEGER, y INTEGER",
            "filler": "frame_id INTEGER, color TEXT, z_index INTEGER, name TEXT"
        }

    def connect(self, database_file):
        self.database = sqlite3.connect(database_file, check_same_thread=False)
        self.query = self.database.cursor()

    def populate(self):
        for table_name, description in self.tables_description.items():
            self.query.execute(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY AUTOINCREMENT, {description})")
        self.query.execute(f"INSERT INTO setting({', '.join(self.tables_description['setting'].split()[::2])}) "
                           f"VALUES(16, 1, 1, 1920, 1080, 100, 40, 4, '0|0|0|255', '0|0|0|0', 1)")
        self.database.commit()

    def load_settings(self):
        with self.database:
            self.query = self.database.cursor()
            for name, setting in zip(["delete"] + self.tables_description["setting"].split()[::2],
                                     itertools.chain(*self.query.execute("SELECT * FROM setting"))):
                self.settings[name] = setting
            del self.settings["delete"]

    def update_settings(self, **settings):
        for setting, value in settings.items():
            if isinstance(value, tuple):
                if not value[-1]:
                    return
                value = value[0]
            with self.database:
                self.query = self.database.cursor()
                self.query.execute(f"UPDATE setting SET {setting} = {value}")
            if setting == current_frame:
                if value > self.settings[count_of_frames]:
                    with self.database:
                        self.query = self.database.cursor()
                        self.query.execute(f"UPDATE setting SET count_of_frames = {value}")
        self.database.commit()
        self.load_settings()

    def set_object_properties(self, object_identifier, new_name, new_stroke_width, new_stroke_color, new_filler_color):
        _, object_type, identifier = object_identifier.split('_')
        if new_stroke_color and isinstance(new_stroke_color, tuple):
            new_stroke_color = '|'.join(map(str, new_stroke_color))
        if new_filler_color and isinstance(new_filler_color, tuple):
            new_filler_color = '|'.join(map(str, new_filler_color))
        if object_type == pen:
            self.query.execute(f"UPDATE pen SET stroke_width = {new_stroke_width}, "
                               f"color = '{new_stroke_color}', name = '{new_name}' WHERE id = {identifier}")
        elif object_type == filler:
            self.query.execute(f"UPDATE filler SET color = '{new_stroke_color}', name = '{new_name}' "
                               f"WHERE id = {identifier}")
        elif object_type == ellipse:
            self.query.execute(f"UPDATE ellipse SET stroke_width = {new_stroke_width}, "
                               f"color = '{new_stroke_color}', fill_color = '{new_filler_color}', "
                               f"name = '{new_name}' "
                               f"WHERE id = {identifier}")
        else:  # line
            self.query.execute(f"UPDATE line SET stroke_width = {new_stroke_width}, "
                               f"color = '{new_stroke_color}', name = '{new_name}' "
                               f"WHERE id = {identifier}")
        self.database.commit()

    def remove_object(self, object_identifier):
        _, object_type, identifier = object_identifier.split('_')
        if object_type in (ellipse, line):
            self.query.execute(f"DELETE FROM {object_type} WHERE id = {identifier}")
        else:
            self.query.execute(f"DELETE FROM {object_type} WHERE id = {identifier}")
            self.query.execute(f"DELETE FROM {object_type}_point WHERE {object_type}_id NOT IN ("
                               f"SELECT id FROM {object_type})")
        self.database.commit()

    def get_object_poperties(self, object_identifier):
        name, object_type, identifier = object_identifier.split('_')
        if object_type == pen:
            return (name, identifier) + self.query.execute(f"SELECT stroke_width, color, NULL as fill_color "
                                                           f"FROM pen WHERE id = {identifier}").fetchall()[0]
        elif object_type == filler:
            return (name, identifier) + self.query.execute(f"SELECT NULL as stroke_width, color, NULL as fill_color "
                                                           f"FROM filler WHERE id = {identifier}").fetchall()[0]
        elif object_type == line:
            return (name, identifier) + self.query.execute(f"SELECT stroke_width, color, NULL as fill_color "
                                                           f"FROM line WHERE id = {identifier}").fetchall()[0]
        else:  # ellipse
            return (name, identifier) + self.query.execute(f"SELECT stroke_width, color, fill_color "
                                                           f"FROM ellipse WHERE id = {identifier}").fetchall()[0]

    def set_z_index(self, object_identifier, addition):
        _, object_type, identidier = object_identifier.split('_')
        self.query.execute(f"UPDATE {object_type} SET z_index = z_index + {addition} WHERE id = {identidier}")

    def duplicate_frame(self, frame_for_copying, after_that):
        self.query.execute(f"UPDATE ellipse SET frame_id = frame_id + 1 WHERE frame_id > {after_that}")
        self.query.execute(f"UPDATE filler SET frame_id = frame_id + 1 WHERE frame_id > {after_that}")
        self.query.execute(f"UPDATE pen SET frame_id = frame_id + 1 WHERE frame_id > {after_that}")
        self.query.execute(f"UPDATE line SET frame_id = frame_id + 1 WHERE frame_id > {after_that}")
        frame_for_copying += 1 if after_that < frame_for_copying else 0
        for elem in self.query.execute(f"SELECT * FROM ellipse WHERE frame_id = {frame_for_copying}").fetchall():
            self.query.execute("INSERT INTO ellipse(frame_id, stroke_width, color, x, y, xx, yy, fill_color, z_index, "
                               "name) "
                               f"VALUES({after_that + 1}, {elem[2]}, '{elem[3]}', {elem[4]}, {elem[5]}, {elem[6]}, "
                               f"{elem[7]}, '{elem[8]}', {elem[9]}, '{elem[10]}')")
        for elem in self.query.execute(f"SELECT * FROM filler WHERE frame_id = {frame_for_copying}").fetchall():
            self.query.execute("INSERT INTO filler(frame_id, color, z_index, name) "
                               f"VALUES({after_that + 1}, '{elem[2]}', {elem[3]}, '{elem[4]}')")
            for el in self.object_points(elem[0], filler):
                self.query.execute("INSERT INTO filler_point(filler_id, x, y) VALUES("
                                   f"(SELECT id FROM filler ORDER BY -id LIMIT 1), {el[2]}, {el[3]})")
        for elem in self.query.execute(f"SELECT * FROM pen WHERE frame_id = {frame_for_copying}").fetchall():
            self.query.execute("INSERT INTO pen(frame_id, stroke_width, color, z_index, name) "
                               f"VALUES({after_that + 1}, {elem[2]}, '{elem[3]}', {elem[4]}, '{elem[5]}')")
            for el in self.object_points(elem[0], pen):
                self.query.execute("INSERT INTO pen_point(pen_id, x, y) VALUES("
                                   f"(SELECT id FROM pen ORDER BY -id LIMIT 1), {el[2]}, {el[3]})")
        for elem in self.query.execute(f"SELECT * FROM line WHERE frame_id = {frame_for_copying}").fetchall():
            self.query.execute("INSERT INTO line(frame_id, stroke_width, color, x, y, xx, yy, z_index, name) "
                               f"VALUES({after_that + 1}, {elem[2]}, '{elem[3]}', {elem[4]}, {elem[5]}, {elem[6]}, "
                               f"{elem[7]}, {elem[8]}, '{elem[9]}')")
        self.database.commit()

    def delete_frame(self, frame):
        if self.settings[count_of_frames] != 1:
            self.query.execute("UPDATE setting SET count_of_frames = count_of_frames - 1")
        for elem in "ellipse, filler, pen, line".split(", "):
            self.query.execute(f"DELETE FROM {elem} WHERE frame_id = {frame}")
            self.query.execute(f"UPDATE {elem} SET frame_id = frame_id - 1 WHERE frame_id > {frame}")
        for elem in "filler_point, pen_point".split(", "):
            self.query.execute(f"DELETE FROM {elem} WHERE {elem.split('_')[0] + '_' + 'id'} NOT IN "
                               f"(SELECT id FROM {elem.split('_')[0]})")
        self.database.commit()

    def reposition(self, object_name, delta_x, delta_y):
        _, table, identifier = object_name.split('_')
        if table == "filler":
            self.query.execute(f"UPDATE {table}_point "
                               f"SET x = x + {delta_x}, y = y + {delta_y} "
                               f"WHERE filler_id = {identifier}")
        elif table == "pen":
            self.query.execute(f"UPDATE {table}_point "
                               f"SET x = x + {delta_x}, y = y + {delta_y} "
                               f"WHERE pen_id = {identifier}")
        else:
            self.query.execute(f"UPDATE {table} "
                               f"SET x = x + {delta_x}, y = y + {delta_y}, xx = xx + {delta_x}, yy = yy + {delta_y} "
                               f"WHERE id = {identifier}")
        self.database.commit()

    def create_pen_object(self):
        self.query.execute(f"INSERT INTO pen(frame_id, stroke_width, color, z_index, name) VALUES("
                           f"{self.settings[current_frame]}, {self.settings[stroke_width]}, '{self.settings[color]}', "
                           f"0, 'Pen')")
        self.database.commit()

    def create_pen_point(self, x, y, current_width, current_height):
        x = int(x * self.settings[width] / current_width)
        y = int(y * self.settings[height] / current_height)
        self.query.execute(f"INSERT INTO pen_point(pen_id, x, y) VALUES("
                           f"(SELECT id FROM pen ORDER BY -id LIMIT 1), {x}, {y})")
        self.database.commit()

    def create_filler_object(self):
        self.query.execute(f"INSERT INTO filler(frame_id, color, z_index, name) VALUES("
                           f"{self.settings[current_frame]}, '{self.settings[color]}', 0, 'Filler')")
        self.database.commit()

    def create_filler_point(self, x, y, current_width, current_height):
        x = int(x * self.settings[width] / current_width)
        y = int(y * self.settings[height] / current_height)
        self.query.execute(f"INSERT INTO filler_point(filler_id, x, y) VALUES("
                           f"(SELECT id FROM filler ORDER BY -id LIMIT 1), {x}, {y})")
        self.database.commit()

    def create_line_object(self, x, y, current_width, current_height):
        x = int(x * self.settings[width] / current_width)
        y = int(y * self.settings[height] / current_height)
        self.query.execute(f"INSERT INTO line(frame_id, stroke_width, color, x, y, xx, yy, z_index, name) VALUES("
                           f"{self.settings[current_frame]}, {self.settings[stroke_width]}, '{self.settings[color]}', "
                           f"{x}, {y}, {x}, {y}, 0, 'Line')")
        self.database.commit()

    def update_last_line_object(self, x, y, current_width, current_height):
        x = int(x * self.settings[width] / current_width)
        y = int(y * self.settings[height] / current_height)
        self.query.execute(f"UPDATE line SET xx = {x}, yy = {y} WHERE id = (SELECT id FROM line ORDER BY -id LIMIT 1)")
        self.database.commit()

    def create_ellipse_object(self, x, y, current_width, current_height):
        x = int(x * self.settings[width] / current_width)
        y = int(y * self.settings[height] / current_height)
        self.query.execute(f"INSERT INTO ellipse(frame_id, stroke_width, color, x, y, xx, yy, fill_color, z_index, "
                           f"name) "
                           f"VALUES("
                           f"{self.settings[current_frame]}, {self.settings[stroke_width]}, '{self.settings[color]}', "
                           f"{x}, {y}, {x}, {y}, '{self.settings[fill_color]}', 0, 'Ellipse')")
        self.database.commit()

    def update_last_ellipse_object(self, x, y, current_width, current_height):
        x = int(x * self.settings[width] / current_width)
        y = int(y * self.settings[height] / current_height)
        self.query.execute(f"UPDATE ellipse SET xx = {x}, yy = {y} WHERE id = ("
                           f"SELECT id FROM ellipse ORDER BY -id LIMIT 1)")
        self.database.commit()

    def objects(self, frame_offset=0):
        with self.database:
            self.query = self.database.cursor()
            return self.query.execute(f'''SELECT id, frame_id, stroke_width, color, x, y, xx, yy, z_index, fill_color, 
                                          name 
                                          FROM ellipse WHERE frame_id = {self.settings[current_frame] - frame_offset} 
                                          UNION
                                          SELECT id, frame_id, stroke_width, color, x, y, xx, yy, z_index, 
                                          NULL as fill_color, name FROM line WHERE frame_id = 
                                          {self.settings[current_frame] - frame_offset} 
                                          UNION
                                          SELECT id, frame_id, stroke_width, color, NULL as x, NULL as y, NULL as xx, 
                                          NULL as yy, z_index, NULL as fill_color, name FROM pen
                                          WHERE frame_id = {self.settings[current_frame] - frame_offset} 
                                          UNION
                                          SELECT id, frame_id, NULL as stroke_width, color, NULL as x, NULL as y, 
                                          NULL as xx, NULL as yy, z_index, NULL as fill_color, name FROM filler 
                                          WHERE frame_id = {self.settings[current_frame] - frame_offset} 
                                          ORDER BY
                                          z_index''').fetchall()

    def object_points(self, object_id, table):
        return self.query.execute(f"SELECT * FROM {table}_point WHERE "
                                  f"{table}_id = {object_id}").fetchall()


if __name__ == "__main__":
    application = QApplication(sys.argv)
    window = Paintmate()
    sys.exit(application.exec())
