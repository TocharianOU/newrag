"""VLM (Vision Language Model) Page Extractor with Schema Validation"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

# Add tools directory to path to import lmstudio_vision_reader
tools_path = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(tools_path))

from lmstudio_vision_reader import LMStudioVisionReader

logger = structlog.get_logger(__name__)


class VLMPageExtractor:
    """Extract structured information from page images using Vision Language Models (Gemini, Qwen-VL, etc.)"""
    
    # JSON Schema for drawing pages
    DRAWING_SCHEMA = {
        "type": "object",
        "properties": {
            "document_info": {"type": "object"},
            "equipment": {"type": "array"},
            "components": {"type": "array"},
            "pipes_and_valves": {"type": "array"},
            "tables": {"type": "array"},
            "all_text": {"type": "array"},
            "technical_parameters": {"type": "array"},
            "notes": {"type": "array"}
        }
    }
    
    # Drawing extraction prompt
    DRAWING_PROMPT = """你是专业的工业图纸识别专家。请**逐像素**分析图片，提取所有信息。

【关键要求】：
1. 提取图纸上**每一个**元器件编号（电容C、电阻R、芯片U/IC、二极管D、晶体管Q、阀门V、泵P等）
2. 记录元器件的型号、参数值（如"100uF"、"10kΩ"、"7805"）
3. 提取所有设备标签（如"V-2001"、"P-1001A"、"SA-2001"）
4. 识别管道、阀门、仪表的标识
5. 提取表格中的每个单元格内容
6. 记录所有文字、数字、符号

【输出 JSON 格式】（严格遵守）：
{
  "document_info": {
    "document_type": "图纸类型",
    "title": "标题",
    "drawing_number": "图号",
    "project_name": "项目名称",
    "company": "公司名称"
  },
  "equipment": [
    {"tag": "V-2001", "name": "设备名", "type": "类型", "position": "E-F/11"}
  ],
  "components": [
    {"id": "C1", "type": "电容", "value": "100uF", "voltage": "25V", "position": "A3"},
    {"id": "R100", "type": "电阻", "value": "10kΩ", "power": "1/4W"},
    {"id": "U1A", "type": "芯片", "model": "LM358", "pin_count": "8"}
  ],
  "pipes_and_valves": [
    {"id": "管道标识", "type": "管道/阀门类型", "spec": "规格"}
  ],
  "tables": [
    {"title": "表格标题", "headers": ["列1", "列2"], "rows": [["单元格1", "单元格2"]]}
  ],
  "all_text": ["图纸上所有可见文字"],
  "technical_parameters": ["技术参数列表"],
  "notes": ["备注信息"]
}

【禁止】：
- 禁止编造不存在的内容
- 禁止遗漏任何元器件编号
- 禁止简化或合并元器件信息

直接输出 JSON，不要任何解释。"""
    
    # Table extraction prompt
    TABLE_PROMPT = """请提取图片中的表格数据。

【要求】：
1. 识别表格标题
2. 提取表头（列名）
3. 提取每一行的数据
4. 保持原始文字（中文保持中文，英文保持英文）

【输出 JSON 格式】：
{
  "tables": [
    {
      "title": "表格标题",
      "headers": ["列1", "列2", "列3"],
      "rows": [
        ["数据1", "数据2", "数据3"],
        ["数据4", "数据5", "数据6"]
      ]
    }
  ],
  "all_text": ["其他可见文字"]
}

直接输出 JSON，不要任何解释。"""
    
    # Mixed content prompt
    MIXED_PROMPT = """请提取图片中的所有内容。

【要求】：
1. 识别所有文字
2. 如果有表格，提取表格数据
3. 如果有图表/图纸元素，提取标识
4. 保持原始文字

【输出 JSON 格式】：
{
  "content_type": "mixed",
  "all_text": ["所有可见文字"],
  "tables": [
    {"title": "表格标题", "headers": [...], "rows": [[...]]}
  ],
  "elements": [
    {"id": "元素标识", "type": "元素类型"}
  ]
}

直接输出 JSON，不要任何解释。"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize VLM page extractor
        
        Args:
            config: Configuration dictionary (uses config.yaml if None)
        """
        self.config = config
        self.reader = LMStudioVisionReader(config_dict=config)
        
        logger.info("vlm_page_extractor_initialized")
    
    def extract_page_content(self, image_path: str, page_type: str = 'drawing') -> Dict[str, Any]:
        """
        Extract content from page image based on type
        
        Args:
            image_path: Path to image file
            page_type: Type of page (drawing/table/mixed/text)
        
        Returns:
            Extracted and validated page data
        """
        try:
            if page_type == 'drawing':
                return self.extract_drawing_page(image_path)
            elif page_type == 'table':
                return self.extract_table_page(image_path)
            elif page_type == 'mixed':
                return self.extract_mixed_page(image_path)
            else:
                # Default to drawing extraction
                return self.extract_drawing_page(image_path)
        
        except Exception as e:
            logger.error("page_extraction_failed", error=str(e), image_path=image_path, page_type=page_type)
            return {
                "error": str(e),
                "document_info": {},
                "equipment": [],
                "components": [],
                "all_text": []
            }
    
    def extract_drawing_page(self, image_path: str) -> Dict[str, Any]:
        """
        Extract structured information from drawing page
        
        Args:
            image_path: Path to drawing image
        
        Returns:
            Validated drawing data
        """
        logger.info("extracting_drawing_page", image_path=image_path)
        
        raw_output = self.reader.read_image(image_path, self.DRAWING_PROMPT)
        
        logger.debug("vlm_raw_output", output_preview=raw_output[:500] if raw_output else "EMPTY")
        
        validated = self._validate_and_fix_json(raw_output, self.DRAWING_SCHEMA)
        
        # Extract all components from various fields
        all_components = self._extract_all_components(validated)
        validated['all_components_list'] = all_components
        
        logger.info(
            "drawing_page_extracted",
            num_equipment=len(validated.get('equipment', [])),
            num_components=len(validated.get('components', [])),
            total_components=len(all_components)
        )
        
        return validated
    
    def extract_table_page(self, image_path: str) -> Dict[str, Any]:
        """
        Extract table data from page
        
        Args:
            image_path: Path to table image
        
        Returns:
            Extracted table data
        """
        logger.info("extracting_table_page", image_path=image_path)
        
        raw_output = self.reader.read_image(image_path, self.TABLE_PROMPT)
        validated = self._validate_and_fix_json(raw_output, {})
        
        logger.info(
            "table_page_extracted",
            num_tables=len(validated.get('tables', []))
        )
        
        return validated
    
    def extract_mixed_page(self, image_path: str) -> Dict[str, Any]:
        """
        Extract mixed content from page
        
        Args:
            image_path: Path to mixed content image
        
        Returns:
            Extracted mixed data
        """
        logger.info("extracting_mixed_page", image_path=image_path)
        
        raw_output = self.reader.read_image(image_path, self.MIXED_PROMPT)
        validated = self._validate_and_fix_json(raw_output, {})
        
        return validated
    
    def _validate_and_fix_json(self, raw_output: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse, validate and fix JSON output
        
        Args:
            raw_output: Raw string output from VLM
            schema: JSON schema for validation
        
        Returns:
            Validated and fixed JSON data
        """
        if not raw_output:
            logger.warning("empty_vlm_output")
            return self._get_default_structure()
        
        # Try to extract JSON from output
        json_str = self._extract_json_from_text(raw_output)
        
        if not json_str:
            logger.warning("no_json_found_in_output", output_preview=raw_output[:200])
            return self._get_default_structure()
        
        # Parse JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error("json_parse_error", error=str(e), json_preview=json_str[:200])
            # Try to fix common JSON errors
            data = self._fix_json_errors(json_str)
        
        # Validate schema
        if schema:
            data = self._validate_schema(data, schema)
        
        return data
    
    def _extract_json_from_text(self, text: str) -> Optional[str]:
        """
        Extract JSON object from text that may contain markdown or other content
        
        Args:
            text: Text containing JSON
        
        Returns:
            Extracted JSON string or None
        """
        # Remove markdown code blocks
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        
        # Find JSON object
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json_match.group(0)
        
        return None
    
    def _fix_json_errors(self, json_str: str) -> Dict[str, Any]:
        """
        Attempt to fix common JSON errors
        
        Args:
            json_str: Malformed JSON string
        
        Returns:
            Fixed JSON data or default structure
        """
        try:
            # Try removing trailing commas
            fixed = re.sub(r',\s*}', '}', json_str)
            fixed = re.sub(r',\s*]', ']', fixed)
            return json.loads(fixed)
        except:
            pass
        
        try:
            # Try fixing quotes
            fixed = json_str.replace("'", '"')
            return json.loads(fixed)
        except:
            pass
        
        logger.error("json_fix_failed", json_preview=json_str[:200])
        return self._get_default_structure()
    
    def _validate_schema(self, data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate data against schema and fill missing fields
        
        Args:
            data: Data to validate
            schema: Schema definition
        
        Returns:
            Validated data with default values for missing fields
        """
        if 'properties' in schema:
            for key, prop_schema in schema['properties'].items():
                if key not in data:
                    # Fill default value based on type
                    if prop_schema.get('type') == 'array':
                        data[key] = []
                    elif prop_schema.get('type') == 'object':
                        data[key] = {}
                    else:
                        data[key] = None
        
        return data
    
    def _get_default_structure(self) -> Dict[str, Any]:
        """
        Get default data structure when extraction fails
        
        Returns:
            Default empty structure
        """
        return {
            "document_info": {},
            "equipment": [],
            "components": [],
            "pipes_and_valves": [],
            "tables": [],
            "all_text": [],
            "technical_parameters": [],
            "notes": []
        }
    
    def _extract_all_components(self, page_json: Dict[str, Any]) -> List[str]:
        """
        Extract all component IDs from various fields
        
        Args:
            page_json: Page data
        
        Returns:
            List of all component IDs
        """
        components = []
        
        # From equipment
        for equip in page_json.get('equipment', []):
            if 'tag' in equip:
                components.append(equip['tag'])
            if 'id' in equip:
                components.append(equip['id'])
        
        # From components
        for comp in page_json.get('components', []):
            if 'id' in comp:
                components.append(comp['id'])
        
        # From pipes and valves
        for item in page_json.get('pipes_and_valves', []):
            if 'id' in item:
                components.append(item['id'])
        
        # Extract from text using patterns (C1, R100, V-2001, etc.)
        all_text = ' '.join(page_json.get('all_text', []))
        pattern = r'\b[A-Z]+[-]?\d+[A-Z]?\b'
        text_components = re.findall(pattern, all_text)
        components.extend(text_components)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_components = []
        for comp in components:
            if comp and comp not in seen:
                seen.add(comp)
                unique_components.append(comp)
        
        return unique_components

