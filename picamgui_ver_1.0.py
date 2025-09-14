#!/usr/bin/env python3
# Single-file Raspberry Pi camera GUI using Picamera2 + PyQt5.
# Features: preview, capture JPEG/RAW, start/stop mp4 recording,
# crop, focus controls, zoomed magnifier, rotate preview.

import sys
import os
import subprocess
import time
from functools import partial

from PyQt5 import QtCore, QtGui, QtWidgets
import numpy as np
from PIL import Image, ImageDraw

try:
    from picamera2 import Picamera2
    from libcamera import controls
    from picamera2.encoders import H264Encoder, Quality
except Exception as e:
    Picamera2 = None
    controls = None
    H264Encoder = None
    Quality = None
    print("Warning: picamera2 or libcamera.controls not available:", e)


class CameraGUI(QtWidgets.QMainWindow):
    """Main application window for the camera GUI."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Raspberry Pi Camera GUI - Version Epsilon")
        self.resize(1200, 800)

        self.picam = None
        self.preview_timer = None
        self.is_preview_paused = False
        self.current_frame = None
        self.is_recording = False
        
        # Crop variables
        self.temp_drawn_rect = None
        self.applied_crop_rect = None

        # Magnifier variables
        self.mag_rect = QtCore.QRect(10, 10, 150, 150)
        self.is_mag_dragging = False
        self.drag_offset = None
        
        self.rotation = 0
        self.is_dragging = False
        self.drag_start = None
        
        self.blink_timer = QtCore.QTimer()
        self.blink_timer.timeout.connect(self.toggle_blinking_indicator)

        # Corrected preview resolutions list to fix the unpacking error.
        self.preview_resolutions = [
            (640, 480),
            (1280, 720),
            (1920, 1080)
        ]
        self.capture_resolutions = [(1920, 1080), (4608, 2592), (4608, 3456)]
        self.capture_formats = ["jpeg", "png", "tiff", "dng"]
        self.current_preview_resolution = self.preview_resolutions[1]

        self.setup_ui()
        self.init_camera()
        self.start_preview()
        
        # Set default theme to dark
        self.apply_theme("dark")

    def setup_ui(self):
        """Initializes the user interface elements and layout."""
        # Main menu bar for theming
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QHBoxLayout(central)

        # Left side - Preview area
        left_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(left_layout, 3)

        # Main preview label
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setFixedSize(800, 600)
        self.preview_label.setStyleSheet("background: black; border: 2px solid #333;")
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setText("Initializing camera...")
        left_layout.addWidget(self.preview_label)
        
        # --- UI elements overlayed on the preview label ---
        self.record_indicator = QtWidgets.QLabel(self.preview_label)
        self.record_indicator.setFixedSize(20, 20)
        self.record_indicator.setStyleSheet(
            "background-color: red; border-radius: 10px; border: 1px solid #fff;"
        )
        self.record_indicator.move(10, 10)
        self.record_indicator.setVisible(False)
        self.record_indicator.raise_()

        self.pause_btn = QtWidgets.QPushButton("Pause Preview", self.preview_label)
        self.pause_btn.setStyleSheet("background-color: rgba(255, 255, 255, 0.5); border: 1px solid #fff;")
        self.pause_btn.setFixedSize(140, 30)
        self.pause_btn.move(10, 10)
        self.pause_btn.clicked.connect(self.toggle_preview)

        # New 'capturing' message overlay
        self.capture_overlay = QtWidgets.QLabel(self.preview_label)
        self.capture_overlay.setText("📸 Capturing Picture...")
        self.capture_overlay.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.7); color: white; "
            "font-size: 24px; padding: 10px; border-radius: 5px;"
        )
        self.capture_overlay.setAlignment(QtCore.Qt.AlignCenter)
        self.capture_overlay.setFixedSize(300, 50)
        self.capture_overlay.setVisible(False)
        self.capture_overlay.move(
            (self.preview_label.width() - self.capture_overlay.width()) // 2,
            (self.preview_label.height() - self.capture_overlay.height()) // 2
        )
        self.capture_overlay.raise_()

        self.mag_label = QtWidgets.QLabel(self.preview_label)
        self.mag_label.setFixedSize(200, 200)
        self.mag_label.setStyleSheet("background: #111; border: 1px solid #444;")
        self.mag_label.setAlignment(QtCore.Qt.AlignCenter)
        self.mag_label.setText("Magnifier")
        
        self.mag_label.move(self.preview_label.width() - self.mag_label.width() - 10, 10)
        self.mag_label.setVisible(False)
        self.pause_btn.raise_()

        mag_controls_layout = QtWidgets.QHBoxLayout()
        self.magnifier_toggle = QtWidgets.QCheckBox("Show Magnifier")
        self.magnifier_toggle.setChecked(False)
        self.magnifier_toggle.toggled.connect(self.toggle_magnifier)
        mag_controls_layout.addWidget(self.magnifier_toggle)
        mag_controls_layout.addStretch()
        left_layout.addLayout(mag_controls_layout)

        # Right side - Controls
        controls_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(controls_layout, 1)
        
        # Night mode button
        night_mode_layout = QtWidgets.QHBoxLayout()
        night_mode_layout.addStretch()
        self.night_mode_btn = QtWidgets.QPushButton("Night Mode")
        self.night_mode_btn.clicked.connect(self.toggle_night_mode)
        night_mode_layout.addWidget(self.night_mode_btn)
        controls_layout.addLayout(night_mode_layout)

        # Video Stream Resolution control
        controls_layout.addWidget(QtWidgets.QLabel("Video Stream Resolution:"))
        self.preview_res_combo = QtWidgets.QComboBox()
        self.preview_res_combo.addItem("640x480 ~60fps", (640, 480))
        self.preview_res_combo.addItem("1280x720 ~50fps", (1280, 720))
        self.preview_res_combo.addItem("1920x1080 ~30fps", (1920, 1080))
        self.preview_res_combo.setCurrentIndex(1)
        self.preview_res_combo.currentIndexChanged.connect(self.on_preview_resolution_change)
        controls_layout.addWidget(self.preview_res_combo)

        # Still Image Capture controls
        controls_layout.addWidget(QtWidgets.QLabel("Still Image Capture:"))
        capture_layout = QtWidgets.QHBoxLayout()
        self.capture_res_combo = QtWidgets.QComboBox()
        for i, (w, h) in enumerate(self.capture_resolutions):
            self.capture_res_combo.addItem(f"{w}x{h}", (w, h))
        self.capture_res_combo.setCurrentIndex(len(self.capture_resolutions) - 1) # Set default to highest resolution
        capture_layout.addWidget(self.capture_res_combo)

        self.capture_format_combo = QtWidgets.QComboBox()
        for fmt in self.capture_formats:
            self.capture_format_combo.addItem(fmt.upper(), fmt)
        self.capture_format_combo.setCurrentIndex(0)
        capture_layout.addWidget(self.capture_format_combo)
        
        self.capture_btn = QtWidgets.QPushButton("Capture")
        self.capture_btn.clicked.connect(self.capture_image)
        capture_layout.addWidget(self.capture_btn)

        controls_layout.addLayout(capture_layout)

        # Video recording buttons
        controls_layout.addWidget(QtWidgets.QLabel("Video Recording:"))
        self.start_record_btn = QtWidgets.QPushButton("Start Recording MP4")
        self.start_record_btn.clicked.connect(self.start_recording)
        controls_layout.addWidget(self.start_record_btn)
        
        self.stop_record_btn = QtWidgets.QPushButton("Stop Recording")
        self.stop_record_btn.clicked.connect(self.stop_recording)
        self.stop_record_btn.setEnabled(False)
        controls_layout.addWidget(self.stop_record_btn)

        # Crop controls
        controls_layout.addWidget(QtWidgets.QLabel("Crop Controls:"))
        
        # New, more compact crop layout
        compact_crop_layout = QtWidgets.QHBoxLayout()
        crop_info = QtWidgets.QLabel("Draw on preview to crop:")
        crop_info.setStyleSheet("font-size: 10px;")
        
        self.crop_apply_btn = QtWidgets.QPushButton("Apply")
        self.crop_apply_btn.clicked.connect(self.apply_crop_from_rect)
        self.crop_apply_btn.setEnabled(False)
        
        self.crop_clear_btn = QtWidgets.QPushButton("Clear")
        self.crop_clear_btn.clicked.connect(self.clear_crop)
        
        compact_crop_layout.addWidget(crop_info)
        compact_crop_layout.addWidget(self.crop_apply_btn)
        compact_crop_layout.addWidget(self.crop_clear_btn)
        
        controls_layout.addLayout(compact_crop_layout)

        # Focus controls (now inline)
        focus_layout = QtWidgets.QHBoxLayout()
        focus_layout.addWidget(QtWidgets.QLabel("Focus Mode:"))
        self.focus_combo = QtWidgets.QComboBox()
        self.focus_combo.addItem("Trigger Autofocus Mode", "auto")
        self.focus_combo.addItem("Continuous", "continuous")
        self.focus_combo.addItem("Manual", "manual")
        self.focus_combo.setCurrentIndex(1)
        self.focus_combo.currentIndexChanged.connect(self.set_focus_mode)
        focus_layout.addWidget(self.focus_combo)
        controls_layout.addLayout(focus_layout)

        self.autofocus_btn = QtWidgets.QPushButton("Trigger Autofocus")
        self.autofocus_btn.clicked.connect(self.trigger_autofocus)
        self.autofocus_btn.setVisible(False)
        controls_layout.addWidget(self.autofocus_btn)

        self.manual_focus_layout = QtWidgets.QVBoxLayout()
        self.manual_focus_label = QtWidgets.QLabel("Manual Focus:")
        self.lens_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.lens_slider.setRange(0, 1000)
        self.lens_slider.setValue(500)
        self.lens_slider.valueChanged.connect(self.set_lens_position)
        self.lens_value_label = QtWidgets.QLabel("0.0 mm")
        self.lens_value_label.setAlignment(QtCore.Qt.AlignRight)
        
        self.manual_focus_layout.addWidget(self.manual_focus_label)
        self.manual_focus_layout.addWidget(self.lens_slider)
        self.manual_focus_layout.addWidget(self.lens_value_label)
        
        self.manual_focus_layout.setAlignment(QtCore.Qt.AlignTop)
        self.manual_focus_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addLayout(self.manual_focus_layout)
        self.manual_focus_layout.itemAt(0).widget().setVisible(False)
        self.manual_focus_layout.itemAt(1).widget().setVisible(False)
        self.manual_focus_layout.itemAt(2).widget().setVisible(False)
        
        # New rotation buttons inline with text
        rot_layout = QtWidgets.QHBoxLayout()
        rot_layout.addWidget(QtWidgets.QLabel("Rotate Preview:"))
        
        rot_ccw_btn = QtWidgets.QPushButton("\u21ba") # Counter-clockwise arrow
        rot_ccw_btn.setFixedSize(30, 30)
        rot_ccw_btn.setStyleSheet("font-size: 16px;")
        rot_ccw_btn.clicked.connect(partial(self.set_rotation_relative, -90))
        rot_layout.addWidget(rot_ccw_btn)
        
        rot_cw_btn = QtWidgets.QPushButton("\u21bb") # Clockwise arrow
        rot_cw_btn.setFixedSize(30, 30)
        rot_cw_btn.setStyleSheet("font-size: 16px;")
        rot_cw_btn.clicked.connect(partial(self.set_rotation_relative, 90))
        rot_layout.addWidget(rot_cw_btn)
        
        controls_layout.addLayout(rot_layout)
        
        # Add a stretch to push controls to the top
        controls_layout.addStretch(1)

        # Status bar
        self.statusBar().showMessage("Ready")

        self.preview_label.mousePressEvent = self.preview_mouse_press
        self.preview_label.mouseMoveEvent = self.preview_mouse_move
        self.preview_label.mouseReleaseEvent = self.preview_mouse_release
        self.preview_label.setMouseTracking(True)
        
        # Center the magnifier box at startup
        self.center_magnifier_box()
    
    def apply_theme(self, theme_name):
        """Applies a theme stylesheet to the application."""
        if theme_name == "dark":
            stylesheet = """
                QMainWindow, QWidget, QComboBox, QSlider, QCheckBox, QLabel {
                    background-color: #2e2e2e;
                    color: #e0e0e0;
                }
                QMenuBar, QMenu {
                    background-color: #3e3e3e;
                    color: #e0e0e0;
                }
                QMenuBar::item:selected, QMenu::item:selected {
                    background-color: #555555;
                }
                QPushButton {
                    background-color: #4a4a4a;
                    border: 1px solid #555555;
                    border-radius: 4px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #555555;
                }
                QSlider::groove:horizontal {
                    border: 1px solid #999999;
                    height: 8px;
                    background: #5a5a5a;
                    margin: 2px 0;
                    border-radius: 4px;
                }
                QSlider::handle:horizontal {
                    background: #4a4a4a;
                    border: 1px solid #777777;
                    width: 18px;
                    margin: -5px 0;
                    border-radius: 3px;
                }
                QStatusBar {
                    background-color: #3e3e3e;
                    color: #e0e0e0;
                }
            """
            self.night_mode_btn.setText("Day Mode")
        else: # light theme
            stylesheet = "" # Use default system style
            self.night_mode_btn.setText("Night Mode")
            
        self.setStyleSheet(stylesheet)
        
    def toggle_night_mode(self):
        """Toggles between dark and light themes."""
        if self.night_mode_btn.text() == "Night Mode":
            self.apply_theme("dark")
        else:
            self.apply_theme("light")
    
    def center_magnifier_box(self):
        """Centers the magnifier rectangle on the preview label."""
        preview_width = self.preview_label.width()
        preview_height = self.preview_label.height()
        mag_width = self.mag_rect.width()
        mag_height = self.mag_rect.height()
        
        self.mag_rect.moveTo(
            (preview_width - mag_width) // 2,
            (preview_height - mag_height) // 2
        )

    def toggle_blinking_indicator(self):
        """Toggles the visibility of the red recording indicator."""
        self.record_indicator.setVisible(not self.record_indicator.isVisible())

    def init_camera(self):
        """Initialize the camera with the current preview settings"""
        if Picamera2 is None:
            QtWidgets.QMessageBox.critical(self, "Error", 
                "Picamera2 not available. Please install: pip install picamera2")
            return False

        try:
            if self.picam:
                try:
                    self.picam.stop()
                    self.picam.close()
                except Exception:
                    pass

            self.picam = Picamera2()
            
            preview_config = self.picam.create_preview_configuration(
                main={"size": self.current_preview_resolution},
                controls={"FrameRate": 60.0}
            )
            
            self.picam.configure(preview_config)
            self.picam.start()
            
            if controls is not None:
                self.picam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
            
            time.sleep(0.2)
            
            self.statusBar().showMessage(f"Camera initialized with preview stream at {self.current_preview_resolution[0]}x{self.current_preview_resolution[1]}")
            return True
            
        except Exception as e:
            error_msg = f"Failed to initialize camera: {str(e)}"
            print(error_msg)
            QtWidgets.QMessageBox.critical(self, "Camera Error", error_msg)
            self.statusBar().showMessage("Camera initialization failed")
            return False

    def start_preview(self):
        """Start the preview timer"""
        if self.preview_timer:
            self.preview_timer.stop()
            
        self.preview_timer = QtCore.QTimer()
        self.preview_timer.timeout.connect(self.update_preview)
        self.preview_timer.start(33)

    def toggle_preview(self):
        """Pauses or resumes the live preview"""
        if self.preview_timer.isActive():
            self.preview_timer.stop()
            self.is_preview_paused = True
            self.pause_btn.setText("Resume Preview")
            self.statusBar().showMessage("Preview Paused", 3000)
        else:
            self.start_preview()
            self.is_preview_paused = False
            self.pause_btn.setText("Pause Preview")
            self.statusBar().showMessage("Preview Resumed", 3000)

    def on_preview_resolution_change(self, index):
        """Handle resolution change for the video stream"""
        new_resolution = self.preview_res_combo.itemData(index)
        if new_resolution and new_resolution != self.current_preview_resolution:
            self.current_preview_resolution = new_resolution
            self.statusBar().showMessage("Changing video stream resolution...")
            
            if self.preview_timer:
                self.preview_timer.stop()
            
            if self.init_camera():
                if not self.is_preview_paused:
                    self.start_preview()
                self.clear_crop()
            else:
                for i in range(self.preview_res_combo.count()):
                    if self.preview_res_combo.itemData(i) == self.current_preview_resolution:
                        self.preview_res_combo.setCurrentIndex(i)
                        break

    def update_preview(self):
        """Update the preview display from the single main stream"""
        if not self.picam:
            return

        try:
            frame = self.picam.capture_array()

            if frame is None or frame.size == 0:
                return

            if frame.ndim == 3 and frame.shape[2] >= 3:
                img = frame[..., :3]
            elif frame.ndim == 2:
                img = np.stack([frame] * 3, axis=-1)
            else:
                return

            self.current_frame = img.copy()

            if self.rotation != 0:
                k = (self.rotation // 90) % 4
                img = np.rot90(img, k)
            
            # This is the corrected crop logic
            if self.applied_crop_rect:
                label_w, label_h = self.preview_label.width(), self.preview_label.height()
                sensor_w, sensor_h = self.current_preview_resolution
                
                scale_x = sensor_w / label_w
                scale_y = sensor_h / label_h

                x1_sensor = int(self.applied_crop_rect.left() * scale_x)
                y1_sensor = int(self.applied_crop_rect.top() * scale_y)
                x2_sensor = int(self.applied_crop_rect.right() * scale_x)
                y2_sensor = int(self.applied_crop_rect.bottom() * scale_y)

                x1_sensor = max(0, min(x1_sensor, sensor_w))
                y1_sensor = max(0, min(y1_sensor, sensor_h))
                x2_sensor = max(0, min(x2_sensor, sensor_w))
                y2_sensor = max(0, min(y2_sensor, sensor_h))
                
                # Slicing the numpy array for the cropped view
                img = self.current_frame[y1_sensor:y2_sensor, x1_sensor:x2_sensor, :]
                
            label_w = self.preview_label.width()
            label_h = self.preview_label.height()
            
            if img.size > 0:
                img_pil = Image.fromarray(img.astype(np.uint8))
                img_pil = img_pil.resize((label_w, label_h), Image.Resampling.LANCZOS)
            else:
                img_pil = Image.new('RGB', (label_w, label_h), 'black')


            draw_img = img_pil.copy()
            draw = ImageDraw.Draw(draw_img)
            
            if self.temp_drawn_rect:
                rect = self.temp_drawn_rect
                draw.rectangle(
                    [rect.left(), rect.top(), rect.right(), rect.bottom()],
                    outline="red", width=2
                )

            if self.magnifier_toggle.isChecked():
                # Draw the magnification rectangle on the main preview
                draw.rectangle(
                    [self.mag_rect.left(), self.mag_rect.top(), self.mag_rect.right(), self.mag_rect.bottom()],
                    outline="blue", width=2
                )
                self.update_magnifier()

            qimage = QtGui.QImage(
                draw_img.tobytes(),
                draw_img.width, draw_img.height,
                draw_img.width * 3,
                QtGui.QImage.Format_RGB888
            )
            pixmap = QtGui.QPixmap.fromImage(qimage)
            self.preview_label.setPixmap(pixmap)
            
        except Exception as e:
            print(f"Preview update error: {e}")

    def update_magnifier(self):
        """Update the magnifier view based on the mag_rect position."""
        if self.current_frame is None:
            return

        try:
            img = self.current_frame
            h, w = img.shape[:2]

            label_w, label_h = self.preview_label.width(), self.preview_label.height()
            
            scale_x = w / label_w
            scale_y = h / label_h

            x1_sensor = int(self.mag_rect.left() * scale_x)
            y1_sensor = int(self.mag_rect.top() * scale_y)
            x2_sensor = int(self.mag_rect.right() * scale_x)
            y2_sensor = int(self.mag_rect.bottom() * scale_y)

            x1_sensor = max(0, min(x1_sensor, w))
            y1_sensor = max(0, min(y1_sensor, h))
            x2_sensor = max(0, min(x2_sensor, w))
            y2_sensor = max(0, min(y2_sensor, h))
            
            crop = img[y1_sensor:y2_sensor, x1_sensor:x2_sensor, :]
            
            if crop.size > 0:
                mag_pil = Image.fromarray(crop.astype(np.uint8))
                mag_pil = mag_pil.resize(
                    (self.mag_label.width(), self.mag_label.height()),
                    Image.Resampling.NEAREST
                )

                qimg = QtGui.QImage(
                    mag_pil.tobytes(),
                    mag_pil.width, mag_pil.height,
                    mag_pil.width * 3,
                    QtGui.QImage.Format_RGB888
                )
                self.mag_label.setPixmap(QtGui.QPixmap.fromImage(qimg))
            else:
                self.mag_label.setText("No content")
                
        except Exception as e:
            print(f"Magnifier update error: {e}")

    def toggle_magnifier(self, checked):
        """Show or hide the magnifier display"""
        self.mag_label.setVisible(checked)
        if checked:
            self.center_magnifier_box()

    def capture_image(self):
        """General function for capturing images with a specified format and resolution."""
        if not self.picam:
            self.statusBar().showMessage("Camera not initialized", 3000)
            return
            
        # Get desired capture settings
        capture_res = self.capture_res_combo.currentData()
        capture_format = self.capture_format_combo.currentData()
        
        # Pause and update UI for capture
        was_preview_active = self.preview_timer.isActive()
        self.preview_timer.stop()
        self.picam.stop()
        self.preview_label.setText("Capturing...")
        self.capture_overlay.setVisible(True)
        self.statusBar().showMessage("Capturing picture...", 0)
        QtCore.QCoreApplication.processEvents()

        try:
            # Reconfigure for high-res capture
            capture_config = self.picam.create_still_configuration(
                main={"size": capture_res},
            )
            self.picam.configure(capture_config)
            self.picam.start()
            
            # Use a temporary file path
            temp_path = f"/tmp/temp_capture.{capture_format}"
            
            if capture_format == "dng":
                # For DNG, we use the raw stream
                capture_config = self.picam.create_still_configuration(
                    raw={"size": self.capture_resolutions[1]}, # Always capture native for DNG
                )
                self.picam.configure(capture_config)
                self.picam.start()
                self.picam.capture_file(temp_path, format="dng")
            else:
                self.picam.capture_file(temp_path, format=capture_format)

            self.statusBar().showMessage("Picture captured. Prompting to save...", 5000)

            # Prompt the user to save the captured image
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, f"Save {capture_format.upper()}",
                os.path.expanduser(f"~/capture.{capture_format}"),
                f"{capture_format.upper()} Files (*.{capture_format});;All Files (*)"
            )

            if filename:
                os.rename(temp_path, filename)
                self.statusBar().showMessage(f"{capture_format.upper()} saved: {os.path.basename(filename)}", 5000)
            else:
                self.statusBar().showMessage("Picture discarded.", 3000)
                os.remove(temp_path)

        except Exception as e:
            error_msg = f"Failed to capture {capture_format.upper()}: {str(e)}"
            print(error_msg)
            self.statusBar().showMessage(f"Capture error: {error_msg}", 5000)
        finally:
            # Always revert to preview mode and resume
            self.capture_overlay.setVisible(False)
            self.preview_label.setText("")
            self.init_camera()
            if was_preview_active:
                self.start_preview()
            else:
                self.pause_btn.setText("Resume Preview")

    def start_recording(self):
        """
        Stop the preview, configure the camera for video, and start recording.
        Saves to a temporary file. The final save prompt happens on stop.
        """
        if self.is_recording:
            return
            
        if not self.picam:
            self.statusBar().showMessage("Camera not initialized", 3000)
            return

        try:
            # First, stop the current preview to free up the camera
            if self.preview_timer:
                self.preview_timer.stop()
            self.picam.stop()
            
            # Update the UI to show a static message
            self.preview_label.setStyleSheet("background: black; color: white; border: 2px solid #333;")
            self.preview_label.setText("Recording Video...")
            QtCore.QCoreApplication.processEvents()

            # Create a dedicated video configuration
            video_config = self.picam.create_video_configuration()
            self.picam.configure(video_config)
            
            # Use a temporary file for the duration of the recording
            self.temp_video_path = "/tmp/temp_video.h264"
            encoder = H264Encoder()
            self.picam.start_recording(encoder, self.temp_video_path)

            self.is_recording = True
            self.start_record_btn.setEnabled(False)
            self.stop_record_btn.setEnabled(True)
            self.blink_timer.start(500) # Start blinking every 500ms
            self.record_indicator.setVisible(True)
            
            self.statusBar().showMessage("Recording...", 0)
        except Exception as e:
            error_msg = f"Failed to start recording: {str(e)}"
            print(error_msg)
            self.statusBar().showMessage(f"Recording error: {error_msg}", 5000)
            self.is_recording = False
            self.start_record_btn.setEnabled(True)
            self.stop_record_btn.setEnabled(False)
            self.record_indicator.setVisible(False)
            self.init_camera()
            self.start_preview()
            
    def stop_recording(self):
        """
        Stop video recording, prompt the user to save the file, then restart preview.
        """
        if not self.is_recording:
            return
            
        try:
            # Stop the blinking timer first
            self.blink_timer.stop()
            self.record_indicator.setVisible(False)
            
            # First, stop the recording to finalize the temporary file
            self.picam.stop_recording()
            self.is_recording = False
            self.start_record_btn.setEnabled(True)
            self.stop_record_btn.setEnabled(False)
            self.statusBar().showMessage("Recording stopped. Saving file...", 0)
            
            # Update the UI to show a static message
            self.preview_label.setStyleSheet("background: black; color: white; border: 2px solid #333;")
            self.preview_label.setText("Processing Video...")
            QtCore.QCoreApplication.processEvents()

            # Prompt the user to save the video
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save MP4 Video", os.path.expanduser("~/video.mp4"),
                "MP4 Files (*.mp4);;All Files (*)"
            )
            
            if filename:
                # Use libcamera-vid to convert the H264 stream to an MP4 container
                self.statusBar().showMessage("Converting to MP4, please wait...", 0)
                subprocess.run(
                    ["ffmpeg", "-i", self.temp_video_path, "-c", "copy", filename],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                self.statusBar().showMessage(f"MP4 saved to {os.path.basename(filename)}", 5000)
                os.remove(self.temp_video_path)
            else:
                self.statusBar().showMessage("Video not saved.", 3000)
                os.remove(self.temp_video_path)

        except Exception as e:
            error_msg = f"Failed to stop or save recording: {str(e)}"
            print(error_msg)
            self.statusBar().showMessage(f"Error saving video: {error_msg}", 5000)
        finally:
            # Reinitialize and start the preview again
            self.preview_label.setStyleSheet("background: black; border: 2px solid #333;")
            self.init_camera()
            self.start_preview()

    def preview_mouse_press(self, event):
        """Handle mouse press on preview, for both crop and magnifier."""
        if self.magnifier_toggle.isChecked() and self.mag_rect.contains(event.pos()):
            self.is_mag_dragging = True
            self.drag_offset = event.pos() - self.mag_rect.topLeft()
        elif event.button() == QtCore.Qt.LeftButton:
            self.drag_start = event.pos()
            self.is_dragging = True
            self.temp_drawn_rect = QtCore.QRect(self.drag_start, self.drag_start)
            self.crop_apply_btn.setEnabled(False)

    def preview_mouse_move(self, event):
        """Handle mouse move for dragging on preview."""
        if self.is_mag_dragging:
            self.mag_rect.moveTopLeft(event.pos() - self.drag_offset)
        elif self.is_dragging and self.drag_start:
            self.temp_drawn_rect = QtCore.QRect(self.drag_start, event.pos()).normalized()
            
            if self.temp_drawn_rect.width() > 10 and self.temp_drawn_rect.height() > 10:
                self.crop_apply_btn.setEnabled(True)
            else:
                self.crop_apply_btn.setEnabled(False)

    def preview_mouse_release(self, event):
        """Handle mouse release on preview."""
        self.is_mag_dragging = False
        if self.is_dragging:
            self.is_dragging = False
            if self.temp_drawn_rect and (self.temp_drawn_rect.width() < 10 or self.temp_drawn_rect.height() < 10):
                self.temp_drawn_rect = None
                self.crop_apply_btn.setEnabled(False)
                
    def apply_crop_from_rect(self):
        """
        Set the crop rectangle to the drawn rectangle's normalized coordinates.
        The actual cropping happens in update_preview.
        """
        if not self.temp_drawn_rect:
            return

        self.applied_crop_rect = self.temp_drawn_rect
        self.temp_drawn_rect = None
        self.statusBar().showMessage("Cropping applied", 3000)

    def clear_crop(self):
        """
        Clear the current crop by resetting the crop_rect.
        """
        self.applied_crop_rect = None
        self.temp_drawn_rect = None
        self.crop_apply_btn.setEnabled(False)
        self.statusBar().showMessage("Crop cleared. Full view restored.", 3000)

    def set_focus_mode(self, index):
        """Set the camera focus mode and manage button visibility"""
        if not self.picam or controls is None:
            return

        mode_data = self.focus_combo.itemData(index)
        mode_text = self.focus_combo.itemText(index)
        
        self.autofocus_btn.setVisible(False)
        self.manual_focus_layout.itemAt(0).widget().setVisible(False)
        self.manual_focus_layout.itemAt(1).widget().setVisible(False)
        self.manual_focus_layout.itemAt(2).widget().setVisible(False)

        try:
            if mode_data == "auto":
                self.picam.set_controls({"AfMode": controls.AfModeEnum.Auto})
                self.autofocus_btn.setVisible(True)
            elif mode_data == "continuous":
                self.picam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
            elif mode_data == "manual":
                metadata = self.picam.capture_metadata()
                lens_position = metadata.get("LensPosition", 0.0)
                if lens_position is not None:
                    slider_value = int(lens_position * 100)
                    self.lens_slider.setValue(slider_value)
                    self.set_lens_position(slider_value)
                
                self.picam.set_controls({"AfMode": controls.AfModeEnum.Manual})
                self.manual_focus_layout.itemAt(0).widget().setVisible(True)
                self.manual_focus_layout.itemAt(1).widget().setVisible(True)
                self.manual_focus_layout.itemAt(2).widget().setVisible(True)

            self.statusBar().showMessage(f"Focus mode: {mode_text}", 3000)
        except Exception as e:
            print(f"Focus mode error: {e}")
            self.statusBar().showMessage(f"Focus mode error: {e}", 3000)

    def trigger_autofocus(self):
        """Triggers a single, accurate autofocus shot."""
        if not self.picam or controls is None:
            self.statusBar().showMessage("Camera not initialized or controls not available.", 3000)
            return
        
        current_mode = self.focus_combo.itemData(self.focus_combo.currentIndex())
        if current_mode != "auto":
            self.statusBar().showMessage("Autofocus can only be triggered in 'Trigger Autofocus Mode'.", 3000)
            return

        try:
            self.picam.set_controls({"AfTrigger": controls.AfTriggerEnum.Start})
            self.statusBar().showMessage("Autofocus triggered.", 3000)
        except Exception as e:
            print(f"Autofocus trigger error: {e}")
            self.statusBar().showMessage(f"Autofocus trigger error: {e}", 3000)

    def set_lens_position(self, value):
        """Set manual lens position and update the display value"""
        if not self.picam or controls is None:
            return

        try:
            position = float(value) / 100.0
            self.picam.set_controls({"LensPosition": position})
            
            if position == 0.0:
                focus_distance_str = "$\infty$ mm"
            else:
                focus_distance = 1000.0 / position
                focus_distance_str = f"{focus_distance:.2f} mm"

            self.lens_value_label.setText(focus_distance_str)
        except Exception as e:
            print(f"Lens position error: {e}")

    def set_rotation_relative(self, angle_change):
        """Set preview rotation angle relative to current one"""
        self.rotation = (self.rotation + angle_change) % 360
        self.statusBar().showMessage(f"Rotation: {self.rotation}°", 3000)

    def closeEvent(self, event):
        """Handle application close"""
        if self.is_recording:
            try:
                self.picam.stop_recording()
                if os.path.exists("/tmp/temp_video.h264"):
                    os.remove("/tmp/temp_video.h264")
            except Exception as e:
                print(f"Error stopping recording on close: {e}")
        
        if self.preview_timer:
            self.preview_timer.stop()
            
        if self.blink_timer:
            self.blink_timer.stop()

        if self.picam:
            try:
                self.picam.stop()
                self.picam.close()
            except:
                pass

        event.accept()


def main():
    """Main application entry point"""
    app = QtWidgets.QApplication(sys.argv)
    
    app.setApplicationName("Raspberry Pi Camera GUI")
    app.setApplicationVersion("1.0.0")
    
    window = CameraGUI()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
