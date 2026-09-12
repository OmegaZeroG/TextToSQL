from app.llm.base import LLMProvider


class GroqProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        from groq import Groq
        self._client = Groq(api_key=api_key)
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        kwargs = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            **kwargs,
        )
        return response.choices[0].message.content


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        kwargs = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            **kwargs,
        )
        return response.choices[0].message.content


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        from anthropic import Anthropic
        self._client = Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        suffix = "\n\nRespond with valid JSON only, no markdown fences." if json_mode else ""
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system_prompt + suffix,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0,
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        response = self._client.models.generate_content(
            model=self._model, contents=user_prompt, config=config,
        )
        return response.text
