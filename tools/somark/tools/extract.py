import logging
import json
from typing import Any, Dict, Generator
import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

logger = logging.getLogger(__name__)


class ExtractTool(Tool):
    def _invoke(self, tool_parameters: Dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        """
        Invoke the Somark extraction tool.
        """
        # 1. Get parameters
        file = tool_parameters.get("file")  # 获取file参数
        if not file:
            yield self.create_text_message("Error: No file provided.")
            return

        # 获取output_formats参数
        output_formats = tool_parameters.get("output_formats")
        if not output_formats:
            yield self.create_text_message("Error: No output formats provided.")
            return

        if not isinstance(output_formats, list) or not output_formats or not all(
                isinstance(item, str) for item in output_formats):
            yield self.create_text_message(
                "Error: output_formats must be a non-empty list of strings."
            )
            return

        allowed_output_formats = {"json", "markdown", "somarkdown", "zip"}

        invalid_formats = [item for item in output_formats if item not in allowed_output_formats]

        if invalid_formats:
            yield self.create_text_message(
                f"Error: Invalid output_formats: {invalid_formats}. "
                "Allowed values are json, markdown, somarkdown, zip."
            )
            return

        if len(output_formats) != len(set(output_formats)):
            yield self.create_text_message("Error: output_formats contains duplicate values.")
            return

        if "zip" in output_formats and not (
                output_formats == ["zip"]
                or (len(output_formats) == 2 and set(output_formats) == {"zip", "json"})
        ):
            yield self.create_text_message(
                "Error: When zip is included, output_formats must be either ['zip'] or contain exactly 'zip' and 'json' in any order."
            )
            return

        # 获取element_formats参数
        default_element_formats = {
            "image": "url",
            "formula": "latex",
            "table": "html",
            "cs": "image",
        }
        allowed_element_formats = {
            "image": {"url", "base64", "none"},
            "formula": {"latex", "mathml", "ascii"},
            "table": {"markdown", "html", "image"},
            "cs": {"image"},
        }
        raw_element_formats = tool_parameters.get("element_formats") or {}

        if not isinstance(raw_element_formats, dict):
            yield self.create_text_message("Error: element_formats must be an object.")
            return

        element_formats: Dict[str, str] = {}
        zip_requested = "zip" in output_formats

        raw_image_value = raw_element_formats.get("image")
        image_provided = "image" in raw_element_formats

        if zip_requested:
            if not image_provided or raw_image_value is None:
                element_formats["image"] = "file"
            elif raw_image_value == "none":
                element_formats["image"] = "none"
            else:
                yield self.create_text_message(
                    "Error: When zip is included, element_formats.image must be 'none' or omitted."
                )
                return
        else:
            image_value = default_element_formats["image"] if raw_image_value is None else raw_image_value

            if not isinstance(image_value, str) or image_value not in allowed_element_formats["image"]:
                allowed_values = ", ".join(sorted(allowed_element_formats["image"]))
                yield self.create_text_message(
                    f"Error: element_formats.image must be one of: {allowed_values}."
                )
                return

            element_formats["image"] = image_value

        for key in ("formula", "table", "cs"):
            # for key in ("formula", "table"):
            default_value = default_element_formats[key]
            value = raw_element_formats.get(key, default_value)
            if value is None:
                value = default_value

            if not isinstance(value, str) or value not in allowed_element_formats[key]:
                allowed_values = ", ".join(sorted(allowed_element_formats[key]))
                yield self.create_text_message(
                    f"Error: element_formats.{key} must be one of: {allowed_values}."
                )
                return

            element_formats[key] = value

        # 获取feature_config参数
        default_feature_config = {
            "enable_text_cross_page": False,
            "enable_table_cross_page": False,
            "enable_title_level_recognition": False,
            "enable_inline_image": True,
            "enable_table_image": True,
            "enable_image_understanding": True,
            "keep_header_footer": False,
        }

        raw_feature_config = tool_parameters.get("feature_config") or {}
        if not isinstance(raw_feature_config, dict):
            yield self.create_text_message("Error: feature_config must be an object.")
            return

        feature_config: Dict[str, bool] = {}
        for key, default_value in default_feature_config.items():
            value = raw_feature_config.get(key, default_value)
            if value is None:
                value = default_value

            if not isinstance(value, bool):
                yield self.create_text_message(
                    f"Error: feature_config.{key} must be a boolean."
                )
                return

            feature_config[key] = value

        # 2. Get configuration
        base_url = self.runtime.credentials.get("base_url")
        if not base_url:
            base_url = "https://somark.tech/api/v1"

        api_key = self.runtime.credentials.get("api_key")
        if not api_key:
            yield self.create_text_message("Error: API Key is required.")
            return

        # 3. Construct URL
        base_url = base_url.rstrip("/")
        url = f"{base_url}/parse/sync"

        # 4. Prepare request
        try:
            files = {
                "file": (file.filename, file.blob, file.mime_type)
            }

            data = {
                "output_formats": output_formats,
                "api_key": api_key,
                "element_formats": json.dumps(element_formats, ensure_ascii=False),
                "feature_config": json.dumps(feature_config, ensure_ascii=False),
            }

            # 5. Send request
            response = requests.post(url, files=files, data=data, timeout=120)

            if response.status_code != 200:
                error_msg = f"Somark API Error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                yield self.create_text_message(error_msg)
                return

            # 6. Process response
            try:
                result = response.json()
            except json.JSONDecodeError:
                yield self.create_text_message(f"Error: Invalid JSON response from API. Content: {response.text}")
                return

            # Extract content
            json_content = None
            md_content = ""
            smd_content = ""
            zip_url = ""
            error_content = ""

            data_block = result.get("data") if isinstance(result, dict) else None
            result_block = data_block.get("result") if isinstance(data_block, dict) else None
            outputs = result_block.get("outputs") if isinstance(result_block, dict) else None

            if isinstance(result, dict) and result.get("code") == 0 and isinstance(outputs, dict):
                md_value = outputs.get("markdown")
                if isinstance(md_value, str) and md_value.strip():
                    md_content = md_value

                json_value = outputs.get("json")
                if json_value not in (None, "", [], {}):
                    json_content = json_value

                smd_value = outputs.get("somarkdown")
                if isinstance(smd_value, str) and smd_value.strip():
                    smd_content = smd_value

                zip_value = outputs.get("zip")
                if isinstance(zip_value, str) and zip_value.strip():
                    zip_url = zip_value
            else:
                error_content = json.dumps(result, ensure_ascii=False)
                logger.error("Somark API returned unexpected payload: %s", error_content)
                yield self.create_text_message(error_content)
                return

            if json_content not in (None, "", [], {}):
                yield self.create_variable_message("json", json_content)
            if md_content:
                yield self.create_variable_message("markdown", md_content)
            if smd_content:
                yield self.create_variable_message("somarkdown", smd_content)
            if zip_url:
                yield self.create_variable_message("zip", zip_url)

            yield self.create_json_message(result)



        except requests.exceptions.RequestException as e:
            logger.error(f"Somark Network Error: {str(e)}")
            yield self.create_text_message(f"Network error connecting to Somark API: {str(e)}")
        except Exception as e:
            logger.error(f"Somark Plugin Error: {str(e)}")
            yield self.create_text_message(f"Error invoking Somark API: {str(e)}")
