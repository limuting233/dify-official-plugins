from typing import Any

import requests
from dify_plugin import ToolProvider


SOMARK_OFFICIAL_API_BASE_URL = "https://somark.tech/api/v1"


class SoMarkProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """
        Validate credentials.
        """
        deployment_type = credentials.get("deployment_type") or "somark_api"
        base_url = (credentials.get("base_url") or "").strip()
        api_key = (credentials.get("api_key") or "").strip()

        if base_url and not base_url.startswith(("http://", "https://")):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")

        if deployment_type == "somark_api":
            if not api_key:
                raise ValueError("使用 SoMark 官方 API 时必须填写 API Key")
            if base_url and base_url.rstrip("/") != SOMARK_OFFICIAL_API_BASE_URL:
                raise ValueError("Base URL 或 API Key 无效，请检查后重试")
            self._validate_api_key_via_official(api_key)
        elif deployment_type == "private":
            if not base_url:
                raise ValueError("SoMark Self-host 时必须填写 Base URL ")

    @staticmethod
    def _validate_api_key_via_official(api_key: str) -> None:
        try:
            resp = requests.post(
                f"{SOMARK_OFFICIAL_API_BASE_URL}/usage",
                data={"api_key": api_key},
            )
        except requests.RequestException as e:
            raise ValueError(f"无法连接 SoMark 服务，请检查网络：{e}") from e

        try:
            payload = resp.json()
        except ValueError:
            raise ValueError(
                f"SoMark 服务返回了非 JSON 响应（HTTP {resp.status_code}）"
            )

        if payload.get("code") == 1107:
            raise ValueError("Base URL 或 API Key 无效，请检查后重试")

        if not resp.ok:
            message = payload.get("message") or "未知错误"
            raise ValueError(f"SoMark 校验失败：{message}")
