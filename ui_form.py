# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'form.ui'
##
## Created by: Qt User Interface Compiler version 6.11.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenu, QMenuBar, QPushButton, QSizePolicy,
    QSpacerItem, QSpinBox, QStatusBar, QTabWidget,
    QVBoxLayout, QWidget)
class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(480, 600)
        self.actionExit = QAction(MainWindow)
        self.actionExit.setObjectName(u"actionExit")
        self.actionAlwaysOnTop = QAction(MainWindow)
        self.actionAlwaysOnTop.setObjectName(u"actionAlwaysOnTop")
        self.actionAlwaysOnTop.setCheckable(True)
        self.actionSelectRegion = QAction(MainWindow)
        self.actionSelectRegion.setObjectName(u"actionSelectRegion")
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.modeTabWidget = QTabWidget(self.centralwidget)
        self.modeTabWidget.setObjectName(u"modeTabWidget")
        self.modeTabWidget.setTabsClosable(False)
        self.videoTab = QWidget()
        self.videoTab.setObjectName(u"videoTab")
        self.verticalLayout_5 = QVBoxLayout(self.videoTab)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.regionGroupBox = QGroupBox(self.videoTab)
        self.regionGroupBox.setObjectName(u"regionGroupBox")
        self.verticalLayout_2 = QVBoxLayout(self.regionGroupBox)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.selectRegionBtn = QPushButton(self.regionGroupBox)
        self.selectRegionBtn.setObjectName(u"selectRegionBtn")

        self.verticalLayout_2.addWidget(self.selectRegionBtn)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.regionLabel = QLabel(self.regionGroupBox)
        self.regionLabel.setObjectName(u"regionLabel")

        self.horizontalLayout.addWidget(self.regionLabel)


        self.verticalLayout_2.addLayout(self.horizontalLayout)


        self.verticalLayout_5.addWidget(self.regionGroupBox)

        self.outputGroupBox = QGroupBox(self.videoTab)
        self.outputGroupBox.setObjectName(u"outputGroupBox")
        self.verticalLayout_3 = QVBoxLayout(self.outputGroupBox)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.formatLabel = QLabel(self.outputGroupBox)
        self.formatLabel.setObjectName(u"formatLabel")

        self.horizontalLayout_2.addWidget(self.formatLabel)

        self.formatComboBox = QComboBox(self.outputGroupBox)
        self.formatComboBox.addItem("")
        self.formatComboBox.addItem("")
        self.formatComboBox.addItem("")
        self.formatComboBox.addItem("")
        self.formatComboBox.setObjectName(u"formatComboBox")

        self.horizontalLayout_2.addWidget(self.formatComboBox)


        self.verticalLayout_3.addLayout(self.horizontalLayout_2)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.pathLabel = QLabel(self.outputGroupBox)
        self.pathLabel.setObjectName(u"pathLabel")

        self.horizontalLayout_3.addWidget(self.pathLabel)

        self.outputPathLineEdit = QLineEdit(self.outputGroupBox)
        self.outputPathLineEdit.setObjectName(u"outputPathLineEdit")

        self.horizontalLayout_3.addWidget(self.outputPathLineEdit)

        self.browsePathBtn = QPushButton(self.outputGroupBox)
        self.browsePathBtn.setObjectName(u"browsePathBtn")

        self.horizontalLayout_3.addWidget(self.browsePathBtn)


        self.verticalLayout_3.addLayout(self.horizontalLayout_3)

        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.fileNameLabel = QLabel(self.outputGroupBox)
        self.fileNameLabel.setObjectName(u"fileNameLabel")

        self.horizontalLayout_4.addWidget(self.fileNameLabel)

        self.outputFileNameLineEdit = QLineEdit(self.outputGroupBox)
        self.outputFileNameLineEdit.setObjectName(u"outputFileNameLineEdit")

        self.horizontalLayout_4.addWidget(self.outputFileNameLineEdit)

        self.extensionLabel = QLabel(self.outputGroupBox)
        self.extensionLabel.setObjectName(u"extensionLabel")

        self.horizontalLayout_4.addWidget(self.extensionLabel)


        self.verticalLayout_3.addLayout(self.horizontalLayout_4)

        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.fpsLabel = QLabel(self.outputGroupBox)
        self.fpsLabel.setObjectName(u"fpsLabel")

        self.horizontalLayout_5.addWidget(self.fpsLabel)

        self.fpsSpinBox = QSpinBox(self.outputGroupBox)
        self.fpsSpinBox.setObjectName(u"fpsSpinBox")
        self.fpsSpinBox.setValue(30)

        self.horizontalLayout_5.addWidget(self.fpsSpinBox)


        self.verticalLayout_3.addLayout(self.horizontalLayout_5)


        self.verticalLayout_5.addWidget(self.outputGroupBox)

        self.controlGroupBox = QGroupBox(self.videoTab)
        self.controlGroupBox.setObjectName(u"controlGroupBox")
        self.verticalLayout_4 = QVBoxLayout(self.controlGroupBox)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.horizontalLayout_6 = QHBoxLayout()
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.startBtn = QPushButton(self.controlGroupBox)
        self.startBtn.setObjectName(u"startBtn")
        self.startBtn.setEnabled(True)

        self.horizontalLayout_6.addWidget(self.startBtn)

        self.stopBtn = QPushButton(self.controlGroupBox)
        self.stopBtn.setObjectName(u"stopBtn")
        self.stopBtn.setEnabled(False)

        self.horizontalLayout_6.addWidget(self.stopBtn)


        self.verticalLayout_4.addLayout(self.horizontalLayout_6)

        self.horizontalLayout_7 = QHBoxLayout()
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.statusLabel = QLabel(self.controlGroupBox)
        self.statusLabel.setObjectName(u"statusLabel")

        self.horizontalLayout_7.addWidget(self.statusLabel)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_7.addItem(self.horizontalSpacer)

        self.durationLabel = QLabel(self.controlGroupBox)
        self.durationLabel.setObjectName(u"durationLabel")

        self.horizontalLayout_7.addWidget(self.durationLabel)


        self.verticalLayout_4.addLayout(self.horizontalLayout_7)


        self.verticalLayout_5.addWidget(self.controlGroupBox)

        icon = QIcon()
        icon.addFile(u"", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.modeTabWidget.addTab(self.videoTab, icon, "")
        self.imageTab = QWidget()
        self.imageTab.setObjectName(u"imageTab")
        self.verticalLayout_6 = QVBoxLayout(self.imageTab)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.imageRegionGroupBox = QGroupBox(self.imageTab)
        self.imageRegionGroupBox.setObjectName(u"imageRegionGroupBox")
        self.verticalLayout_7 = QVBoxLayout(self.imageRegionGroupBox)
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.imageSelectRegionBtn = QPushButton(self.imageRegionGroupBox)
        self.imageSelectRegionBtn.setObjectName(u"imageSelectRegionBtn")

        self.verticalLayout_7.addWidget(self.imageSelectRegionBtn)

        self.horizontalLayout_8 = QHBoxLayout()
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.imageRegionLabel = QLabel(self.imageRegionGroupBox)
        self.imageRegionLabel.setObjectName(u"imageRegionLabel")

        self.horizontalLayout_8.addWidget(self.imageRegionLabel)


        self.verticalLayout_7.addLayout(self.horizontalLayout_8)


        self.verticalLayout_6.addWidget(self.imageRegionGroupBox)

        self.imageOutputGroupBox = QGroupBox(self.imageTab)
        self.imageOutputGroupBox.setObjectName(u"imageOutputGroupBox")
        self.verticalLayout_8 = QVBoxLayout(self.imageOutputGroupBox)
        self.verticalLayout_8.setObjectName(u"verticalLayout_8")
        self.horizontalLayout_9 = QHBoxLayout()
        self.horizontalLayout_9.setObjectName(u"horizontalLayout_9")
        self.imageFormatLabel = QLabel(self.imageOutputGroupBox)
        self.imageFormatLabel.setObjectName(u"imageFormatLabel")

        self.horizontalLayout_9.addWidget(self.imageFormatLabel)

        self.imageFormatComboBox = QComboBox(self.imageOutputGroupBox)
        self.imageFormatComboBox.addItem("")
        self.imageFormatComboBox.addItem("")
        self.imageFormatComboBox.addItem("")
        self.imageFormatComboBox.setObjectName(u"imageFormatComboBox")

        self.horizontalLayout_9.addWidget(self.imageFormatComboBox)


        self.verticalLayout_8.addLayout(self.horizontalLayout_9)

        self.horizontalLayout_10 = QHBoxLayout()
        self.horizontalLayout_10.setObjectName(u"horizontalLayout_10")
        self.imagePathLabel = QLabel(self.imageOutputGroupBox)
        self.imagePathLabel.setObjectName(u"imagePathLabel")

        self.horizontalLayout_10.addWidget(self.imagePathLabel)

        self.imagePathLineEdit = QLineEdit(self.imageOutputGroupBox)
        self.imagePathLineEdit.setObjectName(u"imagePathLineEdit")

        self.horizontalLayout_10.addWidget(self.imagePathLineEdit)

        self.imageBrowsePathBtn = QPushButton(self.imageOutputGroupBox)
        self.imageBrowsePathBtn.setObjectName(u"imageBrowsePathBtn")

        self.horizontalLayout_10.addWidget(self.imageBrowsePathBtn)


        self.verticalLayout_8.addLayout(self.horizontalLayout_10)

        self.horizontalLayout_11 = QHBoxLayout()
        self.horizontalLayout_11.setObjectName(u"horizontalLayout_11")
        self.imageFileNameLabel = QLabel(self.imageOutputGroupBox)
        self.imageFileNameLabel.setObjectName(u"imageFileNameLabel")

        self.horizontalLayout_11.addWidget(self.imageFileNameLabel)

        self.imageFileNameLineEdit = QLineEdit(self.imageOutputGroupBox)
        self.imageFileNameLineEdit.setObjectName(u"imageFileNameLineEdit")

        self.horizontalLayout_11.addWidget(self.imageFileNameLineEdit)


        self.verticalLayout_8.addLayout(self.horizontalLayout_11)


        self.verticalLayout_6.addWidget(self.imageOutputGroupBox)

        self.imageControlGroupBox = QGroupBox(self.imageTab)
        self.imageControlGroupBox.setObjectName(u"imageControlGroupBox")
        self.verticalLayout_9 = QVBoxLayout(self.imageControlGroupBox)
        self.verticalLayout_9.setObjectName(u"verticalLayout_9")
        self.manualGroupBox = QGroupBox(self.imageControlGroupBox)
        self.manualGroupBox.setObjectName(u"manualGroupBox")
        self.verticalLayout_14 = QVBoxLayout(self.manualGroupBox)
        self.verticalLayout_14.setObjectName(u"verticalLayout_14")
        self.horizontalLayout_manualButtons = QHBoxLayout()
        self.horizontalLayout_manualButtons.setObjectName(u"horizontalLayout_manualButtons")
        self.manualStartBtn = QPushButton(self.manualGroupBox)
        self.manualStartBtn.setObjectName(u"manualStartBtn")

        self.horizontalLayout_manualButtons.addWidget(self.manualStartBtn)

        self.manualStopBtn = QPushButton(self.manualGroupBox)
        self.manualStopBtn.setObjectName(u"manualStopBtn")
        self.manualStopBtn.setEnabled(False)

        self.horizontalLayout_manualButtons.addWidget(self.manualStopBtn)


        self.verticalLayout_14.addLayout(self.horizontalLayout_manualButtons)

        self.captureBtn = QPushButton(self.manualGroupBox)
        self.captureBtn.setObjectName(u"captureBtn")

        self.verticalLayout_14.addWidget(self.captureBtn)


        self.verticalLayout_9.addWidget(self.manualGroupBox)

        self.autoGroupBox = QGroupBox(self.imageControlGroupBox)
        self.autoGroupBox.setObjectName(u"autoGroupBox")
        self.verticalLayout_15 = QVBoxLayout(self.autoGroupBox)
        self.verticalLayout_15.setObjectName(u"verticalLayout_15")
        self.horizontalLayout_12 = QHBoxLayout()
        self.horizontalLayout_12.setObjectName(u"horizontalLayout_12")
        self.autoStartBtn = QPushButton(self.autoGroupBox)
        self.autoStartBtn.setObjectName(u"autoStartBtn")

        self.horizontalLayout_12.addWidget(self.autoStartBtn)

        self.autoStopBtn = QPushButton(self.autoGroupBox)
        self.autoStopBtn.setObjectName(u"autoStopBtn")
        self.autoStopBtn.setEnabled(False)

        self.horizontalLayout_12.addWidget(self.autoStopBtn)


        self.verticalLayout_15.addLayout(self.horizontalLayout_12)

        self.horizontalLayout_13 = QHBoxLayout()
        self.horizontalLayout_13.setObjectName(u"horizontalLayout_13")
        self.frameIntervalLabel = QLabel(self.autoGroupBox)
        self.frameIntervalLabel.setObjectName(u"frameIntervalLabel")

        self.horizontalLayout_13.addWidget(self.frameIntervalLabel)

        self.frameIntervalSpinBox = QDoubleSpinBox(self.autoGroupBox)
        self.frameIntervalSpinBox.setObjectName(u"frameIntervalSpinBox")
        self.frameIntervalSpinBox.setValue(1)
        self.frameIntervalSpinBox.setMinimum(0)
        self.frameIntervalSpinBox.setMaximum(100)
        self.frameIntervalSpinBox.setSingleStep(5)

        self.horizontalLayout_13.addWidget(self.frameIntervalSpinBox)


        self.verticalLayout_15.addLayout(self.horizontalLayout_13)


        self.verticalLayout_9.addWidget(self.autoGroupBox)

        self.imageStatusLabel = QLabel(self.imageControlGroupBox)
        self.imageStatusLabel.setObjectName(u"imageStatusLabel")

        self.verticalLayout_9.addWidget(self.imageStatusLabel)


        self.verticalLayout_6.addWidget(self.imageControlGroupBox)

        self.modeTabWidget.addTab(self.imageTab, "")
        self.pdfTab = QWidget()
        self.pdfTab.setObjectName(u"pdfTab")
        self.verticalLayout_10 = QVBoxLayout(self.pdfTab)
        self.verticalLayout_10.setObjectName(u"verticalLayout_10")
        self.pdfRegionGroupBox = QGroupBox(self.pdfTab)
        self.pdfRegionGroupBox.setObjectName(u"pdfRegionGroupBox")
        self.verticalLayout_11 = QVBoxLayout(self.pdfRegionGroupBox)
        self.verticalLayout_11.setObjectName(u"verticalLayout_11")
        self.pdfSelectRegionBtn = QPushButton(self.pdfRegionGroupBox)
        self.pdfSelectRegionBtn.setObjectName(u"pdfSelectRegionBtn")

        self.verticalLayout_11.addWidget(self.pdfSelectRegionBtn)

        self.horizontalLayout_14 = QHBoxLayout()
        self.horizontalLayout_14.setObjectName(u"horizontalLayout_14")
        self.pdfRegionLabel = QLabel(self.pdfRegionGroupBox)
        self.pdfRegionLabel.setObjectName(u"pdfRegionLabel")

        self.horizontalLayout_14.addWidget(self.pdfRegionLabel)


        self.verticalLayout_11.addLayout(self.horizontalLayout_14)


        self.verticalLayout_10.addWidget(self.pdfRegionGroupBox)

        self.pdfOutputGroupBox = QGroupBox(self.pdfTab)
        self.pdfOutputGroupBox.setObjectName(u"pdfOutputGroupBox")
        self.verticalLayout_12 = QVBoxLayout(self.pdfOutputGroupBox)
        self.verticalLayout_12.setObjectName(u"verticalLayout_12")
        self.horizontalLayout_15 = QHBoxLayout()
        self.horizontalLayout_15.setObjectName(u"horizontalLayout_15")
        self.pdfPathLabel = QLabel(self.pdfOutputGroupBox)
        self.pdfPathLabel.setObjectName(u"pdfPathLabel")

        self.horizontalLayout_15.addWidget(self.pdfPathLabel)

        self.pdfPathLineEdit = QLineEdit(self.pdfOutputGroupBox)
        self.pdfPathLineEdit.setObjectName(u"pdfPathLineEdit")

        self.horizontalLayout_15.addWidget(self.pdfPathLineEdit)

        self.pdfBrowsePathBtn = QPushButton(self.pdfOutputGroupBox)
        self.pdfBrowsePathBtn.setObjectName(u"pdfBrowsePathBtn")

        self.horizontalLayout_15.addWidget(self.pdfBrowsePathBtn)


        self.verticalLayout_12.addLayout(self.horizontalLayout_15)

        self.horizontalLayout_16 = QHBoxLayout()
        self.horizontalLayout_16.setObjectName(u"horizontalLayout_16")
        self.pdfFileNameLabel = QLabel(self.pdfOutputGroupBox)
        self.pdfFileNameLabel.setObjectName(u"pdfFileNameLabel")

        self.horizontalLayout_16.addWidget(self.pdfFileNameLabel)

        self.pdfFileNameLineEdit = QLineEdit(self.pdfOutputGroupBox)
        self.pdfFileNameLineEdit.setObjectName(u"pdfFileNameLineEdit")

        self.horizontalLayout_16.addWidget(self.pdfFileNameLineEdit)

        self.pdfExtensionLabel = QLabel(self.pdfOutputGroupBox)
        self.pdfExtensionLabel.setObjectName(u"pdfExtensionLabel")

        self.horizontalLayout_16.addWidget(self.pdfExtensionLabel)


        self.verticalLayout_12.addLayout(self.horizontalLayout_16)


        self.verticalLayout_10.addWidget(self.pdfOutputGroupBox)

        self.pdfControlGroupBox = QGroupBox(self.pdfTab)
        self.pdfControlGroupBox.setObjectName(u"pdfControlGroupBox")
        self.verticalLayout_13 = QVBoxLayout(self.pdfControlGroupBox)
        self.verticalLayout_13.setObjectName(u"verticalLayout_13")
        self.pdfManualGroupBox = QGroupBox(self.pdfControlGroupBox)
        self.pdfManualGroupBox.setObjectName(u"pdfManualGroupBox")
        self.verticalLayout_16 = QVBoxLayout(self.pdfManualGroupBox)
        self.verticalLayout_16.setObjectName(u"verticalLayout_16")
        self.horizontalLayout_pdfManualButtons = QHBoxLayout()
        self.horizontalLayout_pdfManualButtons.setObjectName(u"horizontalLayout_pdfManualButtons")
        self.pdfManualStartBtn = QPushButton(self.pdfManualGroupBox)
        self.pdfManualStartBtn.setObjectName(u"pdfManualStartBtn")

        self.horizontalLayout_pdfManualButtons.addWidget(self.pdfManualStartBtn)

        self.pdfManualStopBtn = QPushButton(self.pdfManualGroupBox)
        self.pdfManualStopBtn.setObjectName(u"pdfManualStopBtn")
        self.pdfManualStopBtn.setEnabled(False)

        self.horizontalLayout_pdfManualButtons.addWidget(self.pdfManualStopBtn)


        self.verticalLayout_16.addLayout(self.horizontalLayout_pdfManualButtons)

        self.pdfCaptureBtn = QPushButton(self.pdfManualGroupBox)
        self.pdfCaptureBtn.setObjectName(u"pdfCaptureBtn")

        self.verticalLayout_16.addWidget(self.pdfCaptureBtn)


        self.verticalLayout_13.addWidget(self.pdfManualGroupBox)

        self.pdfAutoGroupBox = QGroupBox(self.pdfControlGroupBox)
        self.pdfAutoGroupBox.setObjectName(u"pdfAutoGroupBox")
        self.verticalLayout_17 = QVBoxLayout(self.pdfAutoGroupBox)
        self.verticalLayout_17.setObjectName(u"verticalLayout_17")
        self.horizontalLayout_17 = QHBoxLayout()
        self.horizontalLayout_17.setObjectName(u"horizontalLayout_17")
        self.pdfAutoStartBtn = QPushButton(self.pdfAutoGroupBox)
        self.pdfAutoStartBtn.setObjectName(u"pdfAutoStartBtn")

        self.horizontalLayout_17.addWidget(self.pdfAutoStartBtn)

        self.pdfAutoStopBtn = QPushButton(self.pdfAutoGroupBox)
        self.pdfAutoStopBtn.setObjectName(u"pdfAutoStopBtn")
        self.pdfAutoStopBtn.setEnabled(False)

        self.horizontalLayout_17.addWidget(self.pdfAutoStopBtn)


        self.verticalLayout_17.addLayout(self.horizontalLayout_17)

        self.horizontalLayout_18 = QHBoxLayout()
        self.horizontalLayout_18.setObjectName(u"horizontalLayout_18")
        self.pdfFrameIntervalLabel = QLabel(self.pdfAutoGroupBox)
        self.pdfFrameIntervalLabel.setObjectName(u"pdfFrameIntervalLabel")

        self.horizontalLayout_18.addWidget(self.pdfFrameIntervalLabel)

        self.pdfFrameIntervalSpinBox = QDoubleSpinBox(self.pdfAutoGroupBox)
        self.pdfFrameIntervalSpinBox.setObjectName(u"pdfFrameIntervalSpinBox")
        self.pdfFrameIntervalSpinBox.setValue(1)
        self.pdfFrameIntervalSpinBox.setMinimum(0)
        self.pdfFrameIntervalSpinBox.setMaximum(100)
        self.pdfFrameIntervalSpinBox.setSingleStep(5)

        self.horizontalLayout_18.addWidget(self.pdfFrameIntervalSpinBox)


        self.verticalLayout_17.addLayout(self.horizontalLayout_18)


        self.verticalLayout_13.addWidget(self.pdfAutoGroupBox)

        self.pdfStatusLabel = QLabel(self.pdfControlGroupBox)
        self.pdfStatusLabel.setObjectName(u"pdfStatusLabel")

        self.verticalLayout_13.addWidget(self.pdfStatusLabel)


        self.verticalLayout_10.addWidget(self.pdfControlGroupBox)

        self.modeTabWidget.addTab(self.pdfTab, "")

        self.verticalLayout.addWidget(self.modeTabWidget)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 480, 22))
        self.menu_File = QMenu(self.menubar)
        self.menu_File.setObjectName(u"menu_File")
        self.menu_Options = QMenu(self.menubar)
        self.menu_Options.setObjectName(u"menu_Options")
        self.menu_Shortcuts = QMenu(self.menubar)
        self.menu_Shortcuts.setObjectName(u"menu_Shortcuts")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.menubar.addAction(self.menu_File.menuAction())
        self.menubar.addAction(self.menu_Options.menuAction())
        self.menubar.addAction(self.menu_Shortcuts.menuAction())
        self.menu_File.addAction(self.actionExit)
        self.menu_Options.addAction(self.actionAlwaysOnTop)
        self.menu_Shortcuts.addAction(self.actionSelectRegion)

        self.retranslateUi(MainWindow)

        self.modeTabWidget.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"\u5c4f\u5e55\u5f55\u5236\u5668", None))
        self.actionExit.setText(QCoreApplication.translate("MainWindow", u"\u9000\u51fa", None))
        self.actionAlwaysOnTop.setText(QCoreApplication.translate("MainWindow", u"\u4fdd\u6301\u7f6e\u9876", None))
        self.actionSelectRegion.setText(QCoreApplication.translate("MainWindow", u"\u9009\u62e9\u5f55\u5236\u533a\u57df", None))
#if QT_CONFIG(shortcut)
        self.actionSelectRegion.setShortcut(QCoreApplication.translate("MainWindow", u"Ctrl+A", None))
#endif // QT_CONFIG(shortcut)
        self.regionGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u5f55\u5236\u533a\u57df", None))
        self.selectRegionBtn.setText(QCoreApplication.translate("MainWindow", u"\u9009\u62e9\u5f55\u5236\u533a\u57df (Ctrl+A)", None))
        self.regionLabel.setText(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u533a\u57df: \u672a\u9009\u62e9", None))
        self.outputGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u8bbe\u7f6e", None))
        self.formatLabel.setText(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u683c\u5f0f:", None))
        self.formatComboBox.setItemText(0, QCoreApplication.translate("MainWindow", u"mp4", None))
        self.formatComboBox.setItemText(1, QCoreApplication.translate("MainWindow", u"avi", None))
        self.formatComboBox.setItemText(2, QCoreApplication.translate("MainWindow", u"mkv", None))
        self.formatComboBox.setItemText(3, QCoreApplication.translate("MainWindow", u"mov", None))

        self.pathLabel.setText(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u8def\u5f84:", None))
        self.outputPathLineEdit.setText(QCoreApplication.translate("MainWindow", u"Recordings", None))
        self.browsePathBtn.setText(QCoreApplication.translate("MainWindow", u"\u6d4f\u89c8", None))
        self.fileNameLabel.setText(QCoreApplication.translate("MainWindow", u"\u6587\u4ef6\u540d:", None))
        self.outputFileNameLineEdit.setText(QCoreApplication.translate("MainWindow", u"\u5f55\u5236\u7ed3\u679c", None))
        self.extensionLabel.setText(QCoreApplication.translate("MainWindow", u".mp4", None))
        self.fpsLabel.setText(QCoreApplication.translate("MainWindow", u"\u5e27\u7387 (FPS):", None))
        self.controlGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u5f55\u5236\u63a7\u5236", None))
        self.startBtn.setText(QCoreApplication.translate("MainWindow", u"\u5f00\u59cb\u5f55\u5236 (Ctrl+P)", None))
        self.stopBtn.setText(QCoreApplication.translate("MainWindow", u"\u505c\u6b62\u5f55\u5236 (Ctrl+B)", None))
        self.statusLabel.setText(QCoreApplication.translate("MainWindow", u"\u72b6\u6001: \u5c31\u7eea", None))
        self.durationLabel.setText(QCoreApplication.translate("MainWindow", u"\u5df2\u5f55\u5236: 00:00:00", None))
        self.modeTabWidget.setTabText(self.modeTabWidget.indexOf(self.videoTab), QCoreApplication.translate("MainWindow", u"\u89c6\u9891\u5f55\u5236", None))
        self.imageRegionGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u622a\u56fe\u533a\u57df", None))
        self.imageSelectRegionBtn.setText(QCoreApplication.translate("MainWindow", u"\u9009\u62e9\u622a\u56fe\u533a\u57df (Ctrl+A)", None))
        self.imageRegionLabel.setText(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u533a\u57df: \u672a\u9009\u62e9", None))
        self.imageOutputGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u8bbe\u7f6e", None))
        self.imageFormatLabel.setText(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u683c\u5f0f:", None))
        self.imageFormatComboBox.setItemText(0, QCoreApplication.translate("MainWindow", u"png", None))
        self.imageFormatComboBox.setItemText(1, QCoreApplication.translate("MainWindow", u"jpg", None))
        self.imageFormatComboBox.setItemText(2, QCoreApplication.translate("MainWindow", u"bmp", None))

        self.imagePathLabel.setText(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u8def\u5f84:", None))
        self.imagePathLineEdit.setText(QCoreApplication.translate("MainWindow", u"Recordings", None))
        self.imageBrowsePathBtn.setText(QCoreApplication.translate("MainWindow", u"\u6d4f\u89c8", None))
        self.imageFileNameLabel.setText(QCoreApplication.translate("MainWindow", u"\u6587\u4ef6\u5939\u540d:", None))
        self.imageFileNameLineEdit.setText(QCoreApplication.translate("MainWindow", u"\u622a\u56fe", None))
        self.imageControlGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u622a\u56fe\u63a7\u5236", None))
        self.manualGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u624b\u52a8\u6a21\u5f0f", None))
        self.manualStartBtn.setText(QCoreApplication.translate("MainWindow", u"\u5f00\u59cb", None))
        self.manualStopBtn.setText(QCoreApplication.translate("MainWindow", u"\u7ed3\u675f", None))
        self.captureBtn.setText(QCoreApplication.translate("MainWindow", u"\u622a\u53d6\u56fe\u7247 (Enter)", None))
        self.autoGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u81ea\u52a8\u6a21\u5f0f", None))
        self.autoStartBtn.setText(QCoreApplication.translate("MainWindow", u"\u5f00\u59cb\u5f55\u5236 (Ctrl+P)", None))
        self.autoStopBtn.setText(QCoreApplication.translate("MainWindow", u"\u505c\u6b62\u5f55\u5236 (Ctrl+B)", None))
        self.frameIntervalLabel.setText(QCoreApplication.translate("MainWindow", u"\u65f6\u95f4\u95f4\u9694 (\u79d2):", None))
        self.imageStatusLabel.setText(QCoreApplication.translate("MainWindow", u"\u72b6\u6001: \u5c31\u7eea", None))
        self.modeTabWidget.setTabText(self.modeTabWidget.indexOf(self.imageTab), QCoreApplication.translate("MainWindow", u"\u6563\u56fe\u5f55\u5236", None))
        self.pdfRegionGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"PDF \u533a\u57df", None))
        self.pdfSelectRegionBtn.setText(QCoreApplication.translate("MainWindow", u"\u9009\u62e9 PDF \u533a\u57df (Ctrl+A)", None))
        self.pdfRegionLabel.setText(QCoreApplication.translate("MainWindow", u"\u5f53\u524d\u533a\u57df: \u672a\u9009\u62e9", None))
        self.pdfOutputGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u8bbe\u7f6e", None))
        self.pdfPathLabel.setText(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa\u8def\u5f84:", None))
        self.pdfPathLineEdit.setText(QCoreApplication.translate("MainWindow", u"Recordings", None))
        self.pdfBrowsePathBtn.setText(QCoreApplication.translate("MainWindow", u"\u6d4f\u89c8", None))
        self.pdfFileNameLabel.setText(QCoreApplication.translate("MainWindow", u"\u6587\u4ef6\u540d:", None))
        self.pdfFileNameLineEdit.setText(QCoreApplication.translate("MainWindow", u"\u8f93\u51fa", None))
        self.pdfExtensionLabel.setText(QCoreApplication.translate("MainWindow", u".pdf", None))
        self.pdfControlGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"PDF \u63a7\u5236\u533a\u57df", None))
        self.pdfManualGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u624b\u52a8\u6a21\u5f0f", None))
        self.pdfManualStartBtn.setText(QCoreApplication.translate("MainWindow", u"\u5f00\u59cb", None))
        self.pdfManualStopBtn.setText(QCoreApplication.translate("MainWindow", u"\u7ed3\u675f", None))
        self.pdfCaptureBtn.setText(QCoreApplication.translate("MainWindow", u"\u622a\u53d6\u6309\u94ae (Enter)", None))
        self.pdfAutoGroupBox.setTitle(QCoreApplication.translate("MainWindow", u"\u81ea\u52a8\u6a21\u5f0f", None))
        self.pdfAutoStartBtn.setText(QCoreApplication.translate("MainWindow", u"\u5f00\u59cb\u5f55\u5236 (Ctrl+P)", None))
        self.pdfAutoStopBtn.setText(QCoreApplication.translate("MainWindow", u"\u505c\u6b62\u5f55\u5236 (Ctrl+B)", None))
        self.pdfFrameIntervalLabel.setText(QCoreApplication.translate("MainWindow", u"\u65f6\u95f4\u95f4\u9694 (\u79d2):", None))
        self.pdfStatusLabel.setText(QCoreApplication.translate("MainWindow", u"\u72b6\u6001: \u5c31\u7eea", None))
        self.modeTabWidget.setTabText(self.modeTabWidget.indexOf(self.pdfTab), QCoreApplication.translate("MainWindow", u"PDF\u8f93\u51fa\u5f55\u5236", None))
        self.menu_File.setTitle(QCoreApplication.translate("MainWindow", u"\u6587\u4ef6", None))
        self.menu_Options.setTitle(QCoreApplication.translate("MainWindow", u"\u9009\u9879", None))
        self.menu_Shortcuts.setTitle(QCoreApplication.translate("MainWindow", u"\u5feb\u6377\u952e", None))
    # retranslateUi

