# This Python file uses the following encoding: utf-8
import sys
import os
import json
import time
import threading
from datetime import datetime, timedelta

import mss
import cv2
import numpy as np

from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QWidget, QMenu
from PySide6.QtCore import Qt, QTimer, QStandardPaths, Signal, QObject, QPoint, QRect
from PySide6.QtGui import QPainter, QPen, QColor, QAction, QShortcut, QKeySequence, QFont

from ui_form import Ui_MainWindow

class SelectionWindow(QWidget):
    selection_completed = Signal(tuple)  # 选择完成信号
    selection_canceled = Signal()        # 选择取消信号
    
    def __init__(self):
        super().__init__()
        self.initUI()
        self.initVariables()

    def initUI(self):
        from PySide6.QtWidgets import QLabel
        from PySide6.QtGui import QGuiApplication
        # 设置全屏无边框窗口
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # 获取主屏幕几何
        screen = QGuiApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())
        else:
            self.setGeometry(0, 0, 1920, 1080)  # 默认分辨率
        # 设置半透明背景
        self.setStyleSheet("background-color: rgba(0, 0, 0, 128);")
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # 提示文本标签
        self.tip_label = QLabel(self)
        self.tip_label.setText("点击拖动选择范围 再次点击平移选择区域 ESC键退出 双击确认选择范围")
        self.tip_label.setStyleSheet("color: white; background: rgba(0,0,0,180); padding: 8px; border-radius: 4px;")
        self.tip_label.setFont(QFont("Microsoft YaHei", 10))
        # 提示标签位置（左上角）
        self.tip_label.move(20, 20)
        self.tip_label.adjustSize()

    def initVariables(self):
        # 区域选择相关变量
        self.selecting = False  # 是否正在绘制选择框
        self.moving = False     # 是否正在平移选择框
        self.start_point = QPoint()  # 选择框起始点
        self.end_point = QPoint()    # 选择框结束点
        self.current_rect = QRect()  # 当前选择的矩形区域
        self.drag_offset = QPoint()  # 平移时的鼠标偏移量

    def keyPressEvent(self, event):
        # ESC键优先级最高，取消选择
        if event.key() == Qt.Key_Escape:
            self.selection_canceled.emit()
            self.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            mouse_pos = event.pos()
            # 情况1：点击已存在的选择框 → 进入平移模式
            if self.current_rect.contains(mouse_pos) and not self.selecting:
                self.moving = True
                self.drag_offset = mouse_pos - self.current_rect.topLeft()
            # 情况2：未选择区域 → 开始绘制选择框
            else:
                self.selecting = True
                self.start_point = mouse_pos
                self.end_point = mouse_pos

    def mouseMoveEvent(self, event):
        from PySide6.QtGui import QGuiApplication
        mouse_pos = event.pos()
        # 绘制选择框
        if self.selecting and event.buttons() == Qt.LeftButton:
            self.end_point = mouse_pos
            # 实时更新 current_rect，确保拖动时实时显示
            self.current_rect = self.getNormalizedRect(self.start_point, self.end_point)
            self.update()  # 触发paintEvent重绘
        # 平移选择框
        elif self.moving and event.buttons() == Qt.LeftButton:
            new_top_left = mouse_pos - self.drag_offset
            # 限制平移范围在屏幕内
            new_rect = QRect(new_top_left, self.current_rect.size())
            screen = QGuiApplication.primaryScreen()
            if screen:
                screen_rect = screen.geometry()
            else:
                screen_rect = QRect(0, 0, 1920, 1080)
            if screen_rect.contains(new_rect):
                self.current_rect = new_rect
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.selecting:
                # 完成选择框绘制，更新当前矩形
                self.current_rect = self.getNormalizedRect(self.start_point, self.end_point)
                self.selecting = False
            elif self.moving:
                # 结束平移
                self.moving = False
            self.update()

    def mouseDoubleClickEvent(self, event):
        # 双击确认选择（仅当存在有效选择框时）
        if not self.current_rect.isNull():
            rect = (self.current_rect.x(), self.current_rect.y(), 
                   self.current_rect.width(), self.current_rect.height())
            self.selection_completed.emit(rect)
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        # 绘制半透明灰色遮罩（反选区域）
        self.drawBackgroundMask(painter)
        # 绘制选择框（红色边框+半透明白色背景）
        if not self.current_rect.isNull():
            self.drawSelectionRect(painter)

    def drawBackgroundMask(self, painter):
        from PySide6.QtGui import QGuiApplication
        # 绘制全屏遮罩，扣除选择框区域
        screen = QGuiApplication.primaryScreen()
        if screen:
            screen_rect = screen.geometry()
        else:
            screen_rect = QRect(0, 0, 1920, 1080)  # 默认分辨率
        # 遮罩颜色：半透明灰色
        mask_color = QColor(128, 128, 128, 150)
        painter.setBrush(mask_color)
        painter.setPen(Qt.NoPen)

        # 如果有选择框，绘制四个遮罩区域（上下左右）
        if not self.current_rect.isNull():
            # 上
            painter.drawRect(screen_rect.left(), screen_rect.top(), screen_rect.width(), self.current_rect.top())
            # 下
            painter.drawRect(screen_rect.left(), self.current_rect.bottom(), screen_rect.width(), screen_rect.height() - self.current_rect.bottom())
            # 左
            painter.drawRect(screen_rect.left(), self.current_rect.top(), self.current_rect.left(), self.current_rect.height())
            # 右
            painter.drawRect(self.current_rect.right(), self.current_rect.top(), screen_rect.width() - self.current_rect.right(), self.current_rect.height())
        else:
            # 无选择框时绘制全屏遮罩
            painter.drawRect(screen_rect)

    def drawSelectionRect(self, painter):
        # 选择框边框：红色粗线
        pen = QPen(QColor(255, 0, 0), 2, Qt.SolidLine)
        painter.setPen(pen)
        # 选择框背景：半透明白色
        brush = QColor(255, 255, 255, 50)
        painter.setBrush(brush)
        # 绘制选择框
        painter.drawRect(self.current_rect)
        
        # 显示尺寸信息
        size_text = f"{self.current_rect.width()} x {self.current_rect.height()}"
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(self.current_rect.x() + 5, self.current_rect.y() + 20, size_text)

    def getNormalizedRect(self, p1, p2):
        # 确保矩形的左上角为较小值，右下角为较大值（处理从右下往左上拖动的情况）
        x1 = min(p1.x(), p2.x())
        y1 = min(p1.y(), p2.y())
        x2 = max(p1.x(), p2.x())
        y2 = max(p1.y(), p2.y())
        return QRect(x1, y1, x2 - x1, y2 - y1)

class ScreenRecorder(QObject):
    finished = Signal()

    def __init__(self, region, output_file, fps):
        super().__init__()
        self.region = region
        self.output_file = output_file
        self.fps = fps
        self.is_recording = False
        self.recording_thread = None

    def start(self):
        self.is_recording = True
        self.recording_thread = threading.Thread(target=self._record)
        self.recording_thread.daemon = True
        self.recording_thread.start()

    def stop(self):
        self.is_recording = False
        if self.recording_thread:
            self.recording_thread.join()
        self.finished.emit()

    def _record(self):
        try:
            x, y, width, height = self.region

            # 确保输出目录存在
            output_dir = os.path.dirname(self.output_file)
            os.makedirs(output_dir, exist_ok=True)

            # 根据文件扩展名选择编码器
            ext = os.path.splitext(self.output_file)[1].lower()
            if ext == '.mp4':
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            elif ext == '.avi':
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
            elif ext == '.mkv':
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
            elif ext == '.mov':
                fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            else:
                fourcc = cv2.VideoWriter_fourcc(*'XVID')

            # 创建视频写入器
            out = cv2.VideoWriter(self.output_file, fourcc, self.fps, (width, height))

            if not out.isOpened():
                print(f"无法打开视频文件: {self.output_file}")
                return

            with mss.mss() as sct:
                monitor = {'top': y, 'left': x, 'width': width, 'height': height}

                while self.is_recording:
                    # 捕获屏幕
                    screenshot = sct.grab(monitor)
                    img = np.array(screenshot)
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                    # 写入视频
                    out.write(img)

                    # 控制帧率
                    time.sleep(1 / self.fps)

            # 释放资源
            out.release()
        except Exception as e:
            print(f"录制过程出错: {e}")

class ImageCapture(QObject):
    captured = Signal(str)  # 发送捕获的文件路径

    def __init__(self, region, output_folder, image_format):
        super().__init__()
        self.region = region
        self.output_folder = output_folder
        self.image_format = image_format

    def capture(self, count):
        """捕获屏幕并保存图片"""
        try:
            if not self.region:
                return None

            x, y, width, height = self.region

            # 确保输出目录存在
            os.makedirs(self.output_folder, exist_ok=True)

            # 生成文件名
            output_file = os.path.join(self.output_folder, f"{count}.{self.image_format}")

            # 使用Qt的截图功能，确保坐标系统一致
            from PySide6.QtGui import QGuiApplication, QPixmap
            
            # 获取屏幕
            screen = QGuiApplication.primaryScreen()
            if not screen:
                print("[DEBUG] 无法获取屏幕")
                return None
            
            # 使用Qt的grabWindow方法截取指定区域
            # 在Qt6中，使用窗口ID 0表示桌面
            pixmap = screen.grabWindow(0, x, y, width, height)
            
            # 保存图片
            pixmap.save(output_file)

            self.captured.emit(output_file)
            return output_file
        except Exception as e:
            print(f"截图过程出错: {e}")
            return None

class PDFExporter(QObject):
    exported = Signal(str)  # 发送生成的 PDF 文件路径

    def __init__(self, region, output_pdf, temp_folder):
        super().__init__()
        self.region = region
        self.output_pdf = output_pdf
        self.temp_folder = temp_folder
        self.captured_images = []

    def capture(self, count):
        """捕获屏幕并保存临时图片"""
        if not self.region:
            return None

        x, y, width, height = self.region
        
        # 调试信息
        print(f"[DEBUG] 截图区域: ({x}, {y}, {width}, {height})")

        # 确保临时目录存在
        os.makedirs(self.temp_folder, exist_ok=True)

        # 生成临时文件名
        temp_file = os.path.join(self.temp_folder, f"{count}.png")

        # 使用Qt的截图功能，确保坐标系统一致
        from PySide6.QtGui import QGuiApplication, QPixmap
        
        # 获取屏幕
        screen = QGuiApplication.primaryScreen()
        if not screen:
            print("[DEBUG] 无法获取屏幕")
            return None
        
        # 使用Qt的grabWindow方法截取指定区域
        # 在Qt6中，使用窗口ID 0表示桌面
        pixmap = screen.grabWindow(0, x, y, width, height)
        
        # 保存图片
        pixmap.save(temp_file)
        
        # 验证文件
        if os.path.exists(temp_file):
            print(f"[DEBUG] 图片保存成功: {temp_file}")
            # 获取保存的图片尺寸
            from PIL import Image
            saved_img = Image.open(temp_file)
            print(f"[DEBUG] 保存的图片尺寸: {saved_img.size}")
            saved_img.close()
        else:
            print(f"[DEBUG] 图片保存失败: {temp_file}")
            return None

        self.captured_images.append(temp_file)
        return temp_file

    def export(self):
        """生成 PDF 文件"""
        try:
            if not self.captured_images:
                return None

            # 确保输出目录存在
            output_dir = os.path.dirname(self.output_pdf)
            os.makedirs(output_dir, exist_ok=True)

            # 生成 PDF
            from reportlab.pdfgen import canvas

            # 读取第一张图片来决定页面尺寸
            from PIL import Image
            first_img = Image.open(self.captured_images[0])
            first_img_width, first_img_height = first_img.size
            first_img.close()

            # 关键改进：让PDF页面尺寸反向适配图片
            # 使用图片尺寸作为页面尺寸（转换为点：1英寸=72点，假设屏幕DPI=96）
            dpi = 96
            page_width = (first_img_width / dpi) * 72
            page_height = (first_img_height / dpi) * 72
            
            print(f"[DEBUG] 第一张图片尺寸: {first_img_width} x {first_img_height}")
            print(f"[DEBUG] PDF页面尺寸: {page_width:.2f} x {page_height:.2f} 点")

            # 创建canvas，使用适配图片的页面尺寸
            c = canvas.Canvas(self.output_pdf, pagesize=(page_width, page_height))

            # 处理所有图片
            for idx, img_path in enumerate(self.captured_images):
                # 读取图片
                img = Image.open(img_path)
                img_w, img_h = img.size
                
                print(f"[DEBUG] 第 {idx+1} 张图片尺寸: {img_w} x {img_h}")

                # 转换图片尺寸为点
                img_w_points = (img_w / dpi) * 72
                img_h_points = (img_h / dpi) * 72
                
                print(f"[DEBUG] 图片尺寸（点）: {img_w_points:.2f} x {img_h_points:.2f}")

                # 计算缩放比例，确保图片完整适应页面
                scale_w = page_width / img_w_points
                scale_h = page_height / img_h_points
                scale = min(scale_w, scale_h)

                scaled_w = img_w_points * scale
                scaled_h = img_h_points * scale
                
                print(f"[DEBUG] 缩放比例: {scale:.4f}")
                print(f"[DEBUG] 缩放后尺寸: {scaled_w:.2f} x {scaled_h:.2f}")

                # 计算居中位置（reportlab坐标原点在左下角）
                pos_x = (page_width - scaled_w) / 2
                pos_y = (page_height - scaled_h) / 2
                
                print(f"[DEBUG] 绘制位置: ({pos_x:.2f}, {pos_y:.2f})")

                # 添加图片到 PDF（使用原图尺寸的点单位）
                c.drawImage(img_path, pos_x, pos_y, width=scaled_w, height=scaled_h)
                c.showPage()  # 新建一页
                img.close()

            # 保存PDF
            c.save()
            print("[DEBUG] PDF生成完成")

            # 发送导出完成信号
            self.exported.emit(self.output_pdf)
            return self.output_pdf
        except Exception as e:
            print(f"PDF 生成过程出错: {e}")
            return None
        finally:
            # 无论成功还是失败，都清理临时文件
            self.cleanup()

    def cleanup(self):
        """清理临时文件"""
        import shutil

        # 先清空列表
        self.captured_images = []

        # 逐个删除临时文件
        if os.path.exists(self.temp_folder):
            try:
                for filename in os.listdir(self.temp_folder):
                    file_path = os.path.join(self.temp_folder, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                    except Exception as e:
                        print(f"删除临时文件 {file_path} 失败: {e}")
            except Exception as e:
                print(f"遍历临时文件夹失败: {e}")

            # 最后删除临时文件夹
            try:
                shutil.rmtree(self.temp_folder)
                print(f"临时文件夹已删除: {self.temp_folder}")
            except Exception as e:
                print(f"删除临时文件夹失败: {e}")

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        print("MainWindow 初始化开始")
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        print("UI 初始化完成")

        # 初始化变量
        self.selected_region = None
        self.image_selected_region = None
        self.pdf_selected_region = None
        self.is_recording = False
        self.is_image_recording = False
        self.is_pdf_recording = False
        self.selection_window = None
        self.recording_start_time = None
        self.recording_timer = QTimer()
        self.image_capture_count = 0
        self.pdf_capture_count = 0
        self.screen_recorder = None
        self.image_capture = None
        self.image_output_folder = None
        self.pdf_exporter = None
        self.pdf_temp_folder = None
        self.batch_mode = False  # 批量截图模式
        self.batch_folder = None  # 批量截图的输出文件夹
        self.pdf_batch_mode = False  # PDF 批量截图模式
        self.pdf_temp_images = []  # 存储批量截图的临时图片
        print("变量初始化完成")

        # 获取应用数据目录
        self.app_data_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        self.app_data_dir = os.path.join(self.app_data_dir, "ScreenRecorder")
        os.makedirs(self.app_data_dir, exist_ok=True)
        print(f"应用数据目录: {self.app_data_dir}")

        # 设置文件路径
        self.settings_file = os.path.join(self.app_data_dir, "settings.json")
        self.output_dir = os.path.join(self.app_data_dir, "Recordings")
        os.makedirs(self.output_dir, exist_ok=True)
        print(f"设置文件: {self.settings_file}")
        print(f"输出目录: {self.output_dir}")

        # 连接定时器信号
        self.recording_timer.timeout.connect(self.update_recording_duration)
        print("定时器信号连接完成")

        # 加载设置
        self.load_settings()
        print("设置加载完成")

        # 连接信号
        self.ui.selectRegionBtn.clicked.connect(self.select_region)
        self.ui.startBtn.clicked.connect(self.start_recording)
        self.ui.stopBtn.clicked.connect(self.stop_recording)
        self.ui.browsePathBtn.clicked.connect(self.browse_output_path)
        self.ui.formatComboBox.currentTextChanged.connect(self.update_video_extension)
        print("视频录制信号连接完成")

        # 散图录制信号
        self.ui.imageSelectRegionBtn.clicked.connect(self.select_image_region)
        self.ui.captureBtn.clicked.connect(self.capture_image)
        self.ui.autoStartBtn.clicked.connect(self.start_image_recording)
        self.ui.autoStopBtn.clicked.connect(self.stop_image_recording)
        self.ui.manualStartBtn.clicked.connect(self.start_batch_capture)
        self.ui.manualStopBtn.clicked.connect(self.stop_batch_capture)
        self.ui.imageBrowsePathBtn.clicked.connect(self.browse_image_path)
        print("散图录制信号连接完成")

        # PDF 输出信号
        self.ui.pdfSelectRegionBtn.clicked.connect(self.select_pdf_region)
        self.ui.pdfCaptureBtn.clicked.connect(self.pdf_capture_image)
        self.ui.pdfManualStartBtn.clicked.connect(self.start_pdf_batch_capture)
        self.ui.pdfManualStopBtn.clicked.connect(self.stop_pdf_batch_capture)
        self.ui.pdfAutoStartBtn.clicked.connect(self.start_pdf_recording)
        self.ui.pdfAutoStopBtn.clicked.connect(self.stop_pdf_recording)
        self.ui.pdfBrowsePathBtn.clicked.connect(self.browse_pdf_path)
        print("PDF 输出信号连接完成")

        # 连接菜单
        self.ui.actionExit.triggered.connect(self.close)
        self.ui.actionAlwaysOnTop.triggered.connect(self.toggle_always_on_top)
        self.ui.actionSelectRegion.triggered.connect(self.select_current_region)

        # 添加文件菜单子项
        self.add_file_menu_items()

        # 注册快捷键
        self.register_shortcuts()

        # 初始化快捷键设置
        self.init_shortcut_settings()

        # 初始化扩展名显示
        self.update_video_extension(self.ui.formatComboBox.currentText())

    def add_file_menu_items(self):
        # 清空现有菜单
        self.ui.menu_File.clear()

        # 添加打开设置目录
        open_settings_action = QAction("打开设置目录", self)
        open_settings_action.triggered.connect(self.open_settings_directory)
        self.ui.menu_File.addAction(open_settings_action)

        # 添加打开输出默认目录
        open_output_action = QAction("打开输出默认目录", self)
        open_output_action.triggered.connect(self.open_output_directory)
        self.ui.menu_File.addAction(open_output_action)

        # 添加分隔线
        self.ui.menu_File.addSeparator()

        # 添加退出
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        self.ui.menu_File.addAction(exit_action)

    def register_shortcuts(self):
        """注册快捷键"""
        # 快捷键已经在 update_shortcut_menu 方法中通过 QAction 设置
        # 这里不再重复注册，避免冲突
        pass

    def handle_enter_key(self):
        """处理 Enter 键按下"""
        current_tab = self.ui.modeTabWidget.currentIndex()
        if current_tab == 1:  # 散图录制
            self.capture_image()
        elif current_tab == 2:  # PDF 输出
            self.pdf_capture_image()

    def show_status_message(self, message, timeout=5000):
        """显示状态栏提示消息"""
        self.statusBar().showMessage(message, timeout)

    def init_shortcut_settings(self):
        """初始化快捷键设置"""
        # 加载快捷键设置
        self.shortcut_settings = {
            'select_region': 'Ctrl+A',
            'start_recording': 'Ctrl+P',
            'stop_recording': 'Ctrl+B',
            'capture_image': 'Return'
        }
        
        # 从设置文件加载
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    if 'shortcuts' in settings:
                        self.shortcut_settings.update(settings['shortcuts'])
        except Exception as e:
            print(f"加载快捷键设置出错: {e}")
        
        # 更新快捷键菜单项
        self.update_shortcut_menu()

    def update_shortcut_menu(self):
        """更新快捷键菜单项"""
        # 清空现有快捷键菜单
        self.ui.menu_Shortcuts.clear()
        
        # 添加选择录制区域菜单项
        select_region_action = QAction(f"选择录制区域 ({self.shortcut_settings['select_region']})", self)
        select_region_action.triggered.connect(self.select_current_region)
        select_region_action.setShortcut(QKeySequence(self.shortcut_settings['select_region']))
        # 为菜单项添加右键菜单
        select_region_menu = QMenu(self)
        edit_select_region_action = QAction("修改快捷键", self)
        edit_select_region_action.triggered.connect(lambda: self.edit_shortcut('select_region', select_region_action))
        select_region_menu.addAction(edit_select_region_action)
        select_region_action.setMenu(select_region_menu)
        self.ui.menu_Shortcuts.addAction(select_region_action)
        
        # 添加开始录制菜单项
        start_recording_action = QAction(f"开始录制 ({self.shortcut_settings['start_recording']})", self)
        start_recording_action.triggered.connect(self.start_recording)
        start_recording_action.setShortcut(QKeySequence(self.shortcut_settings['start_recording']))
        # 为菜单项添加右键菜单
        start_recording_menu = QMenu(self)
        edit_start_recording_action = QAction("修改快捷键", self)
        edit_start_recording_action.triggered.connect(lambda: self.edit_shortcut('start_recording', start_recording_action))
        start_recording_menu.addAction(edit_start_recording_action)
        start_recording_action.setMenu(start_recording_menu)
        self.ui.menu_Shortcuts.addAction(start_recording_action)
        
        # 添加停止录制菜单项
        stop_recording_action = QAction(f"停止录制 ({self.shortcut_settings['stop_recording']})", self)
        stop_recording_action.triggered.connect(self.stop_recording)
        stop_recording_action.setShortcut(QKeySequence(self.shortcut_settings['stop_recording']))
        # 为菜单项添加右键菜单
        stop_recording_menu = QMenu(self)
        edit_stop_recording_action = QAction("修改快捷键", self)
        edit_stop_recording_action.triggered.connect(lambda: self.edit_shortcut('stop_recording', stop_recording_action))
        stop_recording_menu.addAction(edit_stop_recording_action)
        stop_recording_action.setMenu(stop_recording_menu)
        self.ui.menu_Shortcuts.addAction(stop_recording_action)
        
        # 添加截取图片菜单项
        capture_image_action = QAction(f"截取图片 ({self.shortcut_settings['capture_image']})", self)
        capture_image_action.triggered.connect(self.handle_enter_key)
        capture_image_action.setShortcut(QKeySequence(self.shortcut_settings['capture_image']))
        # 为菜单项添加右键菜单
        capture_image_menu = QMenu(self)
        edit_capture_image_action = QAction("修改快捷键", self)
        edit_capture_image_action.triggered.connect(lambda: self.edit_shortcut('capture_image', capture_image_action))
        capture_image_menu.addAction(edit_capture_image_action)
        capture_image_action.setMenu(capture_image_menu)
        self.ui.menu_Shortcuts.addAction(capture_image_action)



    def edit_shortcut(self, shortcut_key, action):
        """编辑快捷键"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton
        
        dialog = QDialog(self)
        dialog.setWindowTitle("修改快捷键")
        dialog.resize(300, 150)
        
        layout = QVBoxLayout(dialog)
        
        # 修饰键选择
        modifier_layout = QHBoxLayout()
        modifier_label = QLabel("修饰键:")
        modifier_combo = QComboBox()
        modifier_combo.addItems(["空", "Ctrl", "Alt", "Shift", "Ctrl+Shift", "Ctrl+Alt", "Alt+Shift"])
        modifier_layout.addWidget(modifier_label)
        modifier_layout.addWidget(modifier_combo)
        layout.addLayout(modifier_layout)
        
        # 基本键输入
        key_layout = QHBoxLayout()
        key_label = QLabel("基本键:")
        key_edit = QLineEdit()
        key_edit.setPlaceholderText("请输入键")
        key_layout.addWidget(key_label)
        key_layout.addWidget(key_edit)
        layout.addLayout(key_layout)
        
        # 预览
        preview_label = QLabel("预览:")
        layout.addWidget(preview_label)
        
        # 按钮
        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        # 实时更新预览
        def update_preview():
            modifier = modifier_combo.currentText()
            key = key_edit.text()
            if modifier == "空":
                preview = key
            else:
                preview = f"{modifier}+{key}"
            preview_label.setText(f"预览: {preview}")
        
        modifier_combo.currentTextChanged.connect(update_preview)
        key_edit.textChanged.connect(update_preview)
        
        # 加载当前快捷键
        current_shortcut = self.shortcut_settings[shortcut_key]
        if "+" in current_shortcut:
            parts = current_shortcut.split("+")
            modifier = "+".join(parts[:-1])
            key = parts[-1]
            if modifier in ["空", "Ctrl", "Alt", "Shift", "Ctrl+Shift", "Ctrl+Alt", "Alt+Shift"]:
                modifier_combo.setCurrentText(modifier)
            key_edit.setText(key)
        else:
            modifier_combo.setCurrentText("空")
            key_edit.setText(current_shortcut)
        
        update_preview()
        
        # 确定按钮
        def on_ok():
            modifier = modifier_combo.currentText()
            key = key_edit.text().strip()
            if not key:
                QMessageBox.warning(self, "警告", "请输入基本键")
                return
            
            if modifier == "空":
                new_shortcut = key
            else:
                new_shortcut = f"{modifier}+{key}"
            
            # 检查快捷键冲突
            for k, v in self.shortcut_settings.items():
                if k != shortcut_key and v == new_shortcut:
                    QMessageBox.warning(self, "警告", "该快捷键已被使用")
                    return
            
            # 更新设置
            self.shortcut_settings[shortcut_key] = new_shortcut
            self.save_settings()
            self.update_shortcut_menu()
            dialog.accept()
        
        ok_button.clicked.connect(on_ok)
        cancel_button.clicked.connect(dialog.reject)
        
        dialog.exec()

    def open_settings_directory(self):
        """打开设置文件目录"""
        if os.path.exists(self.app_data_dir):
            os.startfile(self.app_data_dir)
        else:
            QMessageBox.warning(self, "警告", "设置目录不存在！")

    def open_output_directory(self):
        """打开输出默认目录"""
        if os.path.exists(self.output_dir):
            os.startfile(self.output_dir)
        else:
            QMessageBox.warning(self, "警告", "输出目录不存在！")

    def toggle_always_on_top(self):
        """切换保持置顶"""
        if self.ui.actionAlwaysOnTop.isChecked():
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        self.show()

    def select_current_region(self):
        """根据当前标签页选择对应的区域"""
        current_tab = self.ui.modeTabWidget.currentIndex()
        if current_tab == 0:  # 视频录制
            self.select_region()
        elif current_tab == 1:  # 散图录制
            self.select_image_region()
        elif current_tab == 2:  # PDF 输出
            self.select_pdf_region()

    def select_region(self):
        """选择视频录制区域"""
        self.hide()

        self.selection_window = SelectionWindow()
        self.selection_window.selection_completed.connect(self.on_region_selection_completed)
        self.selection_window.selection_canceled.connect(self.on_region_selection_canceled)
        self.selection_window.show()

    def on_region_selection_completed(self, region):
        """视频区域选择完成回调"""
        x, y, width, height = region
        self.selected_region = (x, y, width, height)
        self.ui.regionLabel.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()

    def on_region_selection_canceled(self):
        """视频区域选择取消回调"""
        self.show()
        if not self.selected_region:
            self.ui.regionLabel.setText("当前区域: 未选择")

    def select_image_region(self):
        """选择散图录制区域"""
        self.hide()

        self.selection_window = SelectionWindow()
        self.selection_window.selection_completed.connect(self.on_image_region_selection_completed)
        self.selection_window.selection_canceled.connect(self.on_image_region_selection_canceled)
        self.selection_window.show()

    def on_image_region_selection_completed(self, region):
        """散图区域选择完成回调"""
        x, y, width, height = region
        self.image_selected_region = (x, y, width, height)
        self.ui.imageRegionLabel.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()

    def on_image_region_selection_canceled(self):
        """散图区域选择取消回调"""
        self.show()
        if not self.image_selected_region:
            self.ui.imageRegionLabel.setText("当前区域: 未选择")

    def select_pdf_region(self):
        """选择 PDF 输出区域"""
        self.hide()

        self.selection_window = SelectionWindow()
        self.selection_window.selection_completed.connect(self.on_pdf_region_selection_completed)
        self.selection_window.selection_canceled.connect(self.on_pdf_region_selection_canceled)
        self.selection_window.show()

    def on_pdf_region_selection_completed(self, region):
        """PDF 区域选择完成回调"""
        x, y, width, height = region
        self.pdf_selected_region = (x, y, width, height)
        self.ui.pdfRegionLabel.setText(f"当前区域: ({x}, {y}) {width}x{height}")
        self.show()

    def on_pdf_region_selection_canceled(self):
        """PDF 区域选择取消回调"""
        self.show()
        if not self.pdf_selected_region:
            self.ui.pdfRegionLabel.setText("当前区域: 未选择")

    def update_video_extension(self, format):
        """更新视频文件扩展名"""
        self.ui.extensionLabel.setText(f".{format}")

    def get_video_output_path(self):
        """获取视频输出路径"""
        path = self.ui.outputPathLineEdit.text()
        if not os.path.isabs(path):
            path = os.path.join(self.app_data_dir, path)
        os.makedirs(path, exist_ok=True)
        filename = self.ui.outputFileNameLineEdit.text()
        format = self.ui.formatComboBox.currentText()
        return os.path.join(path, f"{filename}.{format}")

    def get_image_output_path(self):
        """获取图片输出路径"""
        path = self.ui.imagePathLineEdit.text()
        if not os.path.isabs(path):
            path = os.path.join(self.app_data_dir, path)
        os.makedirs(path, exist_ok=True)
        return path

    def get_pdf_output_path(self):
        """获取 PDF 输出路径"""
        path = self.ui.pdfPathLineEdit.text()
        if not os.path.isabs(path):
            path = os.path.join(self.app_data_dir, path)
        os.makedirs(path, exist_ok=True)
        filename = self.ui.pdfFileNameLineEdit.text()
        return os.path.join(path, f"{filename}.pdf")

    def start_recording(self):
        try:
            current_tab = self.ui.modeTabWidget.currentIndex()
            if current_tab == 0:  # 视频录制
                if not self.selected_region:
                    QMessageBox.warning(self, "警告", "请先选择录制区域！")
                    return

                output_format = self.ui.formatComboBox.currentText()
                output_file = self.get_video_output_path()
                fps = self.ui.fpsSpinBox.value()

                # 验证输出路径
                output_dir = os.path.dirname(output_file)
                if not os.access(os.path.dirname(output_dir), os.W_OK):
                    QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                    return

                # 创建 ScreenRecorder 实例
                self.screen_recorder = ScreenRecorder(self.selected_region, output_file, fps)
                self.screen_recorder.finished.connect(self.on_recording_finished)

                self.is_recording = True
                self.recording_start_time = datetime.now()

                # 更新 UI 状态
                self.ui.startBtn.setEnabled(False)
                self.ui.stopBtn.setEnabled(True)
                self.ui.selectRegionBtn.setEnabled(False)
                self.ui.statusLabel.setText("状态: 录制中...")
                self.ui.durationLabel.setText("已录制: 00:00:00")

                # 启动定时器，每秒更新一次录制时长
                self.recording_timer.start(1000)

                # 开始录制
                self.screen_recorder.start()

                print(f"[DEBUG] 开始录制:")
                print(f"  区域: {self.selected_region}")
                print(f"  格式: {output_format}")
                print(f"  文件: {output_file}")
                print(f"  帧率: {fps}")

                self.show_status_message(f"开始录制！输出文件: {output_file}", 10000)
            elif current_tab == 1:  # 散图录制
                self.start_image_recording()
            elif current_tab == 2:  # PDF 输出
                self.start_pdf_recording()
        except Exception as e:
            print(f"开始录制出错: {e}")
            QMessageBox.critical(self, "错误", f"开始录制失败: {str(e)}")
            # 恢复 UI 状态
            current_tab = self.ui.modeTabWidget.currentIndex()
            if current_tab == 0:
                self.ui.startBtn.setEnabled(True)
                self.ui.stopBtn.setEnabled(False)
                self.ui.selectRegionBtn.setEnabled(True)
                self.ui.statusLabel.setText("状态: 就绪")
            elif current_tab == 1:
                self.ui.autoStartBtn.setEnabled(True)
                self.ui.autoStopBtn.setEnabled(False)
                self.ui.imageStatusLabel.setText("状态: 就绪")
            elif current_tab == 2:
                self.ui.pdfAutoStartBtn.setEnabled(True)
                self.ui.pdfAutoStopBtn.setEnabled(False)
                self.ui.pdfStatusLabel.setText("状态: 就绪")

    def stop_recording(self):
        try:
            current_tab = self.ui.modeTabWidget.currentIndex()
            if current_tab == 0:  # 视频录制
                if not self.is_recording:
                    return

                # 停止录制
                if self.screen_recorder:
                    self.screen_recorder.stop()

                self.is_recording = False
                self.recording_start_time = None

                # 停止定时器
                self.recording_timer.stop()

                # 更新 UI 状态
                self.ui.startBtn.setEnabled(True)
                self.ui.stopBtn.setEnabled(False)
                self.ui.selectRegionBtn.setEnabled(True)
                self.ui.statusLabel.setText("状态: 已停止")
            elif current_tab == 1:  # 散图录制
                self.stop_image_recording()
            elif current_tab == 2:  # PDF 输出
                self.stop_pdf_recording()
        except Exception as e:
            print(f"停止录制出错: {e}")
            QMessageBox.critical(self, "错误", f"停止录制失败: {str(e)}")
            # 恢复 UI 状态
            current_tab = self.ui.modeTabWidget.currentIndex()
            if current_tab == 0:
                self.is_recording = False
                if hasattr(self, 'recording_timer') and self.recording_timer:
                    self.recording_timer.stop()
                self.ui.startBtn.setEnabled(True)
                self.ui.stopBtn.setEnabled(False)
                self.ui.selectRegionBtn.setEnabled(True)
                self.ui.statusLabel.setText("状态: 已停止")
            elif current_tab == 1:
                self.is_image_recording = False
                if hasattr(self, 'image_timer') and self.image_timer:
                    self.image_timer.stop()
                self.ui.autoStartBtn.setEnabled(True)
                self.ui.autoStopBtn.setEnabled(False)
                self.ui.imageStatusLabel.setText("状态: 已停止")
            elif current_tab == 2:
                self.is_pdf_recording = False
                if hasattr(self, 'pdf_timer') and self.pdf_timer:
                    self.pdf_timer.stop()
                self.ui.pdfAutoStartBtn.setEnabled(True)
                self.ui.pdfAutoStopBtn.setEnabled(False)
                self.ui.pdfStatusLabel.setText("状态: 已停止")

    def on_recording_finished(self):
        """录制完成回调"""
        try:
            output_file = self.get_video_output_path()
            if os.path.exists(output_file):
                self.show_status_message(f"录制已停止！保存到: {output_file}", 10000)
            else:
                self.show_status_message(f"录制已停止，但文件可能未保存成功！预期路径: {output_file}", 10000)
        except Exception as e:
            print(f"录制完成回调出错: {e}")
            QMessageBox.critical(self, "错误", f"处理录制完成事件时出错: {str(e)}")

    def capture_image(self):
        """手动截取图片"""
        try:
            if not self.image_selected_region:
                QMessageBox.warning(self, "警告", "请先选择截图区域！")
                return

            # 获取输出路径
            base_path = self.get_image_output_path()
            
            # 验证输出路径
            if not os.access(os.path.dirname(base_path), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 获取图片格式
            image_format = self.ui.imageFormatComboBox.currentText()

            # 如果处于批量模式，使用批量文件夹
            if self.batch_mode and self.batch_folder:
                output_folder = self.batch_folder
                # 创建 ImageCapture 实例
                image_capture = ImageCapture(self.image_selected_region, output_folder, image_format)
                image_capture.captured.connect(self.on_image_captured)
                
                # 捕获图片
                self.image_capture_count += 1
                output_file = image_capture.capture(self.image_capture_count)

                if output_file:
                    # 更新状态
                    self.ui.imageStatusLabel.setText(f"状态: 批量模式已截取 {self.image_capture_count} 张图片")
                    print(f"[DEBUG] 批量截取图片:")
                    print(f"  区域: {self.image_selected_region}")
                    print(f"  格式: {image_format}")
                    print(f"  文件: {output_file}")
                else:
                    # 截图失败
                    self.image_capture_count -= 1
                    self.ui.imageStatusLabel.setText("状态: 截图失败")
                    QMessageBox.warning(self, "警告", "截图失败，请检查权限或空间！")
            else:
                # 单次截图模式
                # 创建时间戳文件夹
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                folder_name = self.ui.imageFileNameLineEdit.text()
                output_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
                os.makedirs(output_folder, exist_ok=True)
                
                # 创建 ImageCapture 实例
                image_capture = ImageCapture(self.image_selected_region, output_folder, image_format)
                image_capture.captured.connect(self.on_image_captured)

                # 捕获图片
                self.image_capture_count += 1
                output_file = image_capture.capture(self.image_capture_count)

                if output_file:
                    # 更新状态
                    self.ui.imageStatusLabel.setText(f"状态: 已截取 {self.image_capture_count} 张图片")
                    print(f"[DEBUG] 手动截取图片:")
                    print(f"  区域: {self.image_selected_region}")
                    print(f"  格式: {image_format}")
                    print(f"  文件: {output_file}")
                else:
                    # 截图失败，重置计数器
                    self.image_capture_count -= 1
                    self.ui.imageStatusLabel.setText("状态: 截图失败")
                    QMessageBox.warning(self, "警告", "截图失败，请检查权限或空间！")
        except Exception as e:
            print(f"截图过程出错: {e}")
            QMessageBox.critical(self, "错误", f"截图失败: {str(e)}")
            # 重置计数器
            if self.batch_mode and self.batch_folder:
                # 批量模式下不重置计数器
                pass
            elif self.image_capture_count > 0:
                self.image_capture_count -= 1
            self.ui.imageStatusLabel.setText("状态: 截图失败")

    def on_image_captured(self, output_file):
        """图片捕获完成回调"""
        try:
            if output_file and os.path.exists(output_file):
                self.show_status_message(f"已截取图片！保存到: {output_file}", 10000)
            else:
                self.show_status_message(f"图片可能未保存成功！", 10000)
        except Exception as e:
            print(f"图片捕获回调出错: {e}")
            QMessageBox.critical(self, "错误", f"处理图片捕获事件时出错: {str(e)}")

    def start_batch_capture(self):
        """开始批量截图"""
        try:
            if not self.image_selected_region:
                QMessageBox.warning(self, "警告", "请先选择截图区域！")
                return

            # 获取输出路径
            base_path = self.get_image_output_path()
            
            # 验证输出路径
            if not os.access(os.path.dirname(base_path), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 创建时间戳文件夹
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = self.ui.imageFileNameLineEdit.text()
            self.batch_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
            os.makedirs(self.batch_folder, exist_ok=True)

            # 重置计数器
            self.image_capture_count = 0
            self.batch_mode = True

            # 更新 UI 状态
            self.ui.manualStartBtn.setEnabled(False)
            self.ui.manualStopBtn.setEnabled(True)
            self.ui.imageStatusLabel.setText("状态: 批量模式已开始，请截取图片")

            print(f"[DEBUG] 批量截图已开始:")
            print(f"  输出文件夹: {self.batch_folder}")
        except Exception as e:
            print(f"开始批量截图失败: {e}")
            QMessageBox.critical(self, "错误", f"开始批量截图失败: {str(e)}")

    def stop_batch_capture(self):
        """停止批量截图"""
        try:
            if not self.batch_mode:
                return

            # 保存截图数量
            capture_count = self.image_capture_count

            # 重置状态
            self.batch_mode = False
            batch_folder = self.batch_folder
            self.batch_folder = None

            # 更新 UI 状态
            self.ui.manualStartBtn.setEnabled(True)
            self.ui.manualStopBtn.setEnabled(False)

            # 显示结果
            if capture_count > 0:
                self.ui.imageStatusLabel.setText(f"状态: 批量截图已完成，共截取 {capture_count} 张图片")
                self.show_status_message(f"批量截图已完成！共截取 {capture_count} 张图片。保存到: {batch_folder}", 10000)
                print(f"[DEBUG] 批量截图已完成:")
                print(f"  输出文件夹: {batch_folder}")
                print(f"  截图数量: {capture_count}")
            else:
                self.ui.imageStatusLabel.setText("状态: 批量截图已取消")
                self.show_status_message("批量截图已取消，未截取任何图片", 10000)
                # 删除空文件夹
                if os.path.exists(batch_folder):
                    try:
                        os.rmdir(batch_folder)
                        print(f"已删除空文件夹: {batch_folder}")
                    except:
                        pass
        except Exception as e:
            print(f"停止批量截图失败: {e}")
            QMessageBox.critical(self, "错误", f"停止批量截图失败: {str(e)}")
            # 确保状态被重置
            self.batch_mode = False
            self.batch_folder = None
            self.ui.manualStartBtn.setEnabled(True)
            self.ui.manualStopBtn.setEnabled(False)

    def start_image_recording(self):
        """开始自动截图录制"""
        try:
            if not self.image_selected_region:
                QMessageBox.warning(self, "警告", "请先选择截图区域！")
                return

            # 获取输出路径
            base_path = self.get_image_output_path()
            
            # 验证输出路径
            if not os.access(os.path.dirname(base_path), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 创建时间戳文件夹
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = self.ui.imageFileNameLineEdit.text()
            self.image_output_folder = os.path.join(base_path, f"{folder_name}_{timestamp}")
            os.makedirs(self.image_output_folder, exist_ok=True)

            # 重置计数器
            self.image_capture_count = 0

            # 获取图片格式
            image_format = self.ui.imageFormatComboBox.currentText()
            
            # 创建 ImageCapture 实例
            self.image_capture = ImageCapture(self.image_selected_region, self.image_output_folder, image_format)
            self.image_capture.captured.connect(self.on_image_captured)

            # 获取时间间隔（秒）
            interval_seconds = max(0.1, self.ui.frameIntervalSpinBox.value())  # 确保时间间隔至少为0.1秒
            interval = interval_seconds * 1000  # 转换为毫秒

            # 更新 UI 状态
            self.is_image_recording = True
            self.ui.autoStartBtn.setEnabled(False)
            self.ui.autoStopBtn.setEnabled(True)
            self.ui.imageStatusLabel.setText("状态: 自动录制中...")

            # 启动定时器
            self.image_timer = QTimer()
            self.image_timer.timeout.connect(self.auto_capture_image)
            self.image_timer.start(int(interval))

            print(f"[DEBUG] 开始自动截图录制:")
            print(f"  区域: {self.image_selected_region}")
            print(f"  文件夹: {self.image_output_folder}")
            print(f"  格式: {image_format}")
            print(f"  时间间隔: {interval_seconds} 秒")

            self.show_status_message(f"开始自动截图录制！保存到: {self.image_output_folder}", 10000)
        except Exception as e:
            print(f"开始自动截图录制出错: {e}")
            QMessageBox.critical(self, "错误", f"开始自动截图录制失败: {str(e)}")
            # 恢复 UI 状态
            self.ui.autoStartBtn.setEnabled(True)
            self.ui.autoStopBtn.setEnabled(False)
            self.ui.imageStatusLabel.setText("状态: 就绪")

    def auto_capture_image(self):
        """自动截取图片"""
        try:
            if not self.is_image_recording:
                return

            # 捕获图片
            self.image_capture_count += 1
            output_file = self.image_capture.capture(self.image_capture_count)

            if output_file:
                # 更新状态
                self.ui.imageStatusLabel.setText(f"状态: 已截取 {self.image_capture_count} 张图片")

                print(f"[DEBUG] 自动截取图片 {self.image_capture_count}:")
                print(f"  文件: {output_file}")
            else:
                # 截图失败，重置计数器
                self.image_capture_count -= 1
                self.ui.imageStatusLabel.setText(f"状态: 已截取 {self.image_capture_count} 张图片 (部分失败)")
                print(f"[DEBUG] 自动截取图片 {self.image_capture_count + 1} 失败")
        except Exception as e:
            print(f"自动截图出错: {e}")
            # 重置计数器
            if self.image_capture_count > 0:
                self.image_capture_count -= 1
            self.ui.imageStatusLabel.setText(f"状态: 已截取 {self.image_capture_count} 张图片 (错误)")

    def stop_image_recording(self):
        """停止自动截图录制"""
        try:
            if not self.is_image_recording:
                return

            # 停止定时器
            self.image_timer.stop()

            # 更新 UI 状态
            self.is_image_recording = False
            self.ui.autoStartBtn.setEnabled(True)
            self.ui.autoStopBtn.setEnabled(False)
            self.ui.imageStatusLabel.setText(f"状态: 已停止，共截取 {self.image_capture_count} 张图片")

            self.show_status_message(f"自动截图录制已停止！共截取 {self.image_capture_count} 张图片", 10000)
        except Exception as e:
            print(f"停止自动截图录制出错: {e}")
            QMessageBox.critical(self, "错误", f"停止自动截图录制失败: {str(e)}")
            # 恢复 UI 状态
            self.is_image_recording = False
            if hasattr(self, 'image_timer') and self.image_timer:
                self.image_timer.stop()
            self.ui.autoStartBtn.setEnabled(True)
            self.ui.autoStopBtn.setEnabled(False)
            self.ui.imageStatusLabel.setText(f"状态: 已停止，共截取 {self.image_capture_count} 张图片")

    def pdf_capture_image(self):
        """PDF 手动截取图片"""
        try:
            if not self.pdf_selected_region:
                QMessageBox.warning(self, "警告", "请先选择 PDF 区域！")
                return

            # 验证输出路径
            output_file = self.get_pdf_output_path()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 如果处于批量模式
            if self.pdf_batch_mode and hasattr(self, 'pdf_exporter'):
                # 捕获图片
                self.pdf_capture_count += 1
                temp_file = self.pdf_exporter.capture(self.pdf_capture_count)

                if temp_file:
                    # 更新状态
                    self.ui.pdfStatusLabel.setText(f"状态: 批量模式已截取 {self.pdf_capture_count} 张图片")
                    print(f"[DEBUG] PDF 批量截取图片:")
                    print(f"  区域: {self.pdf_selected_region}")
                    print(f"  临时文件: {temp_file}")
                else:
                    # 截图失败
                    self.pdf_capture_count -= 1
                    self.ui.pdfStatusLabel.setText("状态: 截图失败")
                    QMessageBox.warning(self, "警告", "截图失败，请检查权限或空间！")
            else:
                # 单次截图模式
                # 创建时间戳文件夹（中间文件）
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                temp_folder = os.path.join(self.output_dir, f"temp_{timestamp}")
                os.makedirs(temp_folder, exist_ok=True)

                # 创建 PDFExporter 实例
                self.pdf_exporter = PDFExporter(self.pdf_selected_region, output_file, temp_folder)
                self.pdf_exporter.exported.connect(self.on_pdf_exported)

                # 重置计数器
                self.pdf_capture_count = 0

                # 捕获图片
                self.pdf_capture_count += 1
                temp_file = self.pdf_exporter.capture(self.pdf_capture_count)

                if not temp_file:
                    QMessageBox.warning(self, "警告", "截图失败，请检查权限或空间！")
                    self.ui.pdfStatusLabel.setText("状态: 截图失败")
                    return

                # 更新状态
                self.ui.pdfStatusLabel.setText("状态: 处理中...")

                print(f"[DEBUG] PDF 手动截取:")
                print(f"  区域: {self.pdf_selected_region}")
                print(f"  临时文件夹: {temp_folder}")
                print(f"  输出 PDF: {output_file}")

                # 生成 PDF
                exported = self.pdf_exporter.export()
                if not exported:
                    self.ui.pdfStatusLabel.setText("状态: PDF 生成失败")
                    QMessageBox.warning(self, "警告", "PDF 生成失败，请检查权限或空间！")
        except Exception as e:
            print(f"PDF 截取过程出错: {e}")
            QMessageBox.critical(self, "错误", f"PDF 截取失败: {str(e)}")
            self.ui.pdfStatusLabel.setText("状态: PDF 截取失败")

    def on_pdf_exported(self, output_file):
        """PDF 导出完成回调"""
        try:
            if output_file and os.path.exists(output_file):
                self.show_status_message(f"PDF 生成完成！保存到: {output_file}", 10000)
                self.ui.pdfStatusLabel.setText("状态: 已完成")
            else:
                QMessageBox.warning(self, "警告", "PDF 可能未生成成功！")
                self.ui.pdfStatusLabel.setText("状态: 生成失败")
        except Exception as e:
            print(f"PDF 导出回调出错: {e}")
            QMessageBox.critical(self, "错误", f"处理 PDF 导出事件时出错: {str(e)}")
            self.ui.pdfStatusLabel.setText("状态: 生成失败")

    def start_pdf_recording(self):
        """开始 PDF 自动录制"""
        try:
            if not self.pdf_selected_region:
                QMessageBox.warning(self, "警告", "请先选择 PDF 区域！")
                return

            # 验证输出路径
            output_file = self.get_pdf_output_path()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 创建时间戳文件夹（中间文件）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.pdf_temp_folder = os.path.join(self.output_dir, f"temp_{timestamp}")
            os.makedirs(self.pdf_temp_folder, exist_ok=True)

            # 创建 PDFExporter 实例
            self.pdf_exporter = PDFExporter(self.pdf_selected_region, output_file, self.pdf_temp_folder)
            self.pdf_exporter.exported.connect(self.on_pdf_exported)

            # 重置计数器
            self.pdf_capture_count = 0

            # 获取时间间隔（秒）
            interval_seconds = max(0.1, self.ui.pdfFrameIntervalSpinBox.value())  # 确保时间间隔至少为0.1秒
            interval = interval_seconds * 1000  # 转换为毫秒

            # 更新 UI 状态
            self.is_pdf_recording = True
            self.ui.pdfAutoStartBtn.setEnabled(False)
            self.ui.pdfAutoStopBtn.setEnabled(True)
            self.ui.pdfStatusLabel.setText("状态: 自动录制中...")

            # 启动定时器
            self.pdf_timer = QTimer()
            self.pdf_timer.timeout.connect(self.auto_pdf_capture)
            self.pdf_timer.start(int(interval))

            print(f"[DEBUG] 开始 PDF 自动录制:")
            print(f"  区域: {self.pdf_selected_region}")
            print(f"  临时文件夹: {self.pdf_temp_folder}")
            print(f"  输出 PDF: {output_file}")
            print(f"  时间间隔: {interval_seconds} 秒")

            self.show_status_message(f"开始 PDF 自动录制！保存到: {output_file}", 10000)
        except Exception as e:
            print(f"开始 PDF 自动录制出错: {e}")
            QMessageBox.critical(self, "错误", f"开始 PDF 自动录制失败: {str(e)}")
            # 恢复 UI 状态
            self.ui.pdfAutoStartBtn.setEnabled(True)
            self.ui.pdfAutoStopBtn.setEnabled(False)
            self.ui.pdfStatusLabel.setText("状态: 就绪")

    def auto_pdf_capture(self):
        """自动截取 PDF 图片"""
        try:
            if not self.is_pdf_recording:
                return

            # 捕获图片
            self.pdf_capture_count += 1
            temp_file = self.pdf_exporter.capture(self.pdf_capture_count)

            if temp_file:
                # 更新状态
                self.ui.pdfStatusLabel.setText(f"状态: 自动录制中... ({self.pdf_capture_count})")

                print(f"[DEBUG] 自动 PDF 截取 {self.pdf_capture_count}:")
                print(f"  临时文件: {temp_file}")
            else:
                # 截图失败，重置计数器
                self.pdf_capture_count -= 1
                self.ui.pdfStatusLabel.setText(f"状态: 自动录制中... ({self.pdf_capture_count}) (部分失败)")
                print(f"[DEBUG] 自动 PDF 截取 {self.pdf_capture_count + 1} 失败")
        except Exception as e:
            print(f"自动 PDF 截图出错: {e}")
            # 重置计数器
            if self.pdf_capture_count > 0:
                self.pdf_capture_count -= 1
            self.ui.pdfStatusLabel.setText(f"状态: 自动录制中... ({self.pdf_capture_count}) (错误)")

    def stop_pdf_recording(self):
        """停止 PDF 自动录制并生成 PDF"""
        try:
            if not self.is_pdf_recording:
                return

            # 停止定时器
            self.pdf_timer.stop()

            # 更新状态
            self.is_pdf_recording = False
            self.ui.pdfAutoStartBtn.setEnabled(True)
            self.ui.pdfAutoStopBtn.setEnabled(False)
            self.ui.pdfStatusLabel.setText("状态: 生成 PDF 中...")

            print(f"[DEBUG] 停止 PDF 录制并生成 PDF:")
            print(f"  共截取 {self.pdf_capture_count} 张图片")

            # 生成 PDF
            if self.pdf_exporter:
                exported = self.pdf_exporter.export()
                if not exported:
                    self.ui.pdfStatusLabel.setText("状态: PDF 生成失败")
                    QMessageBox.warning(self, "警告", "PDF 生成失败，请检查权限或空间！")
        except Exception as e:
            print(f"停止 PDF 自动录制出错: {e}")
            QMessageBox.critical(self, "错误", f"停止 PDF 自动录制失败: {str(e)}")
            # 恢复 UI 状态
            self.is_pdf_recording = False
            if hasattr(self, 'pdf_timer') and self.pdf_timer:
                self.pdf_timer.stop()
            self.ui.pdfAutoStartBtn.setEnabled(True)
            self.ui.pdfAutoStopBtn.setEnabled(False)
            self.ui.pdfStatusLabel.setText("状态: 已停止")

    def start_pdf_batch_capture(self):
        """开始 PDF 批量截图"""
        try:
            if not self.pdf_selected_region:
                QMessageBox.warning(self, "警告", "请先选择 PDF 区域！")
                return

            # 验证输出路径
            output_file = self.get_pdf_output_path()
            output_dir = os.path.dirname(output_file)
            if not os.access(os.path.dirname(output_dir), os.W_OK):
                QMessageBox.warning(self, "警告", "输出路径没有写入权限！")
                return

            # 创建时间戳文件夹（中间文件）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_folder = os.path.join(self.output_dir, f"temp_{timestamp}")
            os.makedirs(temp_folder, exist_ok=True)

            # 创建 PDFExporter 实例
            self.pdf_exporter = PDFExporter(self.pdf_selected_region, output_file, temp_folder)
            self.pdf_exporter.exported.connect(self.on_pdf_exported)

            # 重置状态
            self.pdf_capture_count = 0
            self.pdf_batch_mode = True

            # 更新 UI 状态
            self.ui.pdfManualStartBtn.setEnabled(False)
            self.ui.pdfManualStopBtn.setEnabled(True)
            self.ui.pdfStatusLabel.setText("状态: 批量模式已开始，请截取图片")

            print(f"[DEBUG] PDF 批量截图已开始:")
            print(f"  临时文件夹: {temp_folder}")
            print(f"  输出 PDF: {output_file}")
        except Exception as e:
            print(f"开始 PDF 批量截图失败: {e}")
            QMessageBox.critical(self, "错误", f"开始 PDF 批量截图失败: {str(e)}")

    def stop_pdf_batch_capture(self):
        """停止 PDF 批量截图并生成 PDF"""
        try:
            if not self.pdf_batch_mode:
                return

            # 保存截图数量
            capture_count = self.pdf_capture_count

            # 保存temp_folder引用
            temp_folder = None
            if hasattr(self, 'pdf_exporter') and self.pdf_exporter:
                temp_folder = self.pdf_exporter.temp_folder

            # 重置状态
            self.pdf_batch_mode = False

            # 更新 UI 状态
            self.ui.pdfManualStartBtn.setEnabled(True)
            self.ui.pdfManualStopBtn.setEnabled(False)

            # 显示结果
            if capture_count > 0:
                self.ui.pdfStatusLabel.setText("状态: 生成 PDF 中...")

                print(f"[DEBUG] 停止 PDF 批量截图并生成 PDF:")
                print(f"  共截取 {capture_count} 张图片")

                # 生成 PDF
                if self.pdf_exporter:
                    exported = self.pdf_exporter.export()
                    if not exported:
                        self.ui.pdfStatusLabel.setText("状态: PDF 生成失败")
                        QMessageBox.warning(self, "警告", "PDF 生成失败，请检查权限或空间！")
            else:
                self.ui.pdfStatusLabel.setText("状态: 批量截图已取消")
                self.show_status_message("PDF 批量截图已取消，未截取任何图片", 10000)

                # 清理 PDFExporter
                if hasattr(self, 'pdf_exporter') and self.pdf_exporter:
                    self.pdf_exporter.cleanup()
        except Exception as e:
            print(f"停止 PDF 批量截图失败: {e}")
            QMessageBox.critical(self, "错误", f"停止 PDF 批量截图失败: {str(e)}")
            # 确保状态被重置
            self.pdf_batch_mode = False
            self.ui.pdfManualStartBtn.setEnabled(True)
            self.ui.pdfManualStopBtn.setEnabled(False)

    def update_recording_duration(self):
        """更新录制时长显示"""
        if self.is_recording and self.recording_start_time:
            elapsed = datetime.now() - self.recording_start_time
            hours = elapsed.seconds // 3600
            minutes = (elapsed.seconds % 3600) // 60
            seconds = elapsed.seconds % 60
            duration_str = f"已录制: {hours:02d}:{minutes:02d}:{seconds:02d}"
            self.ui.durationLabel.setText(duration_str)

    def browse_output_path(self):
        default_path = self.ui.outputPathLineEdit.text()
        if not os.path.isabs(default_path):
            default_path = os.path.join(self.app_data_dir, default_path)

        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择输出路径",
            default_path
        )

        if folder_path:
            # 转换为相对路径（如果在 app_data_dir 内）
            if folder_path.startswith(self.app_data_dir):
                relative_path = os.path.relpath(folder_path, self.app_data_dir)
                if relative_path == '.':
                    relative_path = ''
                self.ui.outputPathLineEdit.setText(relative_path)
            else:
                self.ui.outputPathLineEdit.setText(folder_path)

    def browse_image_path(self):
        default_path = self.ui.imagePathLineEdit.text()
        if not os.path.isabs(default_path):
            default_path = os.path.join(self.app_data_dir, default_path)

        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择输出路径",
            default_path
        )

        if folder_path:
            # 转换为相对路径（如果在 app_data_dir 内）
            if folder_path.startswith(self.app_data_dir):
                relative_path = os.path.relpath(folder_path, self.app_data_dir)
                if relative_path == '.':
                    relative_path = ''
                self.ui.imagePathLineEdit.setText(relative_path)
            else:
                self.ui.imagePathLineEdit.setText(folder_path)

    def browse_pdf_path(self):
        default_path = self.ui.pdfPathLineEdit.text()
        if not os.path.isabs(default_path):
            default_path = os.path.join(self.app_data_dir, default_path)

        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择输出路径",
            default_path
        )

        if folder_path:
            # 转换为相对路径（如果在 app_data_dir 内）
            if folder_path.startswith(self.app_data_dir):
                relative_path = os.path.relpath(folder_path, self.app_data_dir)
                if relative_path == '.':
                    relative_path = ''
                self.ui.pdfPathLineEdit.setText(relative_path)
            else:
                self.ui.pdfPathLineEdit.setText(folder_path)

    def load_settings(self):
        """加载设置"""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

                # 恢复设置
                if 'output_format' in settings:
                    index = self.ui.formatComboBox.findText(settings['output_format'])
                    if index != -1:
                        self.ui.formatComboBox.setCurrentIndex(index)

                if 'fps' in settings:
                    self.ui.fpsSpinBox.setValue(settings['fps'])

                if 'output_path' in settings:
                    self.ui.outputPathLineEdit.setText(settings['output_path'])
                else:
                    self.ui.outputPathLineEdit.setText("Recordings")

                if 'output_file_name' in settings:
                    self.ui.outputFileNameLineEdit.setText(settings['output_file_name'])
                else:
                    self.ui.outputFileNameLineEdit.setText("录制结果")

                if 'image_format' in settings:
                    index = self.ui.imageFormatComboBox.findText(settings['image_format'])
                    if index != -1:
                        self.ui.imageFormatComboBox.setCurrentIndex(index)

                if 'image_path' in settings:
                    self.ui.imagePathLineEdit.setText(settings['image_path'])
                else:
                    self.ui.imagePathLineEdit.setText("Recordings")

                if 'image_file_name' in settings:
                    self.ui.imageFileNameLineEdit.setText(settings['image_file_name'])
                else:
                    self.ui.imageFileNameLineEdit.setText("截图")

                if 'pdf_path' in settings:
                    self.ui.pdfPathLineEdit.setText(settings['pdf_path'])
                else:
                    self.ui.pdfPathLineEdit.setText("Recordings")

                if 'pdf_file_name' in settings:
                    self.ui.pdfFileNameLineEdit.setText(settings['pdf_file_name'])
                else:
                    self.ui.pdfFileNameLineEdit.setText("输出")

                if 'frame_interval' in settings:
                    self.ui.frameIntervalSpinBox.setValue(settings['frame_interval'])

                if 'pdf_frame_interval' in settings:
                    self.ui.pdfFrameIntervalSpinBox.setValue(settings['pdf_frame_interval'])

                if 'always_on_top' in settings:
                    self.ui.actionAlwaysOnTop.setChecked(settings['always_on_top'])
                    self.toggle_always_on_top()

            except Exception as e:
                print(f"加载设置失败: {e}")
        else:
            # 默认设置
            self.ui.outputPathLineEdit.setText("Recordings")
            self.ui.outputFileNameLineEdit.setText("录制结果")
            self.ui.imagePathLineEdit.setText("Recordings")
            self.ui.imageFileNameLineEdit.setText("截图")
            self.ui.pdfPathLineEdit.setText("Recordings")
            self.ui.pdfFileNameLineEdit.setText("输出")

    def save_settings(self):
        """保存设置"""
        settings = {
            'output_format': self.ui.formatComboBox.currentText(),
            'fps': self.ui.fpsSpinBox.value(),
            'output_path': self.ui.outputPathLineEdit.text(),
            'output_file_name': self.ui.outputFileNameLineEdit.text(),
            'image_format': self.ui.imageFormatComboBox.currentText(),
            'image_path': self.ui.imagePathLineEdit.text(),
            'image_file_name': self.ui.imageFileNameLineEdit.text(),
            'pdf_path': self.ui.pdfPathLineEdit.text(),
            'pdf_file_name': self.ui.pdfFileNameLineEdit.text(),
            'frame_interval': self.ui.frameIntervalSpinBox.value(),
            'pdf_frame_interval': self.ui.pdfFrameIntervalSpinBox.value(),
            'always_on_top': self.ui.actionAlwaysOnTop.isChecked(),
            'shortcuts': self.shortcut_settings
        }

        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存设置失败: {e}")

    def closeEvent(self, event):
        """关闭窗口时保存设置"""
        self.save_settings()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = MainWindow()
    widget.show()
    sys.exit(app.exec())
