"""
LLM client abstractions.

Default behavior now favors DashScope/Qwen when LLM_PROVIDER is qwen/dashscope,
while keeping compatibility with existing OpenAI-compatible and Gemini flows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google import genai
from openai import OpenAI

try:
    import dashscope
except Exception:  # pragma: no cover - runtime optional dependency
    dashscope = None

from http import HTTPStatus

logger = logging.getLogger(__name__)
load_dotenv()


@dataclass
class ToolCall:
    """Represents a tool call request from the LLM."""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ChatResponse:
    """Response from chat_with_tools."""

    content: Optional[str]
    tool_calls: List[ToolCall]
    finish_reason: str
    raw_response: Any = None


class BaseLLMClient(ABC):
    @abstractmethod
    def generate_content(self, prompt: str) -> str:
        """Single-turn text generation."""

    @abstractmethod
    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
    ) -> ChatResponse:
        """Tool-calling chat API."""

    def one_chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Backward-friendly helper expected by some external integration notes.
        """
        full_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
        return self.generate_content(full_prompt)

    async def a_one_chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.one_chat, prompt, system_prompt)


class GoogleGeminiClient(BaseLLMClient):
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        api_endpoint = os.getenv("GEMINI_API_ENDPOINT")
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment variables.")

        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if api_endpoint:
            client_kwargs["http_options"] = {"base_url": api_endpoint, "api_version": "v1alpha"}

        self.client = genai.Client(**client_kwargs)
        self.model_name = model

    def generate_content(self, prompt: str) -> str:
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            return response.text or "Error: No text returned from model."
        except Exception as exc:
            logger.error("Gemini generate_content failed: %s", exc)
            return f"Error: Could not generate analysis. Details: {exc}"

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
    ) -> ChatResponse:
        del tool_choice
        try:
            from google.genai import types

            contents = []
            system_instruction = None

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role == "system":
                    system_instruction = content
                elif role == "user":
                    contents.append(types.Content(role="user", parts=[types.Part(text=content)]))
                elif role == "assistant":
                    contents.append(types.Content(role="model", parts=[types.Part(text=content)]))
                elif role == "tool":
                    tool_response = types.Part(
                        function_response=types.FunctionResponse(
                            name=msg.get("name", ""),
                            response={"result": content},
                        )
                    )
                    contents.append(types.Content(role="user", parts=[tool_response]))

            gemini_tools = None
            if tools:
                function_declarations = []
                for tool in tools:
                    if tool.get("type") != "function":
                        continue
                    func = tool.get("function", {})
                    function_declarations.append(
                        types.FunctionDeclaration(
                            name=func.get("name", ""),
                            description=func.get("description", ""),
                            parameters=func.get("parameters", {}),
                        )
                    )
                if function_declarations:
                    gemini_tools = [types.Tool(function_declarations=function_declarations)]

            config_kwargs: Dict[str, Any] = {}
            if system_instruction:
                config_kwargs["system_instruction"] = system_instruction

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(tools=gemini_tools, **config_kwargs),
            )

            tool_calls: List[ToolCall] = []
            content = None

            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        tool_calls.append(
                            ToolCall(
                                id=f"call_{fc.name}_{len(tool_calls)}",
                                name=fc.name,
                                arguments=dict(fc.args) if fc.args else {},
                            )
                        )
                    elif hasattr(part, "text") and part.text:
                        content = part.text

            return ChatResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                raw_response=response,
            )
        except Exception as exc:
            logger.error("Gemini chat_with_tools failed: %s", exc)
            return ChatResponse(content=f"Error: {exc}", tool_calls=[], finish_reason="stop")


class OpenAIClient(BaseLLMClient):
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        key = api_key or os.getenv("OPENAI_API_KEY")
        url = base_url if base_url is not None else os.getenv("OPENAI_BASE_URL")

        raw_provider = (os.getenv("LLM_PROVIDER", "") or "").strip().lower()
        default_model = "qwen-plus" if raw_provider in {"qwen", "dashscope"} else "gpt-4o"
        model = model_name or os.getenv("OPENAI_MODEL", default_model)

        if not key:
            raise ValueError("OPENAI_API_KEY is not set in environment variables.")

        client_kwargs: Dict[str, Any] = {"api_key": key}
        if url:
            client_kwargs["base_url"] = url

        self.client = OpenAI(**client_kwargs)
        self.model_name = model

    def generate_content(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a professional financial analyst."},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.error("OpenAI generate_content failed: %s", exc)
            return f"Error: Could not generate analysis. Details: {exc}"

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
    ) -> ChatResponse:
        try:
            request_kwargs: Dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
            }
            if tools:
                request_kwargs["tools"] = tools
                request_kwargs["tool_choice"] = tool_choice

            response = self.client.chat.completions.create(**request_kwargs)
            message = response.choices[0].message

            tool_calls: List[ToolCall] = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=args,
                        )
                    )

            return ChatResponse(
                content=message.content,
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                raw_response=response,
            )
        except Exception as exc:
            logger.error("OpenAI chat_with_tools failed: %s", exc)
            return ChatResponse(content=f"Error: {exc}", tool_calls=[], finish_reason="stop")


class DashScopeClient(BaseLLMClient):
    """
    DashScope (Qwen) client.

    - one_chat / a_one_chat: uses dashscope SDK Generation.call
    - chat_with_tools: uses OpenAI-compatible endpoint to preserve function-calling behavior
    """

    def __init__(self):
        self.api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL") or os.getenv("DASHSCOPE_MODEL", "qwen-plus")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

        if not self.api_key:
            logger.warning("DASHSCOPE_API_KEY/OPENAI_API_KEY not found in environment variables!")
        if dashscope is not None:
            dashscope.api_key = self.api_key
        else:
            logger.warning("dashscope package not installed, fallback to OpenAI-compatible client only.")

        self._compat_client = OpenAIClient(
            api_key=self.api_key,
            base_url=self.base_url,
            model_name=self.model,
        )

    def one_chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        if dashscope is None:
            # Fallback path when SDK is unavailable.
            fallback_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
            return self._compat_client.generate_content(fallback_prompt)

        try:
            response = dashscope.Generation.call(
                model=self.model,
                messages=messages,
                result_format="message",
            )
            if response.status_code == HTTPStatus.OK:
                return response.output.choices[0].message.content
            logger.error("Qwen API Error: %s - %s", getattr(response, "code", ""), getattr(response, "message", ""))
            return f"Error: {getattr(response, 'message', 'Qwen API call failed')}"
        except Exception as exc:
            logger.error("Qwen one_chat failed: %s", exc)
            return ""

    async def a_one_chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.one_chat, prompt, system_prompt)

    def generate_content(self, prompt: str) -> str:
        return self.one_chat(
            prompt=prompt,
            system_prompt="You are a professional financial analyst.",
        )

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
    ) -> ChatResponse:
        # Keep full tool-calling compatibility through OpenAI-compatible API.
        return self._compat_client.chat_with_tools(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )


def normalize_llm_provider(provider: Optional[str]) -> str:
    value = (provider or "gemini").strip().lower()
    alias_map = {
        "qwen": "dashscope",
        "openai-compatible": "openai_compatible",
    }
    return alias_map.get(value, value)


def get_llm_client() -> BaseLLMClient:
    provider = normalize_llm_provider(os.getenv("LLM_PROVIDER", "gemini"))

    if provider == "gemini":
        return GoogleGeminiClient()
    if provider == "dashscope":
        return DashScopeClient()
    if provider in {"openai", "openai_compatible"}:
        return OpenAIClient()
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
