LIGHT_STYLE = """
QWidget {
	background: #eeeeF1;
	color: #17171a;
	font-family: "Segoe UI";
	font-size: 10pt;
}

QFrame#sidePanel, QFrame#operatorsPanel {
	background: #ffffff;
	border: 1px solid #e4e4e8;
	border-radius: 16px;
}

QFrame#settingsPanel {
	background: #ffffff;
	border: 1px solid #dedee4;
	border-radius: 12px;
}

QLabel {
	background: #f7f7f9;
	border-radius: 6px;
	padding: 2px 5px;
}

QLabel#settingsTitle, QLabel#settingsHeading {
	color: #17171a;
}

QLabel#settingsTitle {
	font-size: 18pt;
	font-weight: 700;
}

QLabel#settingsSubtitle {
	color: #707078;
	font-size: 10pt;
}

QLabel#settingsHeading {
	font-size: 11pt;
	font-weight: 700;
}

QLabel#settingsLabel {
	color: #333338;
	font-size: 10pt;
}

QPushButton {
	background: #18181b;
	border: 1px solid #18181b;
	color: #ffffff;
	border-radius: 9px;
	padding: 6px 10px;
}

QPushButton:hover {
	background: #2b2b30;
	border-color: #2b2b30;
}

QPushButton:pressed {
	background: #f0e8ff;
	border-color: #8A2BE2;
}

QPushButton#operatorButton {
	background: #ffffff;
	color: #17171a;
	border: 1px solid #e4e4e8;
	border-radius: 12px;
	padding: 8px;
}

QPushButton#operatorButton:hover {
	background: #f0f0f3;
	border-color: #d3d3d9;
}

QLabel#sectionLabel {
	color: #000000;
	font-size: 9pt;
	font-weight: 700;
	padding-top: 4px;
	padding-bottom: 1px;
}

QDoubleSpinBox, QSpinBox {
	background: #ffffff;
	color: #17171a;
	border: 1px solid #d9d9df;
	border-radius: 8px;
	padding: 5px 7px;
}

QDoubleSpinBox:focus, QSpinBox:focus {
	border: 1px solid #8A2BE2;
}

QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {
	width: 0px;
	border: none;
}

QScrollBar:vertical {
	background: transparent;
	width: 8px;
}

QScrollBar::handle:vertical {
	background: #d2d2d8;
	border-radius: 4px;
	min-height: 30px;
}
"""

DARK_STYLE = """
QWidget {
	background: #1e1e1e;
	color: #ffffff;
}

QFrame#sidePanel, QFrame#operatorsPanel, QFrame#settingsPanel {
	background: #252526;
	border-color: #3e3e42;
	border-radius: 16px;
}

QLabel {
	background: #202022;
	border-radius: 6px;
	padding: 2px 5px;
}

QLabel, QLabel#settingsTitle, QLabel#settingsSubtitle, QLabel#settingsHeading,
QLabel#settingsLabel, QLabel#sectionLabel {
	color: #ffffff;
}

QPushButton#operatorButton {
	background: #252526;
	color: #ffffff;
	border-color: #3e3e42;
	border-radius: 12px;
}

QPushButton#operatorButton:hover {
	background: #2d2d30;
	border-color: #56565c;
}

QPushButton {
	border-radius: 9px;
}

QDoubleSpinBox, QSpinBox {
	background: #3c3c3c;
	color: #ffffff;
	border-color: #56565c;
	border-radius: 8px;
}

QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {
	width: 0px;
	border: none;
}

QScrollBar::handle:vertical {
	background: #686868;
}
"""

import json
import os
import sys
import time
from pathlib import Path

from opperator import (
	GlobalHotkeyFilter,
	move_cursor,
	move_cursor_if_mouse1_held,
	set_high_process_priority,
)
from softaim import ScreenCaptureWorker

os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")

from PyQt6.QtCore import QTimer, QSize, Qt, QVariantAnimation, QEasingCurve, QRect, QUrl
from PyQt6.QtGui import QColor, QCursor, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
	QApplication,
	QFormLayout,
	QGridLayout,
	QHBoxLayout,
	QLabel,
	QPushButton,
	QSizePolicy,
	QDoubleSpinBox,
	QSpinBox,
	QComboBox,
	QStackedLayout,
	QVBoxLayout,
	QWidget,
	QFrame,
)
from PyQt6.QtQuickWidgets import QQuickWidget

app = QApplication(sys.argv)


class DetectionOverlay(QWidget):
	"""D3D11-backed transparent overlay with a clickable recoil control."""

	def __init__(self, recoil_button_callback, softaim_button_callback):
		super().__init__(None)
		transparent_input = getattr(
			Qt.WindowType, "WindowTransparentForInput", Qt.WindowType(0)
		)
		self.setWindowFlags(
			Qt.WindowType.FramelessWindowHint
			| Qt.WindowType.WindowStaysOnTopHint
			| Qt.WindowType.WindowDoesNotAcceptFocus
			| transparent_input
		)
		self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
		self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
		self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
		self._box = None
		self._screen_geometry = QRect()
		self.quick_surface = QQuickWidget(self)
		self.quick_surface.setResizeMode(
			QQuickWidget.ResizeMode.SizeRootObjectToView
		)
		self.quick_surface.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
		self.quick_surface.setEnabled(False)
		self.quick_surface.setClearColor(QColor(0, 0, 0, 0))
		self.quick_surface.setSource(
			QUrl.fromLocalFile(str(Path(__file__).parent / "overlay.qml"))
		)
		# Keep the full-screen detection surface click-through. The control lives
		# in its own small window so it can still receive mouse clicks.
		self.recoil_button = QPushButton("RECOIL: DISABLED")
		self.recoil_button.setWindowFlags(
			Qt.WindowType.FramelessWindowHint
			| Qt.WindowType.WindowStaysOnTopHint
			| Qt.WindowType.Tool
			| Qt.WindowType.WindowDoesNotAcceptFocus
		)
		self.recoil_button.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
		self.recoil_button.setCheckable(True)
		self.recoil_button.setFixedSize(150, 32)
		self.recoil_button.clicked.connect(recoil_button_callback)
		self.recoil_button.setStyleSheet(
			"QPushButton { background: rgba(24, 24, 27, 220); color: white; "
			"border: 1px solid #8A2BE2; border-radius: 6px; font-weight: 700; }"
		)
		self.softaim_button = QPushButton("SOFTAIM: DISABLED")
		self.softaim_button.setWindowFlags(self.recoil_button.windowFlags())
		self.softaim_button.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
		self.softaim_button.setCheckable(True)
		self.softaim_button.setFixedSize(150, 32)
		self.softaim_button.clicked.connect(softaim_button_callback)
		self.softaim_button.setStyleSheet(
			"QPushButton { background: rgba(24, 24, 27, 220); color: white; "
			"border: 1px solid #8A2BE2; border-radius: 6px; font-weight: 700; }"
		)

	def resizeEvent(self, event):
		self.quick_surface.setGeometry(self.rect())
		super().resizeEvent(event)

	def set_screen_geometry(self, geometry: QRect):
		self._screen_geometry = geometry
		self.setGeometry(geometry)
		self.recoil_button.move(geometry.left() + 10, geometry.top() + 10)
		self.softaim_button.move(geometry.left() + 10, geometry.top() + 48)
		self.recoil_button.raise_()
		self.softaim_button.raise_()
		self.recoil_button.show()
		self.softaim_button.show()

	def set_fov_degrees(self, fov_degrees):
		root = self.quick_surface.rootObject()
		if root is not None:
			root.setProperty("fovDegrees", float(fov_degrees))

	def set_box(self, box):
		self._box = box
		root = self.quick_surface.rootObject()
		if root is None:
			return
		if box is None:
			root.setProperty("detections", [])
			root.setProperty("boxVisible", False)
			root.setProperty("headVisible", False)
			return
		left, top, right, bottom = box
		root.setProperty("boxLeft", left)
		root.setProperty("boxTop", top)
		root.setProperty("boxWidth", right - left)
		root.setProperty("boxHeight", bottom - top)
		root.setProperty("boxVisible", True)

	def set_detection(
		self, box, team, confidence, head_box, head_confidence, detections
	):
		root = self.quick_surface.rootObject()
		if root is None:
			return
		root.setProperty("detections", detections or [])
		if box is None:
			root.setProperty("boxVisible", False)
		else:
			left, top, right, bottom = box
			root.setProperty("boxLeft", left)
			root.setProperty("boxTop", top)
			root.setProperty("boxWidth", right - left)
			root.setProperty("boxHeight", bottom - top)
			root.setProperty("boxTeam", team)
			root.setProperty("boxConfidence", confidence)
			root.setProperty("boxVisible", True)
		if head_box is None:
			root.setProperty("headVisible", False)
		else:
			left, top, right, bottom = head_box
			root.setProperty("headLeft", left)
			root.setProperty("headTop", top)
			root.setProperty("headWidth", right - left)
			root.setProperty("headHeight", bottom - top)
			root.setProperty("headConfidence", head_confidence)
			root.setProperty("headVisible", True)

	def set_recoil_state(self, enabled):
		self.recoil_button.blockSignals(True)
		self.recoil_button.setChecked(enabled)
		self.recoil_button.setText("RECOIL: ENABLED" if enabled else "RECOIL: DISABLED")
		self.recoil_button.blockSignals(False)

	def set_softaim_state(self, enabled):
		self.softaim_button.blockSignals(True)
		self.softaim_button.setChecked(enabled)
		self.softaim_button.setText("SOFTAIM: ENABLED" if enabled else "SOFTAIM: DISABLED")
		self.softaim_button.blockSignals(False)

	def closeEvent(self, event):
		self.recoil_button.hide()
		self.softaim_button.hide()
		self.hide()
		super().closeEvent(event)

class CleanDoubleSpinBox(QDoubleSpinBox):
	"""Display up to two decimal places without unnecessary zeroes."""

	def textFromValue(self, value):
		text = f"{value:.2f}".rstrip("0").rstrip(".")
		return "0" if text in ("-0", "") else text


class ScriptsWindow(QWidget):
	def __init__(self):
		super().__init__()
		data_path = Path(__file__).parent / "opperator info" / "operators.json"
		with data_path.open(encoding="utf-8-sig") as data_file:
			all_data = json.load(data_file)
			self.gun_data = all_data.get("guns", {})
			self.operator_data = all_data.get("operators", {})
		self.gun_data_path = data_path
		self.clean_operator_loadouts()
		settings_path = Path(__file__).parent / "opperator info" / "settings.json"
		with settings_path.open(encoding="utf-8-sig") as settings_file:
			self.settings_data = json.load(settings_file).get("settings", {})
		self.settings_path = settings_path
		self.setWindowTitle("Steam")
		self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
		self._resizing = False
		self.dark_mode_enabled = False
		self.monitor_index = int(self.settings_data.get("MONITOR_INDEX", 1))
		self.softaim_worker = ScreenCaptureWorker()
		self.softaim_enabled = False
		self.softaim_worker.start()
		self.softaim_worker.set_enabled(True)
		QApplication.instance().aboutToQuit.connect(self._stop_softaim)
		self.operator_detected = False

		# Sensitivity inputs start hidden; toggled with Ctrl+Alt+H
		self.sens_visible = False

		screen = QApplication.primaryScreen().availableGeometry()
		self.button_size = max(1, min(screen.width() // 8, screen.height() // 16))

		# Full-width top tabs – 3 equal boxes; underline = bottom border only
		self.tab_buttons = {}
		tab_bar = QHBoxLayout()
		tab_bar.setContentsMargins(0, 0, 0, 0)
		tab_bar.setSpacing(0)
		for tab_name in ("RECOIL", "SOFTAIM", "R6 SETTINGS", "SETTINGS"):
			btn = QPushButton(tab_name)
			btn.setCheckable(True)
			btn.setMinimumHeight(44)
			btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
			btn.setCursor(Qt.CursorShape.PointingHandCursor)
			btn.clicked.connect(lambda checked=False, name=tab_name: self._switch_tab(name))
			self.tab_buttons[tab_name] = btn
			tab_bar.addWidget(btn, 1)

		self.tab_bar_widget = QWidget()
		self.tab_bar_widget.setLayout(tab_bar)

		category_buttons = QHBoxLayout()
		category_buttons.setContentsMargins(0, 0, 0, 0)
		category_buttons.setSpacing(0)
		self.category_bar_widget = QWidget()
		self.category_bar_widget.setLayout(category_buttons)
		self.category_buttons = []
		for label in ("attackers", "defenders"):
			button = QPushButton(label.upper())
			button.setCheckable(True)
			button.setMinimumHeight(44)
			button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
			button.setCursor(Qt.CursorShape.PointingHandCursor)
			button.clicked.connect(lambda checked=False, side=label: self.show_buttons(side))
			category_buttons.addWidget(button)
			self.category_buttons.append(button)

		self.side_btn_width = 122
		self.side_btn_height = 34

		self.extra_buttons = QGridLayout()
		self.extra_buttons.setContentsMargins(12, 12, 12, 12)
		self.extra_buttons.setHorizontalSpacing(10)
		self.extra_buttons.setVerticalSpacing(10)
		self.operator_buttons = []
		self.operators_panel = QFrame()
		self.operators_panel.setObjectName("operatorsPanel")
		self.operators_panel.setLayout(self.extra_buttons)
		self.operators_area = QWidget()
		operators_area_layout = QVBoxLayout(self.operators_area)
		operators_area_layout.setContentsMargins(0, 0, 0, 0)
		operators_area_layout.setSpacing(6)
		operators_area_layout.addWidget(self.category_bar_widget)
		operators_area_layout.addWidget(self.operators_panel, 1)
		self.side_menu = QVBoxLayout()
		self.side_menu_widget = QFrame()
		self.side_menu_widget.setObjectName("sidePanel")
		self.side_menu_widget.setLayout(self.side_menu)
		self.side_menu.setContentsMargins(18, 18, 18, 18)
		self.side_menu.setSpacing(8)
		self.side_menu_widget.setFixedWidth(330)
		self.side_menu_widget.hide()
		# Hidden recoil state – F1 / F2 only
		self.toggle_button = QPushButton()
		self.toggle_button.setCheckable(True)
		self.toggle_button.setChecked(False)
		self.toggle_button.hide()
		self.toggle_button.toggled.connect(self.update_toggle_button)
		self.detection_overlay = DetectionOverlay(
			self.toggle_button.setChecked,
			lambda enabled: self.softaim_button.setChecked(enabled),
		)
		self.detection_overlay.set_recoil_state(False)
		self.detection_overlay.set_softaim_state(False)

		self._pulse_anim = QVariantAnimation(self)
		self._pulse_anim.valueChanged.connect(self._on_pulse_color)
		self._pulse_anim.finished.connect(self._on_pulse_finished)
		self._pulse_going_dark = True

		# Guns that get the Auto Shoot ON/OFF controls
		self.extra_switch_guns = {
			"417",
			"OTs-03",
			"CAMRS",
			"SR-25",
			"Mk 14 EBR",
			"AR-15.50",
			"TSCG12",
		}

		# Shotguns to exclude
		self.excluded_shotguns = {
			"m590a1",
			"m1014",
			"sg-cqb",
			"sasg-12",
			"m870",
			"super 90",
			"spas-12",
			"spas-15",
			"supernova",
			"ita12l",
			"six12",
			"fo-12",
			"bosg.12.2",
			"acs12",
			"tcsg12",
			"six12 sd",
		}
		# Secondary weapons that should not have zoom options
		self.secondary_gun_names = {
			"smg-11",
			"smg-12",
			"reaper mk2",
			"bearing 9",
			"c75 auto",
			".44 vendetta",
			"spsmg9",
		}

		# DMRs to exclude (WIP)
		self.excluded_dmrs = {
			"417",
			"ots-03",
			"camrs",
			"sr-25",
			"mk 14 ebr",
			"ar-15.50",
			"csrx 300",
			"pmr90a2",
		}

		# Bool state for auto-shoot (same idea as the recoil toggle)
		self.auto_shoot_enabled = False

		# Global hotkeys F1-F4 – work even when the game is focused
		self.global_hotkeys = GlobalHotkeyFilter(
			on_f1=self.toggle_recoil,
			on_f2=self.toggle_softaim_hotkey,
			on_f3=self.auto_shoot_on,
			on_f4=self.auto_shoot_off,
		)
		QApplication.instance().installNativeEventFilter(self.global_hotkeys)
		QApplication.instance().aboutToQuit.connect(self.global_hotkeys.unregister)

		# 10 ms timer drives both recoil and auto-shoot
		self.cursor_timer = QTimer(self)
		self.cursor_timer.timeout.connect(self._on_cursor_timer)
		self.cursor_timer.start(10)

		# Ctrl+Alt+H toggles sensitivity visibility
		self.sens_toggle_shortcut = QShortcut(QKeySequence("Ctrl+Alt+H"), self)
		self.sens_toggle_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
		self.sens_toggle_shortcut.activated.connect(self.toggle_sens_visibility)

		content = QHBoxLayout()
		content.setContentsMargins(18, 6, 18, 18)
		content.setSpacing(18)
		content.addWidget(self.operators_area, 1)
		content.addWidget(self.side_menu_widget)

		recoil_layout = QVBoxLayout()
		recoil_layout.setContentsMargins(0, 0, 0, 0)
		recoil_layout.setSpacing(6)
		recoil_layout.addLayout(content, 1)
		recoil_page = QWidget()
		recoil_page.setLayout(recoil_layout)

		r6_page = QWidget()
		r6_layout = QVBoxLayout(r6_page)
		r6_layout.setContentsMargins(40, 30, 40, 30)
		r6_layout.setSpacing(8)
		r6_title = QLabel("R6 SETTINGS")
		r6_title.setObjectName("settingsTitle")
		r6_layout.addWidget(r6_title)
		r6_subtitle = QLabel("put in YOUR sensitivity you dumbass")
		r6_subtitle.setObjectName("settingsSubtitle")
		r6_layout.addWidget(r6_subtitle)
		r6_layout.addSpacing(14)

		settings_panel = QFrame()
		settings_panel.setObjectName("settingsPanel")
		settings_panel_layout = QVBoxLayout(settings_panel)
		settings_panel_layout.setContentsMargins(24, 22, 24, 24)
		settings_panel_layout.setSpacing(16)
		settings_heading = QLabel("Sensitivity profile")
		settings_heading.setObjectName("settingsHeading")
		settings_panel_layout.addWidget(settings_heading)
		settings_form = QFormLayout()
		settings_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
		settings_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
		settings_form.setHorizontalSpacing(36)
		settings_form.setVerticalSpacing(14)
		self.setting_inputs = {}
		setting_labels = {
			"SENS": "Main sensitivity",
			"1.0X": "1.0x ADS sensitivity",
			"2.5X": "2.5x ADS sensitivity",
		}
		for setting_name in ("SENS", "1.0X", "2.5X"):
			label = QLabel(setting_labels[setting_name])
			label.setObjectName("settingsLabel")
			setting = CleanDoubleSpinBox()
			setting.setRange(-1e100, 1e100)
			setting.setDecimals(15)
			setting.setSingleStep(0.1)
			setting.setMinimumWidth(220)
			setting.setAlignment(Qt.AlignmentFlag.AlignRight)
			default_value = self.settings_data.get(setting_name, 50.0)
			setting.setValue(float(default_value))
			setting.valueChanged.connect(
				lambda value, name=setting_name: self.save_setting(name, value)
			)
			self.setting_inputs[setting_name] = setting
			settings_form.addRow(label, setting)
		settings_panel_layout.addLayout(settings_form)
		monitor_label = QLabel("Overlay monitor")
		monitor_label.setObjectName("settingsLabel")
		self.monitor_combo = QComboBox()
		self.populate_monitor_options()
		self.monitor_combo.currentIndexChanged.connect(self.select_monitor)
		monitor_row = QHBoxLayout()
		monitor_row.addWidget(monitor_label)
		monitor_row.addWidget(self.monitor_combo)
		settings_panel_layout.addLayout(monitor_row)
		r6_layout.addWidget(settings_panel, 0, Qt.AlignmentFlag.AlignLeft)
		r6_layout.addStretch()

		ui_page = QWidget()
		ui_layout = QVBoxLayout(ui_page)
		ui_layout.setContentsMargins(40, 30, 40, 30)
		ui_title = QLabel("Nigga am to lazy to do ts")
		ui_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
		ui_title.setStyleSheet("font-size: 14pt; font-weight: 700; color: #000000;")
		ui_layout.addWidget(ui_title)
		ui_hint = QLabel("DMRS FUTURE UPDATE")
		ui_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
		ui_hint.setStyleSheet("color: #707078;")
		ui_layout.addWidget(ui_hint)
		self.ui_title = ui_title
		self.ui_hint = ui_hint
		self.dark_mode_button = QPushButton("Dark mode")
		self.dark_mode_button.setCheckable(True)
		self.dark_mode_button.setFixedSize(180, 40)
		self.dark_mode_button.clicked.connect(self.toggle_dark_mode)
		ui_layout.addWidget(self.dark_mode_button, 0, Qt.AlignmentFlag.AlignCenter)
		ui_layout.addStretch()

		softaim_page = QWidget()
		softaim_layout = QVBoxLayout(softaim_page)
		softaim_layout.setContentsMargins(40, 30, 40, 30)
		softaim_layout.setSpacing(16)
		softaim_title = QLabel("SOFTAIM")
		softaim_title.setObjectName("settingsTitle")
		softaim_layout.addWidget(softaim_title, 0, Qt.AlignmentFlag.AlignCenter)
		self.softaim_button = QPushButton()
		self.softaim_button.setCheckable(True)
		self.softaim_button.setFixedSize(180, 40)
		self.softaim_button.toggled.connect(self.toggle_softaim)
		softaim_layout.addWidget(self.softaim_button, 0, Qt.AlignmentFlag.AlignCenter)
		target_speed_row = QHBoxLayout()
		target_speed_label = QLabel("Target Speed")
		target_speed_label.setObjectName("settingsLabel")
		self.target_speed_input = QSpinBox()
		self.target_speed_input.setRange(1, 10)
		self.target_speed_input.setValue(
			max(1, min(10, int(self.settings_data.get("TARGET_SPEED", 10))))
		)
		self.target_speed_input.valueChanged.connect(self._set_target_speed)
		target_speed_row.addWidget(target_speed_label)
		target_speed_row.addWidget(self.target_speed_input)
		softaim_layout.addLayout(target_speed_row)
		fov_row = QHBoxLayout()
		fov_label = QLabel("Detection FOV (degrees)")
		fov_label.setObjectName("settingsLabel")
		self.fov_input = QDoubleSpinBox()
		self.fov_input.setRange(1.0, 180.0)
		self.fov_input.setDecimals(1)
		self.fov_input.setSingleStep(1.0)
		self.fov_input.setValue(
			max(1.0, min(180.0, float(self.settings_data.get("FOV_DEGREES", 10.0))))
		)
		self.fov_input.valueChanged.connect(self._set_fov_degrees)
		fov_row.addWidget(fov_label)
		fov_row.addWidget(self.fov_input)
		softaim_layout.addLayout(fov_row)
		self.softaim_worker.set_fov_degrees(self.fov_input.value())
		self.detection_overlay.set_fov_degrees(self.fov_input.value())
		self.softaim_target_label = QLabel("TARGET: ALL OPERATORS")
		self.softaim_target_label.setObjectName("settingsHeading")
		self.softaim_target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		softaim_layout.addWidget(self.softaim_target_label)
		self.softaim_status_label = QLabel("STATUS: NOT FOUND")
		self.softaim_status_label.setObjectName("settingsLabel")
		self.softaim_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		softaim_layout.addWidget(self.softaim_status_label)
		self.softaim_detected_label = QLabel("NOT DETECTED")
		self.softaim_detected_label.setObjectName("settingsLabel")
		self.softaim_detected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		softaim_layout.addWidget(self.softaim_detected_label)
		softaim_layout.addStretch()
		self.update_softaim_button(False)
		self.softaim_status_timer = QTimer(self)
		self.softaim_status_timer.timeout.connect(self.update_softaim_status)
		self.softaim_status_timer.start(100)

		self.page_stack = QStackedLayout()
		self.page_stack.addWidget(recoil_page)
		self.page_stack.addWidget(softaim_page)
		self.page_stack.addWidget(r6_page)
		self.page_stack.addWidget(ui_page)

		root = QVBoxLayout()
		root.setContentsMargins(0, 0, 0, 0)
		root.setSpacing(0)
		root.addWidget(self.tab_bar_widget)
		root.addLayout(self.page_stack, 1)
		self.setLayout(root)
		self.setFixedSize(1280, 720)

		self._switch_tab("RECOIL")
		self.show_buttons("attackers")
		self.position_detection_overlay()

	def _on_cursor_timer(self):
		"""10 ms loop for softaim, recoil mouse movement, and auto-shoot."""
		self.global_hotkeys.poll_fallback()
		if self.softaim_enabled:
			result = self.softaim_worker.get_latest_result()
			if result.get("team") == "ENEMY":
				target_box = result.get("head_box") or result.get("box")
				if target_box is not None:
					left, top, right, bottom = target_box
					screens = QApplication.screens()
					screen = screens[max(0, min(self.monitor_index - 1, len(screens) - 1))]
					geometry = screen.geometry()
					target_x = geometry.left() + (left + right) / 2
					target_y = geometry.top() + (top + bottom) / 2
					cursor = QCursor.pos()
					speed = self.target_speed_input.value() / 10.0
					move_cursor(
						(target_x - cursor.x()) * speed,
						(target_y - cursor.y()) * speed,
					)
		gun_ok = getattr(self, "active_gun", "") in self.extra_switch_guns											
		move_cursor_if_mouse1_held(
			self.toggle_button,
			self.get_active_sensitivity(),
			auto_shoot_enabled=self.auto_shoot_enabled and gun_ok,
			operator_detected=self.operator_detected,
		)

	def populate_monitor_options(self):
		self.monitor_combo.clear()
		for index, screen in enumerate(QApplication.screens(), start=1):
			geometry = screen.geometry()
			primary = " (Windows primary)" if screen is QApplication.primaryScreen() else ""
			self.monitor_combo.addItem(
				f"Monitor {index}: {geometry.width()}x{geometry.height()}{primary}"
			)
		if self.monitor_combo.count():
			self.monitor_combo.setCurrentIndex(max(0, min(self.monitor_index - 1, self.monitor_combo.count() - 1)))

	def select_monitor(self, combo_index):
		if combo_index < 0:
			return
		self.monitor_index = combo_index + 1
		self.settings_data["MONITOR_INDEX"] = self.monitor_index
		with self.settings_path.open("w", encoding="utf-8") as settings_file:
			json.dump({"settings": self.settings_data}, settings_file, indent=2)
		self.softaim_worker.set_monitor(self.monitor_index)
		self.position_detection_overlay()

	def position_detection_overlay(self):
		screens = QApplication.screens()
		if not screens:
			return
		screen = screens[max(0, min(self.monitor_index - 1, len(screens) - 1))]
		self.detection_overlay.set_screen_geometry(screen.geometry())
		self.detection_overlay.show()
		self.detection_overlay.raise_()

	def update_recoil_overlay(self, enabled):
		self.detection_overlay.set_recoil_state(enabled)

	def _set_auto_shoot(self, enabled: bool):
		"""Set the hotkey-controlled auto-shoot state."""
		self.auto_shoot_enabled = bool(enabled)

	def toggle_sens_visibility(self):
		"""Toggle horizontal/vertical sensitivity widgets (Ctrl+Alt+H)."""
		self.sens_visible = not self.sens_visible
		if hasattr(self, "horizontal_sens_label"):
			self.horizontal_sens_label.setVisible(self.sens_visible)
			self.horizontal_sens_input.setVisible(self.sens_visible)
			self.vertical_sens_label.setVisible(self.sens_visible)
			self.vertical_sens_input.setVisible(self.sens_visible)

	def _switch_tab(self, name: str):
		"""Underline the tab *box* (bottom border), not the text."""
		index = {"RECOIL": 0, "SOFTAIM": 1, "R6 SETTINGS": 2, "SETTINGS": 3}.get(name, 0)
		self.page_stack.setCurrentIndex(index)
		for tab_name, btn in self.tab_buttons.items():
			active = tab_name == name
			btn.setChecked(active)
			if active:
				btn.setStyleSheet(
					"QPushButton {"
					f"  background-color: {'#333333' if self.dark_mode_enabled else '#f0f0f3'};"
					f"  color: {'#ffffff' if self.dark_mode_enabled else '#000000'};"
					"  border: none;"
					"  border-bottom: 3px solid #8A2BE2;"
					"  border-radius: 0px;"
					"  font-weight: 700;"
					"  font-size: 11pt;"
					"  text-decoration: none;"
					"  padding: 12px 8px;"
					"}"
				)
			else:
				btn.setStyleSheet(
					"QPushButton {"
					f"  background-color: {'#252526' if self.dark_mode_enabled else '#ffffff'};"
					f"  color: {'#ffffff' if self.dark_mode_enabled else '#000000'};"
					"  border: none;"
					f"  border-bottom: 3px solid {'#3a3a3d' if self.dark_mode_enabled else '#e4e4e8'};"
					"  border-radius: 0px;"
					"  font-weight: 700;"
					"  font-size: 11pt;"
					"  text-decoration: none;"
					"  padding: 12px 8px;"
					"}"
					f"QPushButton:hover {{ background-color: {'#3e3e42' if self.dark_mode_enabled else '#f7f7f9'}; }}"
				)

	def toggle_dark_mode(self, enabled):
		"""Switch between the light theme and a VS Code-inspired dark theme."""
		self.dark_mode_enabled = bool(enabled)
		QApplication.instance().setStyleSheet(
			DARK_STYLE if self.dark_mode_enabled else LIGHT_STYLE
		)
		self.ui_title.setStyleSheet(
			"font-size: 14pt; font-weight: 700; color: #ffffff;"
			if self.dark_mode_enabled
			else "font-size: 14pt; font-weight: 700; color: #000000;"
		)
		self.ui_hint.setStyleSheet(
			"color: #cccccc;" if self.dark_mode_enabled else "color: #707078;"
		)
		self.dark_mode_button.setText(
			"Light mode" if self.dark_mode_enabled else "Dark mode"
		)
		self.dark_mode_button.setStyleSheet(
			"background: #ffffff; color: #17171a; border: 1px solid #ffffff;"
			if self.dark_mode_enabled
			else ""
		)
		self._switch_tab(
			next(
				(name for name, button in self.tab_buttons.items() if button.isChecked()),
				"RECOIL",
			)
		)
		if hasattr(self, "current_side"):
			self.show_buttons(self.current_side)
		if hasattr(self, "softaim_button"):
			self.update_softaim_button(self.softaim_enabled)

	def toggle_softaim(self, enabled):
		"""Enable or disable cursor movement while detection continues."""
		self.softaim_enabled = bool(enabled)
		self.detection_overlay.set_softaim_state(self.softaim_enabled)
		if not self.softaim_enabled:
			self.operator_detected = False
		self.update_softaim_button(self.softaim_enabled)
		self.position_detection_overlay()
		if not self.softaim_enabled:
			self.softaim_status_label.setText("STATUS: NOT FOUND")
			self.detection_overlay.set_box(None)

	def _set_target_speed(self, value):
		self.save_setting("TARGET_SPEED", int(value))

	def _set_fov_degrees(self, value):
		fov_degrees = float(value)
		self.softaim_worker.set_fov_degrees(fov_degrees)
		self.detection_overlay.set_fov_degrees(fov_degrees)
		self.save_setting("FOV_DEGREES", fov_degrees)

	def update_softaim_status(self):
		if not hasattr(self, "softaim_status_label"):
			return
		result = self.softaim_worker.get_latest_result()
		self.softaim_worker.record_ui_receive(result)
		self.operator_detected = bool(result.get("found", False))
		status = "FOUND" if result.get("found", False) else "NOT FOUND"
		self.softaim_status_label.setText(f"STATUS: {status}")
		render_started = time.perf_counter()
		self.detection_overlay.set_detection(
			result.get("box"),
			str(result.get("team", "")),
			float(result.get("confidence", 0.0)),
			result.get("head_box"),
			float(result.get("head_confidence", 0.0)),
			result.get("detections", []),
		)
		self.softaim_worker.record_render_time(
			(time.perf_counter() - render_started) * 1000
		)
		self.softaim_detected_label.setText(
			"DETECTED" if self.operator_detected else "NOT DETECTED"
		)

	def update_softaim_button(self, enabled):
		if not hasattr(self, "softaim_button"):
			return
		self.softaim_button.setText("ENABLED" if enabled else "DISABLED")
		self.style_selection_button(self.softaim_button, bool(enabled))

	def _stop_softaim(self):
		self.softaim_worker.stop()
		self.softaim_worker.join(timeout=1)

	def closeEvent(self, event):
		self.cursor_timer.stop()
		self.softaim_status_timer.stop()
		self.softaim_enabled = False
		self.softaim_worker.set_enabled(False)
		self.detection_overlay.set_box(None)
		self.detection_overlay.close()
		super().closeEvent(event)

	def save_setting(self, setting_name, value):
		"""Save a global setting.

		SENS is the game's main sensitivity. A higher SENS means less
		physical mouse movement is required, so the runtime pull is scaled
		by old/new SENS. Gun values are stored as one canonical profile and
		converted for the selected zoom using the ADS ratio.
		"""
		self.settings_data[setting_name] = float(value)
		with self.settings_path.open("w", encoding="utf-8") as settings_file:
			json.dump({"settings": self.settings_data}, settings_file, indent=2)


	def show_buttons(self, side):
		self.current_side = side
		for label, button in zip(("attackers", "defenders"), self.category_buttons):
			active = label == side
			button.setChecked(active)
			button.setStyleSheet(
				"QPushButton {"
				f"  background-color: {('#333333' if self.dark_mode_enabled else '#f0f0f3') if active else ('#252526' if self.dark_mode_enabled else '#ffffff')};"
				f"  color: {'#ffffff' if self.dark_mode_enabled else '#000000'};"
				"  border: none;"
				f"  border-bottom: 3px solid {'#8A2BE2' if active else ('#3a3a3d' if self.dark_mode_enabled else '#e4e4e8')};"
				"  border-radius: 0px;"
				"  font-weight: 700;"
				"  font-size: 11pt;"
				"  padding: 12px 8px;"
				"}"
				f"QPushButton:hover {{ background-color: {'#3e3e42' if self.dark_mode_enabled else '#f7f7f9'}; }}"
			)
		self.side_menu_widget.hide()
		while self.extra_buttons.count():
			item = self.extra_buttons.takeAt(0)
			if item.widget() is not None:
				item.widget().deleteLater()
		self.operator_buttons.clear()

		attacker_names = [
			"Striker", "Sledge", "Thatcher", "Ash", "Thermite", "Twitch", "Montagne",
			"Glaz", "Fuze", "Blitz", "IQ", "Buck", "Blackbeard", "Capitão",
			"Hibana", "Jackal", "Ying", "Zofia", "Dokkaebi", "Lion", "Finka",
			"Maverick", "Nomad", "Gridlock", "NØKK", "Amaru", "Kali", "Iana",
			"Ace", "Zero", "Flores", "Osa", "Sens", "Grim", "Brava", "Ram",
			"Deimos", "Rauora", "Solid Snake", "Dummy",
		]
		defender_names = [
			"Sentry", "Smoke", "Mute", "Castle", "Pulse", "Doc", "Rook",
			"Kapkan", "Tachanka", "Jäger", "Bandit", "Frost", "Valkyrie", "Caveira",
			"Echo", "Mira", "Lesion", "Ela", "Vigil", "Maestro", "Alibi", "Clash",
			"Kaid", "Mozzie", "Warden", "Goyo", "Wamai", "Oryx", "Melusi", "Aruni",
			"Thunderbird", "Thorn", "Azami", "Solis", "Fenrir", "Tubarão", "Skopós",
			"Denari", "Noor",
		]
		button_names = attacker_names if side == "attackers" else defender_names
		icon_directory = Path(__file__).parent / "icons" / side

		for number, name in enumerate(button_names, start=1):
			button = QPushButton(name)
			button.setObjectName("operatorButton")
			button.setFixedSize(self.button_size, self.button_size)
			icon_name = {
				"Solid Snake": "soild snake",
			}.get(
				name,
				name.lower()
				.replace("ø", "o")
				.replace("ã", "a")
				.replace("ä", "a")
				.replace("ó", "o"),
			)
			icon_path = icon_directory / f"{icon_name}.svg"
			if icon_path.exists():
				button.setIcon(QIcon(str(icon_path)))
				button.setIconSize(QSize(self.button_size, self.button_size))
				button.setText("")
			button.setStyleSheet(
				"background-color: transparent; border: none; padding: 0px;"
			)
			button.clicked.connect(
				lambda checked=False, name=name: self.show_side_menu(name)
			)
			self.extra_buttons.addWidget(button, (number - 1) // 6, (number - 1) % 6)
			self.operator_buttons.append(button)

		self.show_side_menu("Striker" if side == "attackers" else "Sentry")

	def show_side_menu(self, button_name):
		self.active_operator = button_name

		for attr in (
			"recoil_status_dot", "recoil_status_label", "recoil_status_wrap",
		):
			if hasattr(self, attr):
				w = getattr(self, attr)
				w.setParent(None)
				w.deleteLater()
				delattr(self, attr)

		self.clear_layout(self.side_menu)

		icon_name = {
			"Solid Snake": "soild snake",
		}.get(
			button_name,
			button_name.lower()
			.replace("ø", "o")
			.replace("ã", "a")
			.replace("ä", "a")
			.replace("ó", "o"),
		)
		self.compact_button = QPushButton("⌄")
		self.compact_button.setCheckable(True)
		self.compact_button.setFixedSize(30, 30)
		self.compact_button.setToolTip("Toggle compact UI")
		self.compact_button.setStyleSheet(
			f"color: {'#ffffff' if self.dark_mode_enabled else '#707078'}; background: transparent; border: none; "
			"font-size: 30px; font-weight: 700; padding: 0px; margin: 0px;"
		)
		self.compact_button.toggled.connect(self.toggle_compact_mode)
		self.side_menu.addWidget(self.compact_button, 0, Qt.AlignmentFlag.AlignLeft)

		icon_path = Path(__file__).parent / "icons" / self.current_side / f"{icon_name}.svg"
		if icon_path.exists():
			operator_icon = QLabel()
			operator_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
			operator_icon.setPixmap(
				QIcon(str(icon_path)).pixmap(QSize(self.button_size * 2, self.button_size * 2))
			)
			self.side_menu.addWidget(operator_icon)
		operator_data = self.operator_data.get(button_name, {})
		gun_lists = (
			("Primary Gun", operator_data.get("primary_guns", [])),
			("Secondary Gun", operator_data.get("secondary_guns", [])),
		)
		self.active_gun = next(
			(
				gun_name
				for _, gun_names in gun_lists
				for gun_name in gun_names
				if gun_name in self.gun_data 
				and gun_name.lower() not in self.excluded_shotguns
				and gun_name.lower() not in self.excluded_dmrs
			),
			"",
		)
		self.gun_buttons = []
		for label, gun_names in gun_lists:
			# Filter out excluded shotguns and DMRs
			filtered_gun_names = [
				gun for gun in gun_names
				if gun.lower() not in self.excluded_shotguns
				and gun.lower() not in self.excluded_dmrs
			]
			if label == "Secondary Gun" and not filtered_gun_names:
				continue
			section_label = QLabel(label)
			section_label.setObjectName("sectionLabel")
			section_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
			self.side_menu.addWidget(section_label)
			gun_row = QGridLayout()
			gun_row.setHorizontalSpacing(8)
			gun_row.setVerticalSpacing(8)
			for index, gun_name in enumerate(filtered_gun_names):
				gun_button = QPushButton(gun_name)
				gun_button.setCheckable(True)
				self.style_selection_button(gun_button, False)
				gun_button.setFixedSize(132, 48)
				gun_button.clicked.connect(
					lambda checked=False, name=gun_name: self.select_gun(name)
				)
				row = index // 2
				if index == 2:
					gun_row.addWidget(
						gun_button, row, 0, 1, 2, Qt.AlignmentFlag.AlignCenter
					)
				else:
					gun_row.addWidget(gun_button, row, index % 2)
				self.gun_buttons.append(gun_button)
			self.side_menu.addLayout(gun_row)

		# Horizontal / Vertical sensitivity (hidden by default)
		self.horizontal_sens_label = QLabel("Horizontal Sens")
		self.side_menu.addWidget(self.horizontal_sens_label)
		self.horizontal_sens_input = CleanDoubleSpinBox()
		self.configure_sensitivity_input(self.horizontal_sens_input)
		self.side_menu.addWidget(self.horizontal_sens_input)

		self.vertical_sens_label = QLabel("Vertical Sens")
		self.side_menu.addWidget(self.vertical_sens_label)
		self.vertical_sens_input = CleanDoubleSpinBox()
		self.configure_sensitivity_input(self.vertical_sens_input)
		self.side_menu.addWidget(self.vertical_sens_input)

		# Apply current visibility state
		self.horizontal_sens_label.setVisible(self.sens_visible)
		self.horizontal_sens_input.setVisible(self.sens_visible)
		self.vertical_sens_label.setVisible(self.sens_visible)
		self.vertical_sens_input.setVisible(self.sens_visible)

		self.select_gun(self.active_gun)
		self.zoom_buttons = {}
		zoom_layout = QHBoxLayout()
		for zoom_name in ("1.0X", "2.5X"):
			zoom_button = QPushButton(zoom_name)
			zoom_button.setCheckable(True)
			self.style_selection_button(zoom_button, False)
			zoom_button.clicked.connect(
				lambda checked=False, name=zoom_name: self.select_zoom(name)
			)
			self.zoom_buttons[zoom_name] = zoom_button
			zoom_layout.addWidget(zoom_button)
		zoom_label = QLabel("ZOOM")
		zoom_label.setObjectName("sectionLabel")
		zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.zoom_label = zoom_label
		self.side_menu.addWidget(zoom_label)
		self.side_menu.addLayout(zoom_layout)
		is_defender = self.current_side == "defenders"
		is_secondary = self.active_gun.lower() in self.secondary_gun_names
		for name, button in self.zoom_buttons.items():
			button.setVisible(
				name == "1.0X" if is_secondary or is_defender else True
			)
		self.select_zoom(self.gun_data.get(self.active_gun, {}).get("zoom", "2.5X"))

		# ENABLED / DISABLED + circular dot (aligned)
		DOT = 12
		self.recoil_status_dot = QFrame()
		self.recoil_status_dot.setFixedSize(DOT, DOT)
		self.recoil_status_dot.setStyleSheet(
			f"background-color: #000000; border: none; border-radius: {DOT // 2}px;"
		)
		self.recoil_status_label = QLabel("DISABLED")
		self.recoil_status_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

		status_inner = QHBoxLayout()
		status_inner.setContentsMargins(0, 12, 0, 12)
		status_inner.setSpacing(10)
		status_inner.addWidget(self.recoil_status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
		status_inner.addWidget(self.recoil_status_label, 0, Qt.AlignmentFlag.AlignVCenter)

		status_row = QHBoxLayout()
		status_row.addStretch()
		status_row.addLayout(status_inner)
		status_row.addStretch()

		self.recoil_status_wrap = QWidget()
		self.recoil_status_wrap.setLayout(status_row)
		self.side_menu.addWidget(self.recoil_status_wrap)

		self.update_toggle_button(self.toggle_button.isChecked())
		self.side_menu.addStretch()
		self.side_menu_widget.show()

	def clear_layout(self, layout):
		while layout.count():
			item = layout.takeAt(0)
			if item.widget() is not None:
				item.widget().deleteLater()
			elif item.layout() is not None:
				self.clear_layout(item.layout())

	def toggle_compact_mode(self, compact):
		self.compact_button.setText("⌃" if compact else "⌄")
		self.tab_bar_widget.setVisible(not compact)
		self.operators_area.setVisible(not compact)
		self.side_menu_widget.setVisible(True)
		self.setFixedSize(384 if compact else 1280, 720)

	def get_active_sensitivity(self):
		"""Return recoil compensation adjusted for current game sensitivity.

		Gun values are raw mouse-movement values tuned at the known working
		baseline: SENS 50, 1.0X 50 and 2.5X 50.

		The gun profile has one canonical sensitivity.  The 2.5X value is
		derived from it with the reversible zoom multiplier.
		"""
		gun_data = self.gun_data.get(getattr(self, "active_gun", ""), {})
		zoom = getattr(self, "active_zoom", "1.0X")
		horizontal = gun_data.get("horizontal_sens_1x", gun_data.get("horizontal_sens", 0.0))
		vertical = gun_data.get("vertical_sens_1x", gun_data.get("vertical_sens", 0.0))
		zoom_multiplier = self.get_zoom_multiplier()
		if zoom == "2.5X":
			horizontal *= zoom_multiplier
			vertical *= zoom_multiplier

		# The zoom multiplier already includes the 1.0X/2.5X ratio.
		# Apply the main sensitivity conversion once to both axes.
		scale = self.get_main_sensitivity_multiplier()

		return {
			"horizontal_sens": float(horizontal) * scale,
			"vertical_sens": float(vertical) * scale,
		}

	def get_main_sensitivity_multiplier(self):
		"""Convert the user's main sensitivity to the 50-sensitivity baseline."""
		try:
			current_sens = float(self.settings_data.get("SENS", 50.0))
		except (TypeError, ValueError):
			current_sens = 50.0
		if current_sens <= 0:
			current_sens = 50.0
		return 50.0 / current_sens

	def get_zoom_multiplier(self):
		"""Return the reversible 1.0X-to-2.5X sensitivity multiplier."""
		one_x_sensitivity = float(self.settings_data.get("1.0X", 50.0))
		two_five_x_sensitivity = float(self.settings_data.get("2.5X", 50.0))
		if one_x_sensitivity <= 0:
			one_x_sensitivity = 50.0
		if two_five_x_sensitivity <= 0:
			two_five_x_sensitivity = 50.0
		return 2.5 * one_x_sensitivity / two_five_x_sensitivity


	def select_gun(self, gun_name):
		if gun_name not in self.gun_data:
			return

		self.active_gun = gun_name

		for button in getattr(self, "gun_buttons", []):
			selected = button.text() == gun_name
			button.setChecked(selected)
			self.style_selection_button(button, selected)

		gun_data = self.gun_data[gun_name]
		# Secondary weapons are always 1.0X
		is_secondary = gun_name.lower() in self.secondary_gun_names
		is_defender = getattr(self, "current_side", "attackers") == "defenders"
		if is_secondary or is_defender:
			zoom = "1.0X"
		else:
			zoom = gun_data.get("zoom", "2.5X")
		self.active_zoom = zoom if zoom in ("1.0X", "2.5X") else "2.5X"
		
		# Show/hide zoom buttons based on gun type
		if hasattr(self, "zoom_buttons"):
			for name, button in self.zoom_buttons.items():
				button.setVisible(
					name == "1.0X" if is_secondary or is_defender else True
				)
		if hasattr(self, "zoom_label"):
			self.zoom_label.setVisible(True)

		self._refresh_zoom_sensitivity_inputs()

		if getattr(self, "zoom_buttons", None):
			self.select_zoom(self.active_zoom)

	def _refresh_zoom_sensitivity_inputs(self):
		"""Show the shared sensitivity converted from the active zoom."""
		if not hasattr(self, "horizontal_sens_input"):
			return

		gun_data = self.gun_data.get(getattr(self, "active_gun", ""), {})
		h = gun_data.get("horizontal_sens_1x", gun_data.get("horizontal_sens", 0))
		v = gun_data.get("vertical_sens_1x", gun_data.get("vertical_sens", 0))
		# Secondary guns always use 1.0X, so never apply zoom multiplier
		is_secondary = getattr(self, "active_gun", "").lower() in self.secondary_gun_names
		is_defender = getattr(self, "current_side", "attackers") == "defenders"
		if not is_secondary and not is_defender and getattr(self, "active_zoom", "1.0X") == "2.5X":
			multiplier = self.get_zoom_multiplier()
			h /= multiplier
			v /= multiplier

		self.horizontal_sens_input.blockSignals(True)
		self.vertical_sens_input.blockSignals(True)
		self.horizontal_sens_input.setValue(float(h))
		self.vertical_sens_input.setValue(float(v))
		self.horizontal_sens_input.blockSignals(False)
		self.vertical_sens_input.blockSignals(False)


	def select_zoom(self, zoom_name):
		# Secondary weapons should never change zoom from 1.0X
		is_secondary = getattr(self, "active_gun", "").lower() in self.secondary_gun_names
		is_defender = getattr(self, "current_side", "attackers") == "defenders"
		if is_secondary or is_defender:
			zoom_name = "1.0X"
		
		if zoom_name not in ("1.0X", "2.5X"):
			zoom_name = "2.5X"

		self.active_zoom = zoom_name

		for name, button in getattr(self, "zoom_buttons", {}).items():
			selected = name == zoom_name
			button.setChecked(selected)
			self.style_selection_button(button, selected)

		if getattr(self, "active_gun", None) in self.gun_data:
			self.gun_data[self.active_gun]["zoom"] = zoom_name
			self._refresh_zoom_sensitivity_inputs()

			with self.gun_data_path.open("w", encoding="utf-8") as data_file:
				json.dump(
					{"guns": self.gun_data, "operators": self.operator_data},
					data_file,
					indent=2,
					ensure_ascii=False,
				)


	def configure_sensitivity_input(self, input_box):
		input_box.setRange(-1e100, 1e100)
		input_box.setDecimals(15)
		input_box.setSingleStep(0.1)
		input_box.valueChanged.connect(
			lambda value, box=input_box: self.save_gun_sensitivity(
				"horizontal_sens" if box is self.horizontal_sens_input else "vertical_sens",
				value,
			)
		)

	def style_selection_button(self, button, selected):
		if self.dark_mode_enabled:
			color = "#8A2BE2" if selected else "#202022"
			text_color = "#ffffff"
			border_color = "#8A2BE2" if selected else "#56565c"
		else:
			color = "#8A2BE2" if selected else "#f7f7f9"
			text_color = "#ffffff" if selected else "#17171a"
			border_color = "#d9d9df"
		button.setStyleSheet(
			f"background-color: {color}; color: {text_color}; border: 1px solid {border_color}; border-radius: 8px;"
		)

	def save_gun_sensitivity(self, field, value):
		"""Save one sensitivity and synchronize both zoom representations."""
		if not getattr(self, "active_gun", None):
			return

		gun_data = self.gun_data.setdefault(self.active_gun, {})
		canonical_value = float(value)
		if getattr(self, "active_zoom", "1.0X") == "2.5X":
			canonical_value /= self.get_zoom_multiplier()
		base_field = f"{field}_1x"
		zoom_field = f"{field}_2_5x"
		gun_data[base_field] = canonical_value
		gun_data[zoom_field] = canonical_value * self.get_zoom_multiplier()

		with self.gun_data_path.open("w", encoding="utf-8") as data_file:
			json.dump(
				{"guns": self.gun_data, "operators": self.operator_data},
				data_file,
				indent=2,
				ensure_ascii=False,
			)


	def clean_operator_loadouts(self):
		allowed_secondary_guns = {
			"smg-11",
			"smg-12",
			"reaper mk2",
			"bearing 9",
			"c75 auto",
			".44 vendetta",
			"spsmg9",
		}
		excluded_shotguns = {
			"m590a1",
			"m1014",
			"sg-cqb",
			"sasg-12",
			"m870",
			"super 90",
			"spas-12",
			"spas-15",
			"supernova",
			"ita12l",
			"six12",
			"fo-12",
			"bosg.12.2",
			"acs12",
			"tcsg12",
			"six12 sd",
		}
		excluded_dmrs = {
			"417",
			"ots-03",
			"camrs",
			"sr-25",
			"mk 14 ebr",
			"ar-15.50",
			"csrx 300",
			"pmr90a2",
		}
		changed = False
		for operator_data in self.operator_data.values():
			for field in ("unique_gadget", "secondary_gadgets"):
				if field in operator_data:
					del operator_data[field]
					changed = True
			secondary_guns = operator_data.get("secondary_guns", [])
			filtered_guns = [
				gun for gun in secondary_guns
				if gun.lower() in allowed_secondary_guns
			]
			if filtered_guns != secondary_guns:
				operator_data["secondary_guns"] = filtered_guns
				changed = True
			# Remove excluded shotguns and DMRs from primary guns
			primary_guns = operator_data.get("primary_guns", [])
			filtered_primary = [
				gun for gun in primary_guns
				if gun.lower() not in excluded_shotguns
				and gun.lower() not in excluded_dmrs
			]
			if filtered_primary != primary_guns:
				operator_data["primary_guns"] = filtered_primary
				changed = True
		if changed:
			with self.gun_data_path.open("w", encoding="utf-8") as data_file:
				json.dump(
					{"guns": self.gun_data, "operators": self.operator_data},
					data_file,
					indent=2,
					ensure_ascii=False,
				)

	def update_toggle_button(self, enabled):
		if not hasattr(self, "recoil_status_label"):
			return
		base = (
			"font-weight: 700; font-size: 11pt; letter-spacing: 0.5px; "
			"background: transparent; border: none; padding: 0px; margin: 0px;"
		)
		if enabled:
			self.update_recoil_overlay(True)
			self.recoil_status_label.setText("ENABLED")
			status_color = "#ffffff" if self.dark_mode_enabled else "#8A2BE2"
			self.recoil_status_label.setStyleSheet(base + f" color: {status_color};")
			self._start_pulse()
		else:
			self.update_recoil_overlay(False)
			self._stop_pulse()
			self.recoil_status_label.setText("DISABLED")
			status_color = "#ffffff" if self.dark_mode_enabled else "#707078"
			self.recoil_status_label.setStyleSheet(base + f" color: {status_color};")
			self._set_dot_color(QColor("#ffffff" if self.dark_mode_enabled else "#000000"))

	def _set_dot_color(self, color: QColor):
		if not hasattr(self, "recoil_status_dot"):
			return
		r = max(1, self.recoil_status_dot.width() // 2)
		self.recoil_status_dot.setStyleSheet(
			f"background-color: {color.name()}; border: none; border-radius: {r}px;"
		)

	def _on_pulse_color(self, value):
		if isinstance(value, QColor):
			self._set_dot_color(value)

	def _start_pulse(self):
		self._pulse_anim.stop()
		self._pulse_going_dark = True
		pulse_color = QColor("#ffffff" if self.dark_mode_enabled else "#8A2BE2")
		pulse_dark_color = QColor("#3e3e42" if self.dark_mode_enabled else "#1a1a1a")
		self._set_dot_color(pulse_color)
		self._pulse_anim.setStartValue(pulse_color)
		self._pulse_anim.setEndValue(pulse_dark_color)
		self._pulse_anim.setDuration(1400)
		self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
		self._pulse_anim.start()

	def _on_pulse_finished(self):
		if not self.toggle_button.isChecked():
			return
		if self._pulse_going_dark:
			self._pulse_going_dark = False
			self._pulse_anim.setStartValue(QColor("#3e3e42" if self.dark_mode_enabled else "#1a1a1a"))
			self._pulse_anim.setEndValue(QColor("#ffffff" if self.dark_mode_enabled else "#8A2BE2"))
			self._pulse_anim.setDuration(700)
		else:
			self._pulse_going_dark = True
			self._pulse_anim.setStartValue(QColor("#ffffff" if self.dark_mode_enabled else "#8A2BE2"))
			self._pulse_anim.setEndValue(QColor("#3e3e42" if self.dark_mode_enabled else "#1a1a1a"))
			self._pulse_anim.setDuration(1400)
		self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
		self._pulse_anim.start()

	def _stop_pulse(self):
		self._pulse_anim.stop()

	def auto_shoot_on(self):
		"""F3 (global) – enable auto-shoot on supported DMRs."""
		if getattr(self, "active_gun", "") in self.extra_switch_guns:
			self._set_auto_shoot(True)

	def auto_shoot_off(self):
		"""F4 (global) – disable auto-shoot."""
		self._set_auto_shoot(False)

	def softaim_on(self):
		"""Enable Softaim."""
		self.softaim_button.setChecked(True)

	def softaim_off(self):
		"""Disable Softaim."""
		self.softaim_button.setChecked(False)

	def toggle_recoil(self):
		"""Toggle recoil from the global F1 hotkey."""
		self.toggle_button.setChecked(not self.toggle_button.isChecked())

	def toggle_softaim_hotkey(self):
		"""Toggle softaim from the global F2 hotkey."""
		self.softaim_button.setChecked(not self.softaim_button.isChecked())

set_high_process_priority()
app.setWindowIcon(QIcon(str(Path(__file__).parent / "icons" / "favicon" / "steam.webp")))
app.setStyleSheet(LIGHT_STYLE)
window = ScriptsWindow()
window.show()

profile_seconds = float(os.environ.get("R6_PROFILE_SECONDS", "0"))
if profile_seconds > 0:
	def finish_profile():
		print(json.dumps(window.softaim_worker.get_performance_stats(), default=str), flush=True)
		app.quit()

	QTimer.singleShot(int(profile_seconds * 1000), finish_profile)

sys.exit(app.exec())