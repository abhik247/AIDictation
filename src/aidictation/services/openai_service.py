import os
import json
import base64
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

    def transcribe_audio(self, file_path: str, api_key: str, host: str, model: str, language_code: str) -> str:
        if not api_key or not api_key.strip():
            raise RuntimeError("API Key is missing. Please set your API Key in Settings -> API Settings.")

        if self._is_gemini_host(host):
            return self._transcribe_with_gemini(file_path, api_key, host, model)

        endpoint = host.rstrip("/") + "/audio/transcriptions"

        if HAS_REQUESTS:
            headers = {"Authorization": f"Bearer {api_key.strip()}"}
            data = {"model": model}
            if language_code:
                data["language"] = language_code

            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f, "audio/wav")}
                resp = requests.post(endpoint, headers=headers, data=data, files=files, timeout=60)

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
                with urllib.request.urlopen(req, timeout=60) as resp:
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

    def _transcribe_with_gemini(self, file_path: str, api_key: str, host: str, model: str) -> str:
        gemini_base_url = host.rstrip("/")
        if gemini_base_url.lower().endswith("/openai"):
            gemini_base_url = gemini_base_url[:-7]

        endpoint = f"{gemini_base_url}/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(api_key.strip())}"

        with open(file_path, "rb") as f:
            audio_bytes = f.read()

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "Transcribe this audio accurately and return only the transcribed text."},
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": audio_b64,
                            }
                        },
                    ]
                }
            ]
        }

        if HAS_REQUESTS:
            headers = {"Content-Type": "application/json"}
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini transcription HTTP {resp.status_code}: {resp.text}")
            doc = resp.json()
        else:
            json_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=json_data, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
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
                    return part["text"]

        raise RuntimeError(f"Gemini transcription response did not contain text. Response: {doc}")
