import os
import json
import base64
import wave
import tempfile
import uuid
import urllib.parse
import urllib.request
import urllib.error

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class OpenAIService:
    GEMINI_HOST_NAME = "generativelanguage.googleapis.com"
    MAX_SINGLE_FILE_SIZE = 15 * 1024 * 1024  # 15 MB safety threshold before chunking

    def transcribe_audio(self, file_path: str, api_key: str, host: str, model: str, language_code: str) -> str:
        if not api_key or not api_key.strip():
            raise RuntimeError("API Key is missing. Please set your API Key in Settings -> API Settings.")

        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        if file_size > self.MAX_SINGLE_FILE_SIZE:
            chunks = self._split_wav_file(file_path, max_duration_sec=300)
            if len(chunks) > 1:
                results = []
                try:
                    for chunk_path in chunks:
                        t = self._transcribe_single_file(chunk_path, api_key, host, model, language_code)
                        if t and t.strip():
                            results.append(t.strip())
                    return " ".join(results)
                finally:
                    for c_path in chunks:
                        if c_path != file_path and os.path.exists(c_path):
                            try:
                                os.remove(c_path)
                            except Exception:
                                pass

        return self._transcribe_single_file(file_path, api_key, host, model, language_code)

    def _split_wav_file(self, file_path: str, max_duration_sec: int = 300) -> list:
        chunk_paths = []
        try:
            with wave.open(file_path, "rb") as wf:
                params = wf.getparams()
                nchannels, sampwidth, framerate, nframes = params[:4]
                if framerate <= 0:
                    return [file_path]

                frames_per_chunk = framerate * max_duration_sec

                if nframes <= frames_per_chunk:
                    return [file_path]

                temp_dir = tempfile.gettempdir()
                frames_read = 0
                while frames_read < nframes:
                    to_read = min(frames_per_chunk, nframes - frames_read)
                    data = wf.readframes(to_read)
                    frames_read += to_read

                    chunk_path = os.path.join(temp_dir, f"chunk_{uuid.uuid4().hex}.wav")
                    with wave.open(chunk_path, "wb") as chunk_wf:
                        chunk_wf.setparams(params)
                        chunk_wf.writeframes(data)
                    chunk_paths.append(chunk_path)
            return chunk_paths if chunk_paths else [file_path]
        except Exception:
            return [file_path]

    def _transcribe_single_file(self, file_path: str, api_key: str, host: str, model: str, language_code: str) -> str:
        if self._is_gemini_host(host):
            return self._transcribe_with_gemini(file_path, api_key, host, model, language_code)

        endpoint = host.rstrip("/") + "/audio/transcriptions"

        if HAS_REQUESTS:
            headers = {"Authorization": f"Bearer {api_key.strip()}"}
            data = {
                "model": model,
                "temperature": "0",
                "prompt": "Transcribe the audio verbatim, exactly as spoken. Do not alter words, do not summarize, do not omit anything, and do not add extra text.",
            }
            if language_code:
                data["language"] = language_code

            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f, "audio/wav")}
                resp = requests.post(endpoint, headers=headers, data=data, files=files, timeout=90)

            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI transcription HTTP {resp.status_code}: {resp.text}")

            result = resp.json()
            return result.get("text", "")
        else:
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            boundary = f"----WebKitFormBoundary{os.urandom(16).hex()}"
            body = bytearray()

            def add_field(name: str, value: str):
                body.extend(f"--{boundary}\r\n".encode("utf-8"))
                body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
                body.extend(f"{value}\r\n".encode("utf-8"))

            add_field("model", model)
            add_field("temperature", "0")
            add_field("prompt", "Transcribe the audio verbatim, exactly as spoken. Do not alter words, do not summarize, do not omit anything, and do not add extra text.")
            if language_code:
                add_field("language", language_code)

            filename = os.path.basename(file_path)
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"))
            body.extend(b"Content-Type: audio/wav\r\n\r\n")
            body.extend(file_bytes)
            body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode("utf-8"))

            req = urllib.request.Request(endpoint, data=bytes(body), method="POST")
            req.add_header("Authorization", f"Bearer {api_key.strip()}")
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    resp_bytes = resp.read()
                    data = json.loads(resp_bytes.decode("utf-8"))
                    return data.get("text", "")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"OpenAI transcription HTTP {e.code}: {err_body}")
            except Exception as e:
                raise RuntimeError(f"OpenAI transcription error: {e}")

    def _is_gemini_host(self, host: str) -> bool:
        if not host or not host.strip():
            return False
        return self.GEMINI_HOST_NAME.lower() in host.lower()

    def _transcribe_with_gemini(self, file_path: str, api_key: str, host: str, model: str, language_code: str = "en") -> str:
        gemini_base_url = host.rstrip("/")
        if gemini_base_url.lower().endswith("/openai"):
            gemini_base_url = gemini_base_url[:-7]

        endpoint = f"{gemini_base_url}/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(api_key.strip())}"

        with open(file_path, "rb") as f:
            audio_bytes = f.read()

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        lang_map = {"bn": "Bengali", "hi": "Hindi", "en": "English"}
        lang_name = lang_map.get(language_code, language_code) if language_code else "English"

        system_instruction = {
            "parts": [
                {
                    "text": (
                        f"You are an exact verbatim speech-to-text transcriber. "
                        f"The audio language is {lang_name}. "
                        f"Transcribe every spoken word in {lang_name} exactly as heard in the audio. "
                        f"DO NOT translate into another language. "
                        f"DO NOT correct grammar, fix punctuation errors, or alter any spoken word. "
                        f"DO NOT summarize or add commentary. "
                        f"DO NOT output introductory text, markdown formatting, quotes, or conversational responses. "
                        f"Output ONLY the verbatim transcribed spoken text in {lang_name}."
                    )
                }
            ]
        }

        payload = {
            "systemInstruction": system_instruction,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": audio_b64,
                            }
                        },
                        {"text": f"Transcribe this audio verbatim in {lang_name}. Output ONLY the exact transcribed spoken words."}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "topP": 1.0,
                "topK": 1,
            },
        }

        if HAS_REQUESTS:
            headers = {"Content-Type": "application/json"}
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=90)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini transcription HTTP {resp.status_code}: {resp.text}")
            doc = resp.json()
        else:
            json_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=json_data, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    resp_bytes = resp.read()
                    doc = json.loads(resp_bytes.decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"Gemini transcription HTTP {e.code}: {err_body}")

        candidates = doc.get("candidates") or []
        if candidates and isinstance(candidates, list):
            first = candidates[0]
            content = first.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                if "text" in part:
                    return self._clean_gemini_transcript(part["text"])

        raise RuntimeError(f"Gemini transcription response did not contain text. Response: {doc}")

    def _clean_gemini_transcript(self, text: str) -> str:
        if not text:
            return ""
        text = text.strip()

        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                if lines[-1].startswith("```"):
                    text = "\n".join(lines[1:-1])
                else:
                    text = "\n".join(lines[1:])
            text = text.strip()

        # Remove introductory prefixes if Gemini added them
        prefixes = [
            "here is the transcription:",
            "here's the transcription:",
            "here is the audio transcription:",
            "here is what was spoken:",
            "here is the transcript:",
            "here's the transcript:",
            "transcription:",
            "transcript:",
        ]
        lower_text = text.lower()
        for prefix in prefixes:
            if lower_text.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        # Strip surrounding quotation marks if present
        if len(text) >= 2 and ((text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'"))):
            text = text[1:-1].strip()

        return text
