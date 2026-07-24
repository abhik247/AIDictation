import os
import time
import uuid
import tempfile
import threading
import struct
import shutil
import subprocess
from typing import Callable, Optional

# Try importing PyAudio if available
try:
    import pyaudio
    import wave
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

# Try importing GStreamer if PyAudio is missing
HAS_GST = False
if not HAS_PYAUDIO:
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst, GLib
        Gst.init(None)
        HAS_GST = True
    except Exception:
        HAS_GST = False


class AudioRecorder:
    def __init__(self):
        self.output_file_path: str = ""
        self.is_recording: bool = False
        self.is_paused: bool = False

        self._start_time: float = 0.0
        self._pause_started: Optional[float] = None
        self._paused_accumulated: float = 0.0

        self.audio_level_changed: Optional[Callable[[float], None]] = None
        self.recording_duration_changed: Optional[Callable[[float], None]] = None

        self._backend = "pyaudio" if HAS_PYAUDIO else ("gst" if HAS_GST else "subprocess")

        # PyAudio objects
        self._pyaudio = None
        self._stream = None
        self._wave_file = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # GStreamer objects
        self._pipeline = None

        # Subprocess objects
        self._proc = None

    def start_recording(self) -> None:
        if self.is_recording:
            return

        temp_dir = tempfile.gettempdir()
        self.output_file_path = os.path.join(temp_dir, f"recording_{uuid.uuid4().hex}.wav")

        self._paused_accumulated = 0.0
        self._pause_started = None
        self.is_paused = False
        self._start_time = time.time()
        self._stop_event.clear()

        if self._backend == "pyaudio" and HAS_PYAUDIO:
            self._start_pyaudio()
        elif self._backend == "gst" and HAS_GST:
            self._start_gst()
        else:
            self._start_subprocess()

        self.is_recording = True

    # --- Backend 1: PyAudio ---
    def _start_pyaudio(self) -> None:
        try:
            self._wave_file = wave.open(self.output_file_path, "wb")
            self._wave_file.setnchannels(1)
            self._wave_file.setsampwidth(2)
            self._wave_file.setframerate(16000)

            self._pyaudio = pyaudio.PyAudio()
            self._stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1024,
            )
        except Exception as e:
            self._cleanup_pyaudio()
            # Try GStreamer or subprocess fallback
            if HAS_GST:
                self._backend = "gst"
                self._start_gst()
                return
            else:
                self._backend = "subprocess"
                self._start_subprocess()
                return

        self._thread = threading.Thread(target=self._pyaudio_record_loop, daemon=True)
        self._thread.start()

    def _pyaudio_record_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                data = self._stream.read(1024, exception_on_overflow=False)
            except Exception:
                break

            if not data:
                continue

            if not self.is_paused and self._wave_file is not None:
                self._wave_file.writeframes(data)

            max_val = 0.0
            num_samples = len(data) // 2
            if num_samples > 0:
                fmt = f"<{num_samples}h"
                samples = struct.unpack(fmt, data)
                for s in samples:
                    val = abs(s) / 32768.0
                    if val > max_val:
                        max_val = val

            if self.audio_level_changed:
                self.audio_level_changed(max_val)

            self._update_duration()

    def _cleanup_pyaudio(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._pyaudio is not None:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None

        if self._wave_file is not None:
            try:
                self._wave_file.close()
            except Exception:
                pass
            self._wave_file = None

    # --- Backend 2: GStreamer ---
    def _start_gst(self) -> None:
        pipeline_str = (
            f"autoaudiosrc ! audioconvert ! audioresample ! "
            f"capsfilter caps=audio/x-raw,rate=16000,channels=1 ! "
            f"level interval=50000000 ! wavenc ! filesink location={self.output_file_path}"
        )
        try:
            self._pipeline = Gst.parse_launch(pipeline_str)
            self._pipeline.set_state(Gst.State.PLAYING)
        except Exception:
            self._backend = "subprocess"
            self._start_subprocess()
            return

        self._thread = threading.Thread(target=self._gst_bus_loop, daemon=True)
        self._thread.start()

    def _gst_bus_loop(self) -> None:
        if not self._pipeline:
            return
        bus = self._pipeline.get_bus()

        while not self._stop_event.is_set():
            msg = bus.pop_filtered(Gst.MessageType.ELEMENT | Gst.MessageType.ERROR)
            if msg:
                if msg.type == Gst.MessageType.ERROR:
                    break
                struct_obj = msg.get_structure()
                if struct_obj and struct_obj.get_name() == "level":
                    if not self.is_paused:
                        peaks = struct_obj.get_value("peak")
                        if peaks and isinstance(peaks, (list, tuple)):
                            db_val = peaks[0]
                            lin_val = min(1.0, max(0.0, (db_val + 60.0) / 60.0))
                            if self.audio_level_changed:
                                self.audio_level_changed(lin_val)

            self._update_duration()
            time.sleep(0.05)

    def _cleanup_gst(self) -> None:
        if self._pipeline:
            try:
                self._pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
            self._pipeline = None

    # --- Backend 3: Subprocess (arecord / pw-record / parec / ffmpeg) ---
    def _start_subprocess(self) -> None:
        arecord = shutil.which("arecord")
        pw_record = shutil.which("pw-record")
        parec = shutil.which("parec")
        ffmpeg = shutil.which("ffmpeg")

        if arecord:
            cmd = [arecord, "-f", "S16_LE", "-c", "1", "-r", "16000", self.output_file_path]
        elif pw_record:
            cmd = [pw_record, "--format=s16", "--channels=1", "--rate=16000", self.output_file_path]
        elif parec:
            cmd = [parec, "--format=s16le", "--channels=1", "--rate=16000", self.output_file_path]
        elif ffmpeg:
            cmd = [ffmpeg, "-y", "-f", "pulse", "-i", "default", "-ar", "16000", "-ac", "1", self.output_file_path]
        else:
            raise RuntimeError("No microphone recording utility (PyAudio, GStreamer, arecord, pw-record, parec, or ffmpeg) is installed.")

        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._thread = threading.Thread(target=self._subprocess_loop, daemon=True)
        self._thread.start()

    def _subprocess_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._proc and self._proc.poll() is not None:
                break
            self._update_duration()
            time.sleep(0.1)

    def _cleanup_subprocess(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    # --- Helper methods ---
    def _update_duration(self) -> None:
        now = time.time()
        paused = self._paused_accumulated
        if self._pause_started is not None:
            paused += now - self._pause_started

        duration = max(0.0, now - self._start_time - paused)
        if self.recording_duration_changed:
            self.recording_duration_changed(duration)

    def pause_recording(self) -> None:
        if not self.is_recording:
            return

        if not self.is_paused:
            self._pause_started = time.time()
            self.is_paused = True
            if self._backend == "gst" and self._pipeline:
                self._pipeline.set_state(Gst.State.PAUSED)
        else:
            if self._pause_started is not None:
                self._paused_accumulated += time.time() - self._pause_started
                self._pause_started = None
            self.is_paused = False
            if self._backend == "gst" and self._pipeline:
                self._pipeline.set_state(Gst.State.PLAYING)

    def stop_recording(self) -> None:
        if not self.is_recording:
            return

        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)

        if self._backend == "pyaudio":
            self._cleanup_pyaudio()
        elif self._backend == "gst":
            self._cleanup_gst()
        else:
            self._cleanup_subprocess()

        self.is_recording = False
        self.is_paused = False
        self._pause_started = None
        self._paused_accumulated = 0.0

    def delete_file(self) -> None:
        try:
            if self.output_file_path and os.path.exists(self.output_file_path):
                os.remove(self.output_file_path)
        except Exception:
            pass
        finally:
            self.output_file_path = ""
