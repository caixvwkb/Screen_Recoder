# 开发记录（专职 BUG 记录）

> **文档定位**：只记录 **Bug / 问题 / 修复**（现象 → 根因 → 修复 → 验证），按时间线追加。
> 设计需求与版本更新见《01-PRD（产品需求文档）.md》；打包见《02-打包发布指南.md》。
> 历史功能迭代记录（2026-09-08 文档重组）：设计约束已提炼进 01，实现细节不再重复维护。

## Bug 修复记录（2026-04-27）

### 问题描述

1. 宽屏截图（如代码编辑器界面）在PDF中显示不完整，右侧内容被截断
2. PDF页面使用固定A4大小，无法适配不同尺寸的截图
3. 使用mss库截图存在坐标系统不一致问题
4. Qt6中 `QApplication.desktop()` API已移除
5. PDF模式临时文件有时未正确删除

### 修改过程

1. **第一阶段 - 算法优化（未完全解决）**
   - 最初尝试使用固定A4页面，根据图片宽高比选择横向/纵向
   - 发现按高度缩放后图片宽度超出页面，导致位置为负数被裁剪

2. **第二阶段 - 页面反向适配（部分解决）**
   - 让PDF页面尺寸反向适配图片尺寸
   - 添加DPI转换计算
   - 但截图仍然不完整，怀疑是截图功能问题

3. **第三阶段 - 截图功能修复（关键修复）**
   - 将mss库改为Qt原生截图功能 `screen.grabWindow(0, x, y, width, height)`
   - 修复Qt6 API兼容性问题（移除 `QApplication.desktop()`）
   - 解决坐标系统不一致问题

4. **第四阶段 - 临时文件清理（收尾）**
   - 使用 `finally` 块确保临时文件在任何情况下都被清理
   - 修复export方法的异常处理逻辑

### 最终代码（PDFExporter.capture）

```python
def capture(self, count):
    """捕获屏幕并保存临时图片"""
    if not self.region:
        return None

    x, y, width, height = self.region
    
    # 确保临时目录存在
    os.makedirs(self.temp_folder, exist_ok=True)

    # 生成临时文件名
    temp_file = os.path.join(self.temp_folder, f"{count}.png")

    # 使用Qt的截图功能，确保坐标系统一致
    from PySide6.QtGui import QGuiApplication, QPixmap
    
    # 获取屏幕
    screen = QGuiApplication.primaryScreen()
    if not screen:
        return None
    
    # 使用Qt的grabWindow方法截取指定区域
    # 在Qt6中，使用窗口ID 0表示桌面
    pixmap = screen.grabWindow(0, x, y, width, height)
    
    # 保存图片
    pixmap.save(temp_file)

    self.captured_images.append(temp_file)
    return temp_file
```

### 最终代码（PDFExporter.export）

```python
def export(self):
    """生成 PDF 文件"""
    try:
        if not self.captured_images:
            return None

        # 生成 PDF
        from reportlab.pdfgen import canvas
        from PIL import Image

        # 读取第一张图片来决定页面尺寸
        first_img = Image.open(self.captured_images[0])
        first_img_width, first_img_height = first_img.size
        first_img.close()

        # 让PDF页面尺寸反向适配图片
        dpi = 96
        page_width = (first_img_width / dpi) * 72
        page_height = (first_img_height / dpi) * 72

        # 创建canvas
        c = canvas.Canvas(self.output_pdf, pagesize=(page_width, page_height))

        for idx, img_path in enumerate(self.captured_images):
            img = Image.open(img_path)
            img_w, img_h = img.size
            
            # 转换图片尺寸为点
            img_w_points = (img_w / dpi) * 72
            img_h_points = (img_h / dpi) * 72

            # 安全缩放算法
            scale_w = page_width / img_w_points
            scale_h = page_height / img_h_points
            scale = min(scale_w, scale_h)

            scaled_w = img_w_points * scale
            scaled_h = img_h_points * scale

            # 居中位置
            pos_x = (page_width - scaled_w) / 2
            pos_y = (page_height - scaled_h) / 2

            c.drawImage(img_path, pos_x, pos_y, width=scaled_w, height=scaled_h)
            c.showPage()
            img.close()

        c.save()
        self.exported.emit(self.output_pdf)
        return self.output_pdf
    except Exception as e:
        print(f"PDF 生成过程出错: {e}")
        return None
    finally:
        # 无论成功还是失败，都清理临时文件
        self.cleanup()
```

### 同样修复了 ImageCapture 类（散图录制功能）

```python
def capture(self, count):
    """捕获屏幕并保存图片"""
    x, y, width, height = self.region

    # 使用Qt的截图功能
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    if not screen:
        return None
    
    pixmap = screen.grabWindow(0, x, y, width, height)
    output_file = os.path.join(self.output_folder, f"{count}.{self.image_format}")
    pixmap.save(output_file)

    self.captured.emit(output_file)
    return output_file
```

### 注意事项

- 使用Qt原生API确保坐标系统一致
- 临时文件会在任何情况下被清理
- 图片完整显示，无裁剪
- PDF页面尺寸动态适配截图

---

## Bug 记录：程序焦点问题 —— 失焦时快捷键（Enter 截图）无效（2026-09-03，已修复）

**问题描述：**

1. 进行截图操作（散图录制手动模式、PDF打包录制手动模式）时，只要电脑程序焦点不在 ScreenRecorder 上，快捷键就完全无效，**最主要的是 Enter 截取操作**没有反应
2. 期望使用方式：程序**后台运行、全程待命**，焦点在其他程序（如浏览器、编辑器）上时，也能随时按快捷键截图
3. 当前实际痛点：手动截取模式下，必须**先点一下 ScreenRecorder 界面**才能截图；操作完目标程序后，要**再点回 ScreenRecorder** 才能截下一张，来回切换极其繁琐

### 影响范围

- 基于 QShortcut 实现的所有快捷键在失焦时全部失效：
  - Enter（手动截取散图 / 截取 PDF）—— 影响最严重
  - Ctrl+A（选择区域）
  - Ctrl+P（开始录制）
  - Ctrl+B（停止录制）
- 散图录制手动模式、PDF 录制手动模式受影响最严重（需要高频截图）

### 根因分析

- 当前快捷键使用 Qt 的 `QShortcut` 实现
- `QShortcut` 属于**应用内快捷键**，只在 ScreenRecorder 窗口**拥有键盘焦点**时才会响应按键
- 焦点切换到其他程序后，Qt 窗口收不到任何按键事件，快捷键自然失效
- 这是 Qt 桌面应用的典型限制，不是按键冲突或信号连接问题

### 修复方向（已实施，2026-09-03）

采用**方案 B：Windows 原生全局热键**（无新增依赖）。

**实现要点：**

1. 新增模块 `global_hotkey.py`
   - `GlobalHotkeyManager(QObject)`：基于 `RegisterHotKey` + `QAbstractNativeEventFilter` 监听 `WM_HOTKEY` 消息，把原生按键转成 Qt 信号 `activated(功能名)`
   - 内置"快捷键字符串 → Windows 虚拟键码"解析表（支持 Ctrl/Alt/Shift 修饰键、字母、数字、F 键、Return 等）
   - 冲突检测：同一组合已被其它程序占用时 `RegisterHotKey` 返回 0，注册失败不崩溃
   - `MOD_NOREPEAT`：按住 Enter 不自动重复截图

2. 主窗口 `mainwindow.py` 接入
   - `__init__` 创建 `GlobalHotkeyManager` 并安装原生事件过滤器
   - 新增 `_on_global_hotkey(name)`：收到 `capture_image` → 调 `handle_enter_key()`（按当前标签页路由到散图/PDF 截图）
   - 新增 `_update_global_capture_hotkey()`：**按批量会话状态注册/注销全局 Enter**
     - `start_batch_capture` / `start_pdf_batch_capture` 开始 → 注册全局 Enter
     - `stop_batch_capture` / `stop_pdf_batch_capture` 结束 → 注销全局 Enter
   - `edit_shortcut` 修改快捷键后同步重新注册；`closeEvent` 统一注销

### 设计决策（重要）

- 全局热键**只在手动批量截取会话进行中生效**，结束后自动注销
  - 避免后台常驻时抢走所有程序的 Enter 键（如浏览器按回车确认）
  - 批量会话正是"在其他程序工作、按 Enter 连续截图"的使用场景
- **Ctrl+A / Ctrl+P / Ctrl+B 保持应用内快捷键**，不注册为全局
  - 它们是系统通用快捷键（全选 / 打印 / 加粗），全局化会破坏其它程序
  - 开始/停止/选区属于配置类操作，本来就在应用内完成

### 修复注意事项

- 全局快捷键**只注册关键操作**（Enter 截图），开始/停止录制保留应用内快捷键，减少系统热键冲突面
- 快捷键字符串解析失败或热键冲突时静默跳过，不影响程序运行
- 修复后验收：批量截取会话进行中，ScreenRecorder 最小化/后台、焦点在其他程序时按 Enter 仍能截到目标程序当前画面；会话结束后 Enter 恢复正常

### 补充修复（2026-09-03 复验发现，重要）

用户实测：**切到桌面有全局效果，切到其它应用内部仍然失效**。排查后确认第一次修复不完整，真正根因如下：

- **根因**：`RegisterHotKey` 用 `hwnd=NULL` 注册时，系统把 `WM_HOTKEY` 投递到**线程消息队列**；而 **Qt 6 的事件分发器不会把 NULL 句柄的线程消息转发给 `QAbstractNativeEventFilter`**，所以全局热键实际上**从未真正生效**。
- **"桌面有效"是假象**：桌面（Progman）不抢 Qt 窗口的键盘焦点，ScreenRecorder 仍被 Qt 视为活动窗口，响应的其实是**应用内 QShortcut**，不是全局热键。
- **实证**（对照实验）：
  - `RegisterHotKey(NULL)` 注册成功 + `PostMessage(NULL, WM_HOTKEY)` 投递成功 → native filter **收不到**（`activated` 不触发）
  - `RegisterHotKey(真实hwnd)` 注册成功 + `PostMessage(hwnd, WM_HOTKEY)` 投递成功 → native filter **正常收到并触发信号**
- **修复**：`register()` 增加 `hwnd` 参数，主窗口注册时传 `int(self.winId())`（真实窗口句柄）。`WM_HOTKEY` 改走窗口过程，Qt 才能捕获。
  - `GlobalHotkeyManager` 新增 `_name_to_hwnd` 字典，注销时用对应句柄
  - `mainwindow._update_global_capture_hotkey()` 注册时传入 `hwnd=int(self.winId())`
- **验证**：真实 GUI 环境（非 offscreen）端到端通过——批量会话开始 → 热键注册在真实句柄上 → 向主窗口投递 `WM_HOTKEY` → 过滤器捕获 → 触发截图动作。
- **教训**：`RegisterHotKey` 传 NULL 句柄是常见坑，任何"注册成功但收不到消息"的热键问题先检查是否用了 NULL 句柄；Qt6 下必须用真实窗口句柄。

### 最终解决方案（2026-09-03 实测确认）：管理员权限运行

修复真实句柄后，大部分程序（豆包、Qt Creator 等普通权限软件）内的全局热键已正常，但**"未来教育考试系统V4.0"窗口内仍然失效**。排查确认是目标软件架构导致的特殊场景：

- 该考试系统为**防作弊软件**：manifest 要求 `requireAdministrator`（实测完整性级别 High / S-1-16-12288），内置 **360 安全 SDK + 绿鹰安全 SDK**（`360Base.dll`/`360NetBase.dll`/`360Util.dll`、`LYSDK2.dll`/`LsfSdk.dll`），并用 **CEF（Chromium 内核）**渲染考试内容
- 我们的 ScreenRecorder 是普通权限（Medium / S-1-16-8192），**无法对管理员进程做任何介入**（UIPI 隔离），其安全 SDK 安装的**全局低级键盘钩子（WH_KEYBOARD_LL）优先级高于热键检测**，会吞掉按键导致热键不触发
- **解法：以管理员身份运行 ScreenRecorder**（右键 → 以管理员身份运行；或打包 exe 属性 → 兼容性 → 勾选"以管理员身份运行此程序"）。与考试系统同级权限后，全局热键在考试系统窗口内**实测生效** ✅
- **注意事项**：
  - 管理员运行会触发 UAC 弹窗；普通权限软件的"拖放文件"等交互可能受限
  - 若未来遇到"提权后仍失效"的程序（防作弊锁定键盘），需改用鼠标触发截图（鼠标点击不受键盘钩子影响）或定时自动截图


---

## 修复：主题切换开关失效（2026-09-07）
- 症状：深色模式开关/小眼睛按钮切换深浅主题"没反应"，界面深色但开关显示 Off
- 根因：SwitchSettingCard.setChecked() 只写 qconfig 配置、不更新开关 UI
  （源码 setValue 未调用 switchButton.setChecked）→ 程序化设置开关状态时
  UI 永远保持默认 Off，与真实主题（跟随系统）脱节
- 修复：所有开关状态读写改用 switchButton.setChecked()（真实更新 UI 并触发
  checkedChanged）；涉及 dark_switch/always_on_top_switch/out_folder_switch
  的初始化、_load_settings 恢复、_apply_theme 同步


---

## 修复：settings.json 被 BOM 污染导致解析失败（2026-09-07）
- 现象：PowerShell Set-Content 写 settings.json 会带 UTF-8 BOM，
  SettingsManager.load 解析失败返回空 dict -> 设置全部回默认
- 修复：统一用 Python utf-8 无 BOM 写 settings.json（io.open(encoding='utf-8')）
- 教训：任何写配置/代码文件的操作禁用 PowerShell Set-Content，一律走 Python

## 修复：OCR 页构建期 _save_settings 触发 AttributeError（2026-09-07）
- 现象：页面构建早期（settings_page 未创建）开关信号触发 _save_settings -> AttributeError
- 修复：_save_settings 加 getattr 保护，settings_page 不存在时跳过全局部分
- 教训：Qt 静默吞异常，早期信号触发类错误常表现为"没反应"

## 修复：ASR 页开始转写无响应（_check_asr_model 缺失）（2026-09-07）
- 现象：新版遗漏 _check_asr_model 方法（旧版有），开始转写 AttributeError 被 except
  吞掉 -> 界面无响应
- 修复：补齐 _check_asr_model（models_complete 文件存在性检查）
- 教训：迁移页面时逐方法核对旧版引用，漏方法常被 try/except 掩盖
---

## 修复：OCR/ASR 输出目录卡两行说明被裁剪（2026-09-07）
- 根因：SettingCard 默认固定高 70px，两行说明放不下，第一行被裁剪
  （用户看到'…源文件夹下'就断了，误以为说明未更新）
- 修复：OutFolderCard setFixedHeight(92)，两行说明完整显示
- 验证：卡片高 92、说明文本完整 ✅

## OCR/ASR 输出目录说明改三行（2026-09-07）
- 说明分 3 行：'勾选后：批量 md 汇总到 / 源文件夹下新建的子目录，目录名可自定义；/ 不勾选：散在源文件旁'
- 卡片高度 112px（70 默认放不下 3 行）

## 屏蔽 QFluentWidgets Pro 广告提示（2026-09-07）
- 现象：终端每次启动打印 'QFluentWidgets Pro is now released' 广告
- 来源：qfluentwidgets/common/config.py 模块导入时无条件 print(ALERT)（第 411 行）


---

## 折叠卡收不起来 修复（2026-09-07）
【Bug：折叠卡收不起来】
- 根因：qfluentwidgets ExpandGroupSettingCard 收起动画终点取 scrollbar.maximum()（=内容高-卡高），
  高度收敛在 2×卡高，永远收不拢（库的动画计算缺陷）
- 修复：monkey-patch ExpandGroupSettingCard.setExpand —— 收起时停止动画、滚动条归零、
  setFixedHeight(卡头高度)，直接跳变收起；展开保留原动画。代码在项目内（打包后仍生效），不改库文件
- 验证：三块收起=70px / 展开=300/280/156px ✓


## 折叠动画+间距修复（2026-09-07，用户反馈"按钮贴边/收起突兀"）
【根因深挖】ExpandGroupSettingCard._adjustViewSize 用 self.widgets（addGroupWidget 维护）
  计算内容高度；此前用 viewLayout.addWidget 直接加内容 → widgets 空 → 高度恒为卡头高
【修复】
- 内容一律改走 group.addGroupWidget(card)（自动维护 widgets + 触发高度同步），
  状态行 QHBoxLayout 包成 QWidget 再 addGroupWidget
- setExpand 补丁改为：QVariantAnimation 动画卡片高度，收起=卡头高、展开=卡头+widgets累加高
  （不依赖库滚动条动画终点缺陷），展开/收起均平滑
- FeaturePage.showEvent 补一次 _adjustViewSize（构建期卡 sizeHint 未激活偏小）
- 所有功能卡右侧 addSpacing(24) 安全间距（全屏/框选/窗口/格式/目录/文件名/控制卡）
【验证】收起 [183→70] 展开 [70→183] 平滑时间轴 ✓（离屏数值偏小为布局未激活假象，实机正常）

## 折叠卡展开不全修复（2026-09-07，用户反馈"视频参数块少一个选项卡、按钮渲染不全"）
【根因】逐卡 addGroupWidget 时末张卡 sizeHint 未激活（为 0），自动 _adjustViewSize
  按当时偏小值固定高度，之后不再刷新 → 展开高度少一卡，末卡被压缩/消失
【修复】
- FeaturePage._sync_expand_height：撑开测量法——临时 setFixedHeight(10000) 让布局给出
  非受限 viewLayout.sizeHint()，恢复后 setFixedHeight(card.height()+h)
- showEvent 时对所有展开块同步；MainWindow 首帧 80ms 后再全局同步一次
- 验证：视频参数块 286（内容 216，三卡齐全）、录制区域 309、录制控制 159 ✓

## 折叠再展开仍缺卡 修复（2026-09-07）
【根因】setExpand 补丁展开终点用 widgets 累加（卡 sizeHint），折叠态卡 sizeHint 会变小，
  再展开时终点低估 → 少一卡
【修复】展开终点改撑开测量法（_fixed_measure：临时 setFixedHeight(10000) → viewLayout.sizeHint
  → 恢复），与 _sync_expand_height 同口径，折叠态测量同样稳定
【验证】视频参数块：初始 286 → 折叠 70 → 再展开 286（内容 sizeHint 216 完整）✓

## 右侧控件被拉伸变形 修复（2026-09-07，用户反馈"按钮被文字挡住只能渲染一半"）
【根因】QHBoxLayout 默认把子控件垂直拉满到卡高；副标题文字换行撑高卡片（如输出目录卡
  两行说明 → 卡高 124px），右侧 SpinBox/按钮被拉成 95px 高，末按钮宽度被压缩文字截断
【修复】新增 _right(card, *widgets) 辅助：右侧控件统一 setFixedHeight(32) +
  addWidget(..., Qt.AlignRight | Qt.AlignVCenter)；按钮加 minimumWidth(88)；
  输入框加 minimumWidth(150/180)，防宽度压缩


---

## 帧率框渲染失效 + 录制按钮改蓝（2026-09-07）
【问题】qfluentwidgets SpinBox 在本环境整体不渲染（数字/箭头/背景全空白，仅标签可见）
【修复】
- 帧率改用标准 QSpinBox + 主题感知 QSS（_apply_spin_qss：深色白字/浅色深字、圆角边框、
  CSS 三角箭头），主题切换时自动刷新样式
- 全屏/框选/应用窗口三个按钮改 PrimaryPushButton（品牌蓝）


---

- py_compile 全部 7 个文件通过
- 离屏全量冒烟通过：5 页块结构齐全（录制区域/视频参数/录制控制…）、设置页存在、
  关键控件完整、全局复用方法可调用、OCR/ASR fake worker 状态机触发正常
- 真实窗口启动成功（ScreenRecorder 2.1，PID 可见）

## 遗留记录：深浅主题切换 bug（2026-09-07）
- 现象：设置页"深色模式"开关切换后，真实窗口背景不变（离屏正常、真实窗口不刷新，
  isDarkTheme() 初始即 False 但界面仍深色、w.style() is app.style() 为 False）
- 定位：未找到根因（疑真实平台 qconfig 主题模式与样式表未联动刷新）
- 状态：用户拍板记录为遗留 bug，暂不处理；后续改主题相关代码须真实窗口抓图对比

## BUG修复：录制无法开始（2026-09-07）
- 现象：视频录制页点"开始录制"弹"开始录制失败 name 'datetime' is not defined"；
  散图/PDF 录制同样中招（"一些情况下不能开始录制"）
- 根因：UI 层拆分后 ui/pages/*.py 独立成文件，主文件的全局 import（datetime）不再自动可见；
  video/image/pdf 三个页面录制代码均用 datetime.now() 但未补 import
- 修复：video_page.py / image_page.py / pdf_page.py 统一补 

---

- 离屏：ImageCapture 窗口抓帧成功；ScreenRecorder 窗口视频 19 帧可读、尺寸一致；
  PDFExporter 窗口模式 capture 成功（export 链路与窗口无关）
- UI：三页 hwnd 属性 / _pick_*_window / WindowPickerDialog 引用全部就位
- 限制：极少数纯 DirectX 全屏独占渲染窗口 PrintWindow 可能返回黑屏（超出
  PW_RENDERFULLCONTENT 覆盖范围），UI 会显示截图失败提示

## 修复：Qt 字体警告（2026-09-07）
- 现象：PDF 输出时控制台出现 QFont::setPointSize(-1) 警告，与启动时
  "Cannot find font directory" 同源（PySide6 6.x 不携带字体，打包版字体


---

  (expected str, bytes or os.PathLike) → 必须包一层 reportlab ImageReader
### 验证（真实平台）
- 无 OCR：2 帧 -> 2 页 PDF 生成，尺寸正确，输出目录零残留
- 带 OCR：1 帧 -> PDF + 说明.md 生成，输出目录零残留，跨线程导出安全
- OCR 内存识别实测：含中文测试图识别出「屏幕录制 测试文字」

## 修复：PDF 批量停止报 name 'PDFExportWorker' is not defined（2026-09-07）
- 现象：PDF 批量模式开始并抓页后，点「停止」弹窗报
  name 'PDFExportWorker' is not defined，PDF 未生成，输出目录残留 temp_xxx 散图
- 根因：UI 拆分时 pdf_page.py 独立成文件，但漏了
  from export_worker import PDFExportWorker（主文件有 import，拆分后不共享）
  停止批量 -> _start_pdf_export 引用未定义类 -> 异常中断 -> cleanup 未执行
  -> 旧版落盘散图残留
- 修复：pdf_page.py 补 import；全量扫描该文件外部引用无其他缺失
- 附带验证：完整模拟批量流程（开始->Enter抓2页->停止->导出）真实平台通过，
  PDF 生成、状态栏「已完成」、无新散图产生（capture 已内存化，不再建 temp_xxx）

## 修复：PDF 内存 OCR 引擎未运行（2026-09-07）
- 现象：PDF 能正常导出但内部无 OCR 文字层、说明.md 无文字；导出耗时 0.1s
  （正常应 2s+），OCR 全程空跑
- 根因（两层 PySide6 API 误用，异常均被 except 静默吞掉，表现为"没跑"）：
  1. QImage 枚举是类属性：img.Format_RGB888 实例访问 AttributeError
     -> 应 QImage.Format.Format_RGB888
  2. constBits() 返回 memoryview 而非 QByteArray：view.setsize() 不存在
     -> np.frombuffer(view) 直接可用，无需 setsize
     ocr.py _frame_to_rgb 两处异常使所有帧转 None -> 识别列表为空


---

- pyproject.toml 项目列表加入 paths.py
### 验证
- 程序根=D:\Projects\QT_Projects\screen_recoder；cache 自动创建
- 旧配置自动迁移（dark_mode=false、Ctrl+S 等全部保留）
- 首次运行 settings.json 自动创建

## 修复：深浅主题不一致（开关浅色/界面深色）（2026-09-07）
- 现象：settings 深色模式默认值跟随系统（深色系统下默认开启），
  且配置为浅色时开关显示关闭但界面实际仍是深色（"浅色主题有bug"）
- 根因：_load_settings 只 setChecked 开关状态，未调用 setTheme 应用实际主题；



## 打包版批量 OCR 只输出文件名、无识别内容（2026-09-08）
- 现象：打包版 exe（2.1.0）「OCR 识别」页批量识别文件夹（
  D:\学科研习总库\...\有问题，860 题原题截图），生成的 md 只有文件名，
  「识别文字」为空；源码（Qt 里运行）同一文件夹识别正常。
- 打包版 ocr.log：
  [OCR] 引擎加载失败，OCR 功能禁用: 'NoneType' object has no attribute 'endswith'
- 根因（已二次确认，修正）：**Nuitka 默认不设置 sys.frozen**（sys.frozen 是
  PyInstaller 的约定；Nuitka 的编译标记是全局 `__compiled__`）。ocr.py / asr.py /
  paths.py 此前用 `getattr(sys, "frozen", False)` 判断打包环境 → 打包版判定为
  "源码运行" → 走 `os.path.dirname(__file__)` 分支，而 Nuitka 编译模块的 __file__
  是伪路径 → 程序根/base 算错 → resolve_model_dir 自动探测不到 exe 同级
  models\ocr\ → 返回 None → 回退 rapidocr 包内默认模型（Nuitka 未打包包内
  models）→ RapidOCR() 内部 det_model_path=None 调 endswith 崩溃 → 引擎禁用
  → 全部识别返回空串 → md 只剩文件名（.exe 同级 models\ocr\ 实际完整存在）。
- 源码正常的原因：源码环境 sys.frozen 分支不触发，走 __file__ 分支恰为项目根，
  models\ocr 存在 → 显式传 det/rec/cls 三个 onnx 路径加载成功。
- 修复（2026-09-08）：
  1) paths.py 新增 is_compiled()：`sys.frozen or "__compiled__" in globals()` 双兼容；
  2) paths.py 新增 app_base_candidates()：exe 同级 / 项目根 / 各自父级多候选根，
     并过滤含 .exe 的 Nuitka 伪路径；
  3) ocr.py / asr.py 的 resolve_model_dir 改用多候选根探测；
  4) OCR 探测全部失败时打印每个候选路径到 ocr.log（下次失败可直接定位）。
- 验证：源码模拟 Nuitka（注入 __compiled__、sys.executable=dist exe）、模拟
  PyInstaller（sys.frozen=True）、正常源码 三种环境全部 PASS——
  打包版正确解析到 dist\models\ocr / dist\models\asr，源码环境不受影响。
- 遗留：需重新打包后实机验证（打包前建议 --clean-cache）。

### 复验与最终修复（2026-09-08 实机确认）
- 路径解析修复后重打包：trace.log 显示 [路径] 程序根: ...dist（编译环境，exe 同级）、
  [OCR] 模型目录选定: ...dist\models\ocr（路径探测已 OK），但引擎仍加载失败：
  [Errno 2] No such file or directory: ...dist\rapidocr_onnxruntime\config.yaml
- **第三层（真正收尾）根因**：RapidOCR 构造时仍会读包内 
apidocr_onnxruntime\config.yaml
  做参数解析；Nuitka 默认**不打包包内数据文件** → dist 里 rapidocr 包缺 config.yaml
  → 引擎加载失败 → 识别全空 → md 只剩文件名
- 修复：打包命令加 --include-package-data=rapidocr_onnxruntime
- 实机验证：重新打包并拷 models 后，批量 OCR 输出**正常识别文字**（用户确认）
- 教训：Nuitka 打包第三方库时，凡库内有数据文件（config.yaml/模型/词典等），
  必须显式 --include-package-data=<包名>，仅 --follow-imports 不会带数据文件


## 打包版 OCR 相关页全部不工作 + 初始路径指向源码目录（2026-09-08，已修复）
- 现象（打包版 exe 运行）：
  1. 散图录制 / PDF / 批量 OCR 三个页面的 OCR 全部不工作（引擎未加载）；
  2. 打包版**初始路径出现 QT 原始软件目录**（D:\Projects\QT_Projects\screen_recoder）——
     设置/默认输出等路径指向源码目录，而不是 exe 同级；
  3. 疑似配置文件也被打包（未正常生成 exe 同级的默认 settings.json）。
- 推断根因：`sys.frozen` 判定问题——Nuitka 不设 sys.frozen，打包版把程序根
  算到源码/伪路径（与 09-08「打包版批量 OCR 只输出文件名」同源）。
  **上一轮已修复** paths.is_compiled()（双兼容 __compiled__）+ app_base_candidates()
  多候选，但**尚未重新打包验证**，此条为现象记录，修复验证后关闭。
- 验证（2026-09-08 实机）：
  ① exe 同级生成**全新默认** settings.json ✅（迁移跳过生效，用户确认）
  ② 散图/PDF/批量 OCR 三页引擎正常加载并识别 ✅（含 rapidocr config.yaml 修复后）
  ③ 路径解析日志显示 exe 同级（编译环境）✅

## 打包版首次运行迁移 %AppData% 旧配置（2026-09-08，已修复）
- 现象：重新打包后首次运行，设置/路径仍显示源码开发期内容（ocr_folder 指向
  D:\学科研习总库\...），与源码运行一致，非全新默认配置
- 根因：_migrate_legacy_settings 无条件迁移 %AppData%/Roaming/ScreenRecorder/
  ScreenRecorder/settings.json（内含源码测试路径）；打包版应首次运行生成全新默认
  exe 同级 settings.json，迁移把开发期配置带进了分发版
- 修复：_migrate_legacy_settings 开头加 if is_compiled(): return（打包版跳过迁移，
  仅源码开发环境迁移旧配置）
- 验证：重新打包后首次运行，exe 同级生成全新默认 settings.json（深色默认、
  隐藏调试浮窗默认勾选），不再出现源码路径 ✅

## 通性 bug：会话结束后状态未复位（2026-09-08，已逐页检查并修复）
- 现象（多页同现）：
  1. 截图/录制完成后状态栏一直停留在「完成/已截取 N 张」等，不回到就绪态；
  2. 快捷键（应用内 + 全局 Enter）完成一次录制/截图操作后，再次按下无反应，
     必须点击一下界面才能继续（状态机残留导致方法内部提前返回或按钮状态错误）。
- 逐页检查结论与修复：
  - **视频页**：_on_video_finished（录制自然结束/异常退出）原只弹提示不复位，
    导致按钮全灰卡「录制中」→ 已补完整复位（is_video_recording=False、
    timer 停止、全部按钮恢复、状态回就绪/已停止）。
  - **PDF 页**：_on_pdf_failed 原只改状态文本，导出中全禁用的按钮不恢复，
    失败后无法再次开始 → 已补按钮复位 + setFocus。
  - **散图页 / OCR / ASR**：批量/连拍开始-停止路径复位完整，无需改。
  - **焦点残留**（新修复）：视频/散图/PDF 的停止与完成路径统一 setFocus()
    归还主窗口焦点——此前焦点残留在按钮上，按 Enter 会误触发按钮或无效，
    是「完成一次后快捷键失效、要点界面才恢复」的主要来源之一。
  - 状态文本「一直显示完成」：属正常结果展示，再次开始时自动覆盖，
    按钮已复位可随时开始新会话。
- 遗留待确认（失焦失效）：Ctrl+S/Ctrl+P/Ctrl+A 为应用内 QShortcut，
  切到其它程序时失效（Enter 已全局化）。若需全局化会抢占系统快捷键
  （保存/打印/全选），此前用户已拍板不全局化——保持现状。
  **实测辅助（已实现）**：设置页「通用」「操作提示音」默认开启——快捷键操作
  成功/失败会播放系统提示音，后台运行时不看界面即可确认按键是否触发、操作是否成功，
  便于定位失焦 vs 状态机问题（详见 01 音频操作提示条目）。

## PDF 临时文件夹位置与清理（2026-09-08，已修复）
- 现象：PDF 模式的缓存文件夹直接在 Recordings（输出目录）里创建（temp_时间戳），
  输出目录只应出成品（PDF + 可选说明.md）；且输出/取消后空目录残留不删除。
- 根因：PDFExporter 已重构为内存模式（帧存 QImage 列表，零散图落盘），
  temp_folder 仅是兼容占位参数；但 _pdf_temp_folder() 仍在 output_dir 下创建目录，
  cleanup() 只清空内存帧、不删目录 → 每次 PDF 操作留一个空 temp_xxx 目录。
- 修复：
  - _pdf_temp_folder() 改到缓存区（paths.cache_dir()：源码=项目根 cache，打包版=exe 同级 cache），
    输出目录不再出现临时目录；
  - PDFExporter.cleanup() 增加删除 temp_folder（export 的 finally 保证成功/失败都执行，
    取消路径 _stop_pdf_batch_capture 也调用）；
  - 新增 _cleanup_legacy_temp_dirs()：PDF 导出完成/失败时顺带清理输出目录下
    旧版残留的「temp_ 前缀 + 空目录」（只删空的，不影响用户文件与占用中目录）。
- 验证：临时目录落在缓存区、cleanup 后目录删除、历史残留只清空目录保留非空/用户目录。

## 操作提示音不响（2026-09-08，已修复）
- 现象：设置页「操作提示音」默认开启，但快捷键操作时听不到提示音。
- 根因：初版用 winsound.MessageBeep（系统"默认提示音"），依赖 Windows 声音方案；
  系统方案中该音效被设为静音时完全无声（常见于精简/静音优化方案）。
- 修复：改用 winsound.Beep 直接指定频率经声卡播放（成功 880Hz 短音、失败 220Hz 低长音），
  不依赖系统声音方案；Beep 阻塞调用放子线程，不卡 UI；异常时退回 MessageBeep。
  另在 play_ok/play_fail 加 tracelog（DEBUG）日志，开调试浮窗可确认是否触发、
  区分「按键没触发」与「触发但无声」。
- 注意：打包版需重新打包才包含音效功能；源码运行（QT 构建）立即生效。

## 视频录制只有屏幕 1/4（2026-09-08，已修复）
- 现象：框选全屏录制，产物只有屏幕左上角 1/4（DPI 缩放 200% 时）。
- 根因：ScreenRecorder 后台线程用 mss 抓屏（物理像素），而录制区域 region
  来自 Qt QScreen.geometry()（逻辑坐标）——Windows 缩放 200% 时逻辑 1920x1080
  对应物理 3840x2160，mss 按逻辑尺寸抓物理屏 → 只抓到左上 1/4。
  散图/PDF 用 Qt grabWindow（同为逻辑坐标）所以不受影响。
- 修复：ScreenRecorder._record 屏幕区域模式按 screen.devicePixelRatio() 将
  区域换算为物理像素（x/y/宽/高各乘 dpr），VideoWriter 尺寸与 mss monitor
  均用物理像素；窗口模式不受影响。
- 验证：换算逻辑正确（200% 时 1920→3840）；需用户实机确认录制全屏完整。

## 视频播放比实际快近 2 倍（2026-09-08，已修复）
- 现象：30fps 录制的视频播放时画面明显快于实际（几乎 2 倍）；用户疑问帧率到底怎么算的。
- 根因：帧率控制写成「抓帧 + 固定 sleep(1/fps)」。每帧总耗时 = 抓帧 + 编码 + sleep，
  抓帧/编码较慢时实际帧率远低于设定（30fps 实际只有 ~12fps），但视频文件仍标记 30fps，
  播放器按标记 fps 播放 → 帧数不足 → 画面快于实际。
- 修复：改为**录制时钟时间戳对齐**：第 N 帧目标时刻 = 开始时刻 + N/fps，
  超前则 sleep 到目标时刻、落后则立即抓下一帧（掉帧但时长正确）；
  落后超过 0.5s（系统卡顿）重置基准避免追帧突发。顺带 mss 抓屏改 frombuffer 复用内存，
  少一次拷贝。窗口模式同循环统一修复。
- 验证：30fps 录 3.0s → 90 帧 / 播放 3.00s；15fps 录 2.0s → 30 帧 / 2.00s；
  60fps 录 2.0s → 121 帧 / 2.02s。播放速度与实拍一致。

## 带音频录制的临时视频残留在输出目录（2026-09-08，已修复）
- 现象：Recordings 输出目录出现 _tmp_audio_*.mp4（30MB+）且不删除；
  带音频录制的中间文件应在缓存目录处理，输出目录只出成品。
- 根因：两处问题叠加——① 临时视频路径用 os.path.dirname(output_file)
  （即输出目录），未用 paths.cache_dir()；② mux 合成成功后只删了临时 wav，
  **没有删除临时视频**（mux 失败/无声分支也只 warn 不迁移，无声视频留在临时路径）。
- 修复：
  - 临时视频改放 paths.cache_dir()（程序根/cache；打包版=exe 同级 cache）；
  - mux 成功后删除缓存里的临时视频；
  - mux 失败 / wav 写入失败 / 未采集到音频时，把临时视频 rename 成最终
    output_file（回退为无声视频，用户仍能拿到产物）。
- 验证：带音频录 2s → 成品有视频轨；缓存目录与输出目录均无 _tmp_audio_ 残留。

## 录制守护复位逻辑 NameError 导致界面卡死（2026-09-08，已修复）
- 现象：窗口录制失败（hwnd 抓取不到，如窗口关闭/独占全屏）后，录制线程终止，
  守护监控触发复位时报错 NameError: name 'tracelog' is not defined
  （video_page.py 未 import tracelog），_on_video_finished 未执行，界面按钮卡灰。
- 修复：
  - video_page.py 顶部补 import tracelog；守护分支 tracelog 调用加 try 保护，
    确保任何日志异常不阻断 _on_video_finished 复位；
  - 开始录制前新增窗口预检（capture_window_by_hwnd_np probe）：取不到内容的
    窗口（独占全屏/硬件加速渲染）直接提示拒绝开始，避免"开始后立即中断"；
  - probe 失败日志补充原因说明。
- 验证：模拟录制线程死亡 → 守护日志正常输出、is_video_recording 复位 False、
  开始按钮解灰、状态回"就绪"，无异常。

### Ctrl+P 无法结束视频录制（2026-09-08 修复）
- **现象**：录制视频时焦点在其他应用（浏览器/游戏），按 Ctrl+P 停止录制无效；
  必须点回软件再点停止。散图录制的 Enter 截图是全局的，视频停止不是。
- **根因**：Ctrl+S/Ctrl+P 绑定的是**应用内 QShortcut**（QKeySequence），
  只在软件获得焦点时生效；只有散图/PDF 的 Enter 截图用了 RegisterHotKey 真全局。
- **方案（2026-09-08 用户拍板改为常驻机制）**：程序启动即注册全部全局热键
  （含用户自定义值），退出才注销；快捷键修改后自动重注册。RegisterHotKey 常驻、
  后台待命——录屏软件标准形态。Enter（capture_image）例外：万能确认键，保持
  「批量截图会话期间临时注册」，避免常驻抢走所有程序的回车。
- **实现**：MainWindow 建统一 `self.global_hotkeys`（activated → _route_action
  按当前停留页路由）；_register_global_hotkeys 启动注册 select_region/start_recording/
  stop_recording 并打日志（成功 INFO/失败 WARN）；closeEvent 注销全部；修改快捷键后
  _rebind_shortcuts 重注册。image_page 的会话 Enter 注册复用统一实例（mixin 天然
  共享 self），video_page 的临时注册逻辑已删除。
- **注意**：Ctrl+A（框选）常驻会劫持其它程序的全选、Ctrl+S 劫持保存、Ctrl+P 劫持
  打印——用户已知并拍板常驻；可在设置里自定义避开。
- **验证**：启动注册日志 ✓；模拟系统级 Ctrl+S → 视频开始录制（59fps 真帧）✓；
  Ctrl+P → 停止 ✓；自定义 Ctrl+E 重注册生效 ✓；会话 Enter 注册/注销 ✓；退出注销 ✓。---

# 2.3 ASR 主线 Bug 记录（2026-09-08 ~ 09-09）

## ASR 长音频 OOM：BFCArena 分配 73~179GB 失败（2026-09-08，已修复）
- 现象：批量转写 32~97MB 课堂录音，日志连续报
  `onnxruntime ... BFCArena::AllocateRawInternal Failed to allocate memory ...
  size 73666645248 / 146777869568 / 179542028288`（73GB~179GB），
  每个文件都返回空结果（0 字），但程序不崩。
- 根因：整段音频喂 SenseVoice，attention 矩阵 L×L 随时长平方爆炸，
  模型 context 撑爆 onnxruntime 内存池。
- 修复（2.3.1）：分段识别——单段 ≤30s、段间重叠 1s，逐段识别后按段序拼接。

## ASR 批量转写全部完成才输出：中途异常丢全部结果（2026-09-08，已修复）
- 现象：ASRWorker 先跑完所有文件的识别，再统一循环 write_asr_txt；
  中途一个文件异常走 except → finished(0, len)，已识别的全部文本丢失、
  进度被清空，浮窗提示一次性爆发。
- 修复（2.3.8）：改为按文件为单位即时输出——每个文件最后一段完成
  立即聚合、写 txt、发进度、弹提示；失败只影响失败文件，已完成保留。

## ASR 段并行分配不均：先解码完的文件独占线程池（2026-09-08，已修复）
- 现象：段任务按解码完成顺序提交，第一个解码完的文件全部段先占满
  线程池，观感是"一个文件处理完才下一个"，文件多时后面文件干等。
- 修复（2.3.8）：两阶段——全部文件先并行解码就绪，再按文件轮换交错
  提交段任务（f1s1, f2s1, f1s2, f2s2…），多文件均匀推进。

## 状态栏"文件 x/y"提示不累加且误导（2026-09-08，已修复）
- 现象：双进度副信息"（文件 x/y 完成）"的 x 在段级并行下未按全局正确
  自增；且文件为单位显示对"段为单位并行"的进度语义有误导。
- 修复（2.3.5）：删除"文件 x/y"文字提示，只保留全局段进度 + 当前文件名；
  进度条改绑全局段进度（2.3.6 方案，后续落实）。

## SenseVoice int8 不输出句读标点、无法自然断句（2026-09-08，已修复）
- 现象：转写文本无任何标点（模型不输出 segment_timestamps/punct），
  只能按 60 字硬切，输出"60 秒一段"观感很差。
- 修复（2.3.7）：不换 ASR 模型（保精度），加 sherpa-onnx 官方
  CT-Transformer 标点模型做后处理（只插标点不改字，72MB int8）；
  实测 90s 课堂音频 → 11 行自然断句（含问号识别）。

## 打包版 ASR 模型找不到 / OCR 引擎禁用（2026-09-08，已修复）
- 现象：打包版 OCR 批量识别只有文件名、无内容（rapidocr 包内
  config.yaml 未打包）；ASR 模型路径探测失败（Nuitka 不设 sys.frozen，
  程序根算到伪路径）。
- 修复：打包命令加 --include-package-data=rapidocr_onnxruntime；
  paths.is_compiled() 双兼容判定（sys.frozen or __compiled__），
  程序根统一为 exe 同级。

## OCR 模型文件名写死、无外置配置（2026-09-09，已修复）
- 现象：models/ocr 三个 onnx 文件名在 ocr.py 硬编码（MODEL_FILES），
  加载日志也写死；换模型需改代码，与 ASR 的 config.json 机制不一致。
- 修复（2.3.10）：ocr.py 增加 _load_ocr_config / _cfg_model_files /
  _cfg_name，models/ocr/config.json 配置 name / det_model / rec_model /
  cls_model；models_complete 与加载日志全部走配置，缺失回退默认。
## export_worker 三 Worker 启动即崩：_stop_event 未初始化（2026-09-09，已修复）
- 现象：开始文件夹 OCR 报 `'FolderOcrWorker' object has no attribute '_stop_event'`，
  批量 OCR / 散图说明 / PDF 导出全部功能失效。
- 根因：PDFExportWorker / SidecarWorker / FolderOcrWorker 的 start() 调用
  `self._stop_event.clear()`、stop() 调用 `.set()`，但三个 __init__ 都未创建
  该字段（此前补停止按钮时只加了方法、漏了字段初始化，一直未被 start() 触发）；
  ASRWorker 有字段（未完成重传补丁补过），故只有 ASR 正常。
- 修复：三个类 __init__ 补 `self._stop_event = threading.Event()`。
- 备注：这三个类的 stop() 目前只置位事件，_run 尚未接入取消逻辑
  （点击停止不会立即中断、但也不崩）；真正取消需给 ocr_images_parallel /
  ocr_files_parallel / PDFExporter.export 加 cancel 参数，待后续按需实现。
- 验证：FolderOcrWorker 实例化 + start() + stop() 不再抛异常。
## OCR 合并模式取消后重新开始全部重识别（2026-09-09，设计限制 + UI 标注）
- 现象：OCR 页默认勾选「合并图片为一个 md」，取消后重新开始仍重新处理全部
  文件——即使部分图片已识别完成。
- 根因：**设计限制**。合并模式无单文件中间产物（图片收齐才写合并 md），
  is_ocred 按单文件 md 判断全部未完成 → 无法跳过。非合并模式正常跳过。
- 处理：不做复杂中间产物机制（避免合并文件不完整/残留单 md），改为
  **UI 三处标注**：合并选项卡说明、点取消时状态栏、完成提示，均按模式
  区分明示「合并模式重新开始将全部重新识别」。
