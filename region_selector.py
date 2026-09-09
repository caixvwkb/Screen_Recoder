# This Python file uses the following encoding: utf-8
"""区域选择遮罩窗口（SelectionWindow）。

用户点击“选择录制/截图/PDF 区域”后，主窗口隐藏并弹出本全屏遮罩：
  - 左键拖拽：绘制红色选区（任意方向均可，自动归一化）
  - 点击已选区域后拖动：平移选区（限制在屏幕内）
  - 双击：确认选区，发出 selection_completed 信号
  - Esc：取消，发出 selection_canceled 信号
"""
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget


class SelectionWindow(QWidget):
    """全屏选区遮罩：拖拽画框、点击平移、双击确认、Esc 取消。"""
    selection_completed = Signal(tuple)  # 选择完成信号
    selection_canceled = Signal()        # 选择取消信号
    
    def __init__(self):
        super().__init__()
        self.initUI()
        self.initVariables()

    def initUI(self):
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

