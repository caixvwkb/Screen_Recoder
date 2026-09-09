# This Python file uses the following encoding: utf-8
"""设置持久化。

负责把界面设置（输出路径、文件名、帧率、快捷键等）保存到
%AppData%/ScreenRecorder/settings.json，并在下次启动时读回。
本模块只做「读写文件 + 返回字典」，不接触任何界面控件。
"""
import tracelog
import json
import os


class SettingsManager:
    """设置文件的读写封装。

    app_data_dir 传入应用数据目录（如 %AppData%/ScreenRecorder），
    设置文件固定放在该目录下的 settings.json。
    """

    def __init__(self, app_data_dir: str):
        self.app_data_dir = app_data_dir
        self.settings_file = os.path.join(app_data_dir, "settings.json")

    def load(self) -> dict:
        """读取设置字典；文件不存在或解析失败时返回空字典。"""
        if not os.path.exists(self.settings_file):
            return {}
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            tracelog.error(f"[设置] 加载设置失败: {e}")
            return {}

    def save(self, settings: dict) -> None:
        """把设置字典写入文件（美化缩进，保留中文）。"""
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            tracelog.error(f"[设置] 保存设置失败: {e}")
