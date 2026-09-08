"""Background R6 operator detection for the existing application UI."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

import mss
import numpy as np
import torch
import cv2
from ultralytics import YOLO

try:
    import dxcam
except ImportError:
    dxcam = None


CONFIDENCE_THRESHOLD = 0.80
DETECTION_RATE = 120
FRAME_TIME = 1 / DETECTION_RATE
MODEL_PATH = Path(r"C:\scripts\runs\detect\train-9\weights\best.pt")
NO_CLASS_NAME = "no"
FOV_DEGREES = 10.0
DXCAM_CAPTURE_FPS = 60
INFERENCE_SIZE = (640, 360)


def _within_fov(
    box: tuple[int, int, int, int],
    frame_shape: tuple[int, ...],
    fov_degrees: float,
) -> bool:
    """Check a box center against a circular angular cone at frame center."""
    frame_height, frame_width = frame_shape[:2]
    center_x = (box[0] + box[2]) / 2
    center_y = (box[1] + box[3]) / 2
    delta_x = center_x - frame_width / 2
    delta_y = center_y - frame_height / 2
    focal_length = min(frame_width, frame_height) / 2
    angular_offset = math.degrees(
        math.atan2(math.hypot(delta_x, delta_y), focal_length)
    )
    return angular_offset <= fov_degrees


def _class_name(names, class_id: int) -> str:
    if isinstance(names, dict):
        return str(names.get(class_id, ""))
    if 0 <= class_id < len(names):
        return str(names[class_id])
    return ""


def detect_target(
    frame: np.ndarray,
    model: YOLO,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    device: str | None = None,
    fov_degrees: float = FOV_DEGREES,
    source_shape: tuple[int, ...] | None = None,
    imgsz: int | tuple[int, int] | None = None,
) -> dict[str, object]:
    """Resolve Ally, Enemy, and Head from one YOLO inference result."""
    trace: dict[str, float] = {}
    if device is not None and device.startswith("cuda"):
        sync_started = time.perf_counter()
        torch.cuda.synchronize()
        trace["gpu_sync_before_ms"] = (time.perf_counter() - sync_started) * 1000
    inference_started = time.perf_counter()
    trace["yolo_call_started_at"] = inference_started
    inference_options = {"verbose": False, "device": device}
    if imgsz is not None:
        inference_options["imgsz"] = imgsz
        inference_options["rect"] = True
    result = model(frame, **inference_options)[0]
    yolo_call_returned = time.perf_counter()
    trace["yolo_call_returned_at"] = yolo_call_returned
    if device is not None and device.startswith("cuda"):
        sync_started = time.perf_counter()
        torch.cuda.synchronize()
        trace["gpu_sync_after_ms"] = (time.perf_counter() - sync_started) * 1000
    model_wall_ms = (time.perf_counter() - inference_started) * 1000
    model_speed = getattr(result, "speed", {}) or {}
    postprocess_started = time.perf_counter()
    trace["python_detection_started_at"] = postprocess_started
    source_height, source_width = (source_shape or frame.shape)[:2]
    scale_x = source_width / frame.shape[1]
    scale_y = source_height / frame.shape[0]
    detections: list[dict[str, object]] = []
    best_team = ""
    best_team_confidence = 0.0
    best_team_box: tuple[int, int, int, int] | None = None
    best_head_confidence = 0.0
    best_head_box: tuple[int, int, int, int] | None = None
    head_candidates: list[tuple[float, tuple[int, int, int, int]]] = []

    # Classification results have one class and no coordinates.
    probabilities = getattr(result, "probs", None)
    if probabilities is not None:
        class_id = int(probabilities.top1)
        class_name = _class_name(result.names, class_id).casefold()
        confidence = float(probabilities.top1conf)
        if class_name in {"ally", "enemy"}:
            best_team = class_name
            best_team_confidence = confidence

    # Keep every qualifying Ally, Enemy, and Head box for the overlay.
    boxes = getattr(result, "boxes", None)
    if boxes is not None and len(boxes) > 0:
        for index, (class_id, confidence) in enumerate(
            zip(boxes.cls.tolist(), boxes.conf.tolist())
        ):
            class_name = _class_name(result.names, int(class_id)).casefold()
            confidence = float(confidence)
            coordinates = boxes.xyxy[index].tolist()
            box = (
                int(round(coordinates[0] * scale_x)),
                int(round(coordinates[1] * scale_y)),
                int(round(coordinates[2] * scale_x)),
                int(round(coordinates[3] * scale_y)),
            )
            if class_name not in {"ally", "enemy", "head"}:
                continue
            if confidence < confidence_threshold:
                continue
            detections.append(
                {
                    "left": box[0],
                    "top": box[1],
                    "right": box[2],
                    "bottom": box[3],
                    "class_name": class_name,
                    "confidence": confidence,
                    "box": box,
                }
            )

    filtered_detections = [
        detection
        for detection in detections
        if _within_fov(detection["box"], (source_height, source_width), fov_degrees)
    ]
    detections = filtered_detections
    for detection in detections:
        class_name = str(detection["class_name"])
        confidence = float(detection["confidence"])
        box = detection["box"]
        if class_name in {"ally", "enemy"} and confidence > best_team_confidence:
            best_team = class_name
            best_team_confidence = confidence
            best_team_box = box
        elif class_name == "head":
            head_candidates.append((confidence, box))
    for detection in detections:
        detection.pop("box", None)

    if best_team_box is not None and head_candidates:
        left, top, right, bottom = best_team_box
        associated_heads = [
            (confidence, head_box)
            for confidence, head_box in head_candidates
            if left <= (head_box[0] + head_box[2]) / 2 <= right
            and top <= (head_box[1] + head_box[3]) / 2 <= bottom
        ]
        if associated_heads:
            best_head_confidence, best_head_box = max(
                associated_heads, key=lambda item: item[0]
            )

    found = bool(best_team) and best_team_confidence >= confidence_threshold
    timing = {
        "preprocess_ms": float(model_speed.get("preprocess", 0.0)),
        "inference_ms": float(model_speed.get("inference", model_wall_ms)),
        "model_postprocess_ms": float(model_speed.get("postprocess", 0.0)),
        "model_wall_ms": model_wall_ms,
        "postprocess_ms": (time.perf_counter() - postprocess_started) * 1000,
        "yolo_call_ms": (yolo_call_returned - inference_started) * 1000,
        "gpu_sync_before_ms": trace.get("gpu_sync_before_ms", 0.0),
        "gpu_sync_after_ms": trace.get("gpu_sync_after_ms", 0.0),
        "python_detection_ms": (time.perf_counter() - postprocess_started) * 1000,
    }
    trace["python_detection_finished_at"] = time.perf_counter()
    trace["inference_finished_at"] = trace["python_detection_finished_at"]
    return {
        "found": found,
        "team": best_team.upper() if found else "",
        "operator": best_team.upper() if found else "NO",
        "confidence": best_team_confidence if found else 0.0,
        "box": best_team_box if found else None,
        "head_box": best_head_box if best_head_confidence >= confidence_threshold else None,
        "head_confidence": best_head_confidence,
        "detections": detections,
        "fov_degrees": fov_degrees,
        "_timing": timing,
        "_profile": trace,
    }


class ScreenCaptureWorker(threading.Thread):
    """Capture the primary display and run operator inference off the UI thread."""

    def __init__(
        self,
        model_path: Path = MODEL_PATH,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        detection_rate: float = DETECTION_RATE,
        monitor_index: int = 1,
        fov_degrees: float = FOV_DEGREES,
        inference_size: tuple[int, int] | None = INFERENCE_SIZE,
    ) -> None:
        super().__init__(name="operator-detection", daemon=True)
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.frame_time = 1 / detection_rate
        self.monitor_index = monitor_index
        self.fov_degrees = float(fov_degrees)
        self.inference_size = inference_size
        self._enabled = threading.Event()
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._frame_ready = threading.Event()
        self._latest_frame: tuple[np.ndarray, float, float, tuple[int, int]] | None = None
        self._latest_result: dict[str, object] = {
            "found": False,
            "operator": "",
            "confidence": 0.0,
        }
        self._model: YOLO | None = None
        self.model_error = ""
        self.capture_backend = "uninitialized"
        self.capture_backend_error = ""
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self._metrics_lock = threading.Lock()
        self._metrics_started = time.perf_counter()
        self._last_inference_start_at: float | None = None
        self._metrics = {
            "captured_frames": 0,
            "inference_frames": 0,
            "discarded_frames": 0,
            "render_updates": 0,
            "capture_ms": 0.0,
            "capture_grab_ms": 0.0,
            "capture_convert_ms": 0.0,
            "resize_ms": 0.0,
            "frame_wait_ms": 0.0,
            "capture_to_buffer_ms": 0.0,
            "buffer_to_retrieve_ms": 0.0,
            "capture_to_retrieve_ms": 0.0,
            "preprocess_ms": 0.0,
            "inference_ms": 0.0,
            "model_postprocess_ms": 0.0,
            "postprocess_ms": 0.0,
            "model_wall_ms": 0.0,
            "yolo_call_ms": 0.0,
            "gpu_sync_before_ms": 0.0,
            "gpu_sync_after_ms": 0.0,
            "python_detection_ms": 0.0,
            "pipeline_latency_ms": 0.0,
            "inference_update_ms": 0.0,
            "next_inference_start_ms": 0.0,
            "result_buffer_ms": 0.0,
            "ui_receive_ms": 0.0,
            "render_ms": 0.0,
            "last_inference_at": None,
            "input_width": 0,
            "input_height": 0,
            "inference_width": 0,
            "inference_height": 0,
        }

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()

    def set_monitor(self, monitor_index: int) -> None:
        with self._lock:
            self.monitor_index = monitor_index

    def set_fov_degrees(self, fov_degrees: float) -> None:
        with self._lock:
            self.fov_degrees = float(fov_degrees)

    def get_latest_result(self) -> dict[str, object]:
        with self._lock:
            return self._latest_result.copy()

    def get_performance_stats(self) -> dict[str, object]:
        with self._metrics_lock:
            metrics = self._metrics.copy()
            elapsed = max(time.perf_counter() - self._metrics_started, 0.001)
        captured_frames = int(metrics["captured_frames"])
        inference_frames = int(metrics["inference_frames"])
        for key in (
            "capture_ms",
            "capture_grab_ms",
            "capture_convert_ms",
            "resize_ms",
            "frame_wait_ms",
            "capture_to_buffer_ms",
            "buffer_to_retrieve_ms",
            "capture_to_retrieve_ms",
            "preprocess_ms",
            "inference_ms",
            "model_postprocess_ms",
            "postprocess_ms",
            "model_wall_ms",
            "yolo_call_ms",
            "gpu_sync_before_ms",
            "gpu_sync_after_ms",
            "python_detection_ms",
            "pipeline_latency_ms",
            "inference_update_ms",
            "next_inference_start_ms",
            "result_buffer_ms",
            "ui_receive_ms",
            "render_ms",
        ):
            count = captured_frames if key in {
                "capture_ms",
                "capture_grab_ms",
                "capture_convert_ms",
                "capture_to_buffer_ms",
            } else inference_frames
            if key == "render_ms":
                count = int(metrics["render_updates"])
            if key == "ui_receive_ms":
                count = int(metrics["render_updates"])
            metrics[key] = metrics[key] / max(count, 1)
        metrics.update(
            {
                "capture_fps": captured_frames / elapsed,
                "inference_fps": inference_frames / elapsed,
                "device": self.device,
                "stale_frames_discarded": int(metrics["discarded_frames"]),
                "confidence_threshold": self.confidence_threshold,
                "fov_degrees": self.fov_degrees,
                "capture_backend": self.capture_backend,
                "capture_backend_error": self.capture_backend_error,
                "inference_size": self.inference_size,
            }
        )
        return metrics

    def record_render_time(self, render_ms: float) -> None:
        with self._metrics_lock:
            self._metrics["render_updates"] += 1
            self._metrics["render_ms"] += render_ms

    def record_ui_receive(self, result: dict[str, object]) -> None:
        received_at = time.perf_counter()
        profile = result.get("_profile", {})
        result_placed_at = profile.get("result_placed_at")
        if result_placed_at is not None:
            with self._metrics_lock:
                self._metrics["ui_receive_ms"] += (
                    received_at - result_placed_at
                ) * 1000

    def stop(self) -> None:
        self._stopped.set()
        self._enabled.set()
        self._frame_ready.set()

    def _set_latest_result(self, result: dict[str, object]) -> None:
        profile = result.get("_profile")
        with self._lock:
            self._latest_result = result
            result_placed_at = time.perf_counter()
        if isinstance(profile, dict):
            profile["result_placed_at"] = result_placed_at

    def _publish_frame(
        self,
        frame: np.ndarray,
        capture_started: float,
        grab_finished: float,
        captured_at: float,
    ) -> None:
        with self._lock:
            if self._latest_frame is not None:
                with self._metrics_lock:
                    self._metrics["discarded_frames"] += 1
            self._latest_frame = (
                frame,
                captured_at,
                time.perf_counter(),
                (frame.shape[1], frame.shape[0]),
            )
            placed_at = self._latest_frame[2]
        with self._metrics_lock:
            self._metrics["captured_frames"] += 1
            self._metrics["capture_ms"] += (captured_at - capture_started) * 1000
            self._metrics["capture_grab_ms"] += (grab_finished - capture_started) * 1000
            self._metrics["capture_convert_ms"] += (captured_at - grab_finished) * 1000
            self._metrics["capture_to_buffer_ms"] += (placed_at - captured_at) * 1000
            self._metrics["input_width"] = frame.shape[1]
            self._metrics["input_height"] = frame.shape[0]
        self._frame_ready.set()

    def _capture_loop_mss(self, screen) -> None:
        while not self._stopped.is_set():
            if not self._enabled.wait(timeout=0.1):
                continue
            with self._lock:
                monitor_index = self.monitor_index
            monitor = screen.monitors[
                max(1, min(monitor_index, len(screen.monitors) - 1))
            ]
            capture_started = time.perf_counter()
            screenshot = screen.grab(monitor)
            grab_finished = time.perf_counter()
            frame = np.asarray(screenshot)
            captured_at = time.perf_counter()
            self._publish_frame(frame, capture_started, grab_finished, captured_at)

    def _capture_loop_dxcam(self, camera) -> None:
        while not self._stopped.is_set():
            if not self._enabled.wait(timeout=0.1):
                continue
            capture_started = time.perf_counter()
            raw_frame = camera.get_latest_frame()
            grab_finished = time.perf_counter()
            if raw_frame is None:
                continue
            frame = np.asarray(raw_frame)
            captured_at = time.perf_counter()
            self._publish_frame(frame, capture_started, grab_finished, captured_at)

    def _take_latest_frame(self):
        with self._lock:
            frame_data = self._latest_frame
            self._latest_frame = None
            self._frame_ready.clear()
            if self._latest_frame is not None:
                self._frame_ready.set()
        return frame_data

    def run(self) -> None:
        try:
            self._model = YOLO(str(self.model_path))
            self._model.to(self.device)
        except Exception as error:
            self.model_error = str(error)

        if self._model is None:
            self._set_latest_result(
                {"found": False, "operator": "", "confidence": 0.0, "error": self.model_error}
            )

        if self._model is None:
            return

        capture_thread = None
        camera = None
        screen = None
        try:
            if dxcam is None:
                raise RuntimeError("dxcam is not installed")
            with self._lock:
                output_index = max(0, self.monitor_index - 1)
            camera = dxcam.create(output_idx=output_index, output_color="BGRA")
            camera.start(target_fps=DXCAM_CAPTURE_FPS, video_mode=True)
            self.capture_backend = "dxcam"
            capture_thread = threading.Thread(
                target=self._capture_loop_dxcam,
                args=(camera,),
                name="screen-capture-dxcam",
                daemon=True,
            )
        except Exception as error:
            self.capture_backend = "mss"
            self.capture_backend_error = str(error)
            screen = mss.mss()
            capture_thread = threading.Thread(
                target=self._capture_loop_mss,
                args=(screen,),
                name="screen-capture-mss",
                daemon=True,
            )
        capture_thread.start()
        try:
            while not self._stopped.is_set():
                wait_started = time.perf_counter()
                self._frame_ready.wait(timeout=0.1)
                if self._stopped.is_set():
                    break
                frame_data = self._take_latest_frame()
                if frame_data is None:
                    continue
                frame_wait_ms = (time.perf_counter() - wait_started) * 1000
                frame, captured_at, placed_at, _ = frame_data
                retrieved_at = time.perf_counter()
                with self._lock:
                    fov_degrees = self.fov_degrees
                    inference_size = self.inference_size
                resize_started = time.perf_counter()
                if inference_size is None or (
                    frame.shape[1], frame.shape[0]
                ) == inference_size:
                    inference_frame = frame
                else:
                    inference_frame = cv2.resize(
                        frame, inference_size, interpolation=cv2.INTER_AREA
                    )
                resize_finished = time.perf_counter()
                inference_started = time.perf_counter()
                result = detect_target(
                    inference_frame,
                    self._model,
                    self.confidence_threshold,
                    self.device,
                    fov_degrees,
                    frame.shape,
                    None
                    if inference_size is None
                    else (
                        math.ceil(inference_size[1] / 32) * 32,
                        inference_size[0],
                    ),
                )
                inference_finished = time.perf_counter()
                timing = result.pop("_timing", {})
                with self._metrics_lock:
                    self._metrics["inference_frames"] += 1
                    self._metrics["resize_ms"] += (
                        resize_finished - resize_started
                    ) * 1000
                    self._metrics["inference_width"] = inference_frame.shape[1]
                    self._metrics["inference_height"] = inference_frame.shape[0]
                    self._metrics["frame_wait_ms"] += frame_wait_ms
                    self._metrics["buffer_to_retrieve_ms"] += (
                        retrieved_at - placed_at
                    ) * 1000
                    self._metrics["capture_to_retrieve_ms"] += (
                        retrieved_at - captured_at
                    ) * 1000
                    for key in (
                        "preprocess_ms",
                        "inference_ms",
                        "model_postprocess_ms",
                        "postprocess_ms",
                        "model_wall_ms",
                        "yolo_call_ms",
                        "gpu_sync_before_ms",
                        "gpu_sync_after_ms",
                        "python_detection_ms",
                    ):
                        self._metrics[key] += timing.get(key, 0.0)
                    self._metrics["pipeline_latency_ms"] += (
                        inference_finished - captured_at
                    ) * 1000
                    profile = result.get("_profile", {})
                    if self._last_inference_start_at is not None:
                        self._metrics["next_inference_start_ms"] += (
                            inference_started - self._last_inference_start_at
                        ) * 1000
                    self._last_inference_start_at = inference_started
                    last_inference_at = self._metrics["last_inference_at"]
                    if last_inference_at is not None:
                        self._metrics["inference_update_ms"] += (
                            inference_finished - last_inference_at
                        ) * 1000
                    self._metrics["last_inference_at"] = inference_finished
                self._set_latest_result(result)
                profile = result.get("_profile", {})
                if isinstance(profile, dict):
                    with self._metrics_lock:
                        self._metrics["result_buffer_ms"] += (
                            profile["result_placed_at"] - inference_finished
                        ) * 1000
        finally:
            self._stopped.set()
            capture_thread.join(timeout=1)
            if camera is not None:
                camera.stop()
            if screen is not None:
                screen.close()
