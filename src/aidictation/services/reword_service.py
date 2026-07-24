import json
import urllib.parse
import urllib.request
import urllib.error

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class RewordService:
    GEMINI_HOST_NAME = "generativelanguage.googleapis.com"

    def reword(self, input_text: str, api_key: str, host: str, model: str, language_name: str, custom_instructions: str = "") -> str:
        if not api_key or not api_key.strip():
            raise RuntimeError("API Key is missing. Please set your API Key in Settings -> API Settings.")

        if self._is_gemini_host(host):
            return self._reword_with_gemini(input_text, api_key, host, model, language_name, custom_instructions)

        if not custom_instructions or not custom_instructions.strip():
            system_prompt = f"Rewrite the following text to be clear, grammatically correct, and natural in {language_name}:\n\n{input_text}"
        else:
            system_prompt = f"{custom_instructions}\n\nPlease output the result in {language_name}:\n\n{input_text}"

        request_body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": system_prompt,
                }
            ],
        }

        endpoint = host.rstrip("/") + "/chat/completions"

        if HAS_REQUESTS:
            headers = {
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
            }
            resp = requests.post(endpoint, headers=headers, json=request_body, timeout=60)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI rewording HTTP {resp.status_code}: {resp.text}")
            doc = resp.json()
            output = doc["choices"][0]["message"]["content"]
            return output or ""
        else:
            json_bytes = json.dumps(request_body).encode("utf-8")
            req = urllib.request.Request(endpoint, data=json_bytes, method="POST")
            req.add_header("Authorization", f"Bearer {api_key.strip()}")
            req.add_header("Content-Type", "application/json")

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    resp_bytes = resp.read()
                    doc = json.loads(resp_bytes.decode("utf-8"))
                    output = doc["choices"][0]["message"]["content"]
                    return output or ""
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"OpenAI rewording HTTP {e.code}: {err_body}")
            except Exception as e:
                raise RuntimeError(f"OpenAI rewording error: {e}")

    def _is_gemini_host(self, host: str) -> bool:
        if not host or not host.strip():
            return False
        return self.GEMINI_HOST_NAME.lower() in host.lower()

    def _reword_with_gemini(self, input_text: str, api_key: str, host: str, model: str, language_name: str, custom_instructions: str) -> str:
        gemini_base_url = host.rstrip("/")
        if gemini_base_url.lower().endswith("/openai"):
            gemini_base_url = gemini_base_url[:-7]

        if not custom_instructions or not custom_instructions.strip():
            prompt = f"Rewrite the following text to be clear, grammatically correct, and natural in {language_name}. Return only the rewritten text, nothing else:\n\n{input_text}"
        else:
            prompt = f"{custom_instructions}\n\nPlease output the result in {language_name}. Return only the rewritten text, nothing else:\n\n{input_text}"

        endpoint = f"{gemini_base_url}/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(api_key.strip())}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        }

        if HAS_REQUESTS:
            headers = {"Content-Type": "application/json"}
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini rewording HTTP {resp.status_code}: {resp.text}")
            doc = resp.json()
        else:
            json_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=json_bytes, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    resp_bytes = resp.read()
                    doc = json.loads(resp_bytes.decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"Gemini rewording HTTP {e.code}: {err_body}")

        candidates = doc.get("candidates") or []
        if candidates and isinstance(candidates, list):
            first = candidates[0]
            content = first.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                if "text" in part:
                    return part["text"]

        raise RuntimeError(f"Gemini rewording response did not contain rewritten text. Response: {doc}")
