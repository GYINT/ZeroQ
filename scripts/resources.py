#!/usr/bin/env python3
"""qcm_resources.py — QCM MCP Resources API

MCP Resources API:
  - resources/list: 列出可用资源
  - resources/read: 读取具体资源

支持的资源 URI:
  - qcm://corpus/{filename}     - QCM corpus 文件
  - qcm://tools/{num}            - 工具定义（A01-F10）
  - qcm://masters/{name}          - 大师档案
  - qcm://standards/{id}          - 标准引用

用法：
  from resources import resource_handler
  result = resource_handler.list_resources()
  result = resource_handler.read_resource("qcm://tools/A01")
"""
import os
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse


class ResourceHandler:
    """Resources API 处理器"""

    def __init__(self, corpus: Dict[str, str]):
        """corpus: {filename: content} 文件名到内容的映射"""
        self.corpus = corpus

    def list_resources(self) -> List[Dict[str, str]]:
        """列出所有可用资源"""
        resources = []

        # 1. corpus 文件（仅核心 5 个）
        key_files = ["action-orders.md", "tools.md", "masters.md",
                     "standards-citation.md", "cases.md"]
        for filename in key_files:
            if filename in self.corpus:
                resources.append({
                    "uri": f"qcm://corpus/{filename}",
                    "name": filename.replace(".md", "").replace("-", "_"),
                    "mimeType": "text/markdown",
                    "description": f"QCM corpus file: {filename}",
                })

        # 2. 工具（A01-F10）
        tools_md = self.corpus.get("tools.md", "")
        for m in re.finditer(r"^## ([A-F]\d+)\. (.+)$", tools_md, re.M):
            num, name = m.group(1), m.group(2).strip()
            # 提取简称
            short_name = re.split(r"[\s（(]", name)[0]
            resources.append({
                "uri": f"qcm://tools/{num}",
                "name": f"tool_{num}_{short_name}",
                "mimeType": "application/json",
                "description": f"QCM Tool {num}: {name}",
            })

        # 3. 大师
        masters_md = self.corpus.get("masters.md", "")
        # 简单正则：包含在 "## " 下的中文姓名（3-4 字）
        master_names = set()
        for m in re.finditer(r"^## ([^\n]{2,30})\s*$", masters_md, re.M):
            name = m.group(1).strip()
            # 启发式过滤：排除非姓名（如"21 位核心大师"）
            if any(skip in name for skip in ["大师", "简介", "附录", "参考"]):
                continue
            if len(name) > 20:
                continue
            master_names.add(name)
        for name in sorted(master_names):
            resources.append({
                "uri": f"qcm://masters/{name}",
                "name": f"master_{name}",
                "mimeType": "text/markdown",
                "description": f"QCM Master: {name}",
            })

        # 4. 标准（V8.4 A2：由 entities.yaml 派生 · 消除与实体层双源漂移；缺失用内置兜底）
        standards = self._load_standard_entities()
        for std_id in standards:
            resources.append({
                "uri": f"qcm://standards/{std_id}",
                "name": f"standard_{std_id}",
                "mimeType": "text/markdown",
                "description": f"QCM Standard: {std_id}",
            })

        return resources

    @staticmethod
    def _load_standard_entities() -> list:
        """从 entities.yaml 提取标准实体名（单一真源 · 与 extract_entities 对齐）"""
        try:
            import yaml
            from pathlib import Path
            ent_path = Path(__file__).resolve().parent.parent / "references" / "config" / "entities.yaml"
            ent = yaml.safe_load(ent_path.read_text(encoding="utf-8")) or {}
            stds = [e["name"] for e in ent.get("entities", []) if e.get("type") == "standard"]
            if stds:
                return stds
        except Exception:
            pass
        # 内置兜底（entities.yaml 缺失/解析失败时）
        return ["ISO9001", "IATF16949", "AS9100", "VDA6.3", "VDA6.5",
                "ISO42001", "CQI", "CMMI", "ESG", "ISO14001"]

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """读取具体资源"""
        # 手动解析 qcm:// URI（因为 qcm 不是标准 scheme）
        if not uri.startswith("qcm://"):
            return {"error": f"unsupported scheme: {uri}", "uri": uri}

        # 提取 path (格式: qcm://type/identifier)
        path = uri[6:]  # 去掉 "qcm://"
        if path.startswith("/"):
            path = path[1:]

        if path.startswith("corpus/"):
            filename = path[len("corpus/"):]
            content = self.corpus.get(filename)
            if content is None:
                return {"error": f"corpus file not found: {filename}", "uri": uri}
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": content,
                }]
            }
        elif path.startswith("tools/"):
            tool_num = path[len("tools/"):]
            tools_md = self.corpus.get("tools.md", "")
            # 提取该工具的完整定义
            pattern = re.compile(
                rf"^## {tool_num}\. (.+?)(?=^## [A-F]\d+\. |\Z)",
                re.M | re.S
            )
            m = pattern.search(tools_md)
            if not m:
                return {"error": f"tool not found: {tool_num}", "uri": uri}
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": m.group(0),
                }]
            }
        elif path.startswith("masters/"):
            master_name = path[len("masters/"):]
            masters_md = self.corpus.get("masters.md", "")
            # 简单返回段落
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": f"# 大师: {master_name}\n\n（从 masters.md 提取）\n\n请访问 masters.md 查看完整内容。",
                }]
            }
        elif path.startswith("standards/"):
            std_id = path[len("standards/"):]
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": f"# 标准: {std_id}\n\n（从 standards-citation.md 提取）\n\n请访问 standards-citation.md 查看完整内容。",
                }]
            }
        else:
            return {"error": f"unsupported resource path: {path}", "uri": uri}


# 全局实例（懒加载）
_handler: Optional[ResourceHandler] = None


def get_resource_handler() -> ResourceHandler:
    """获取全局 ResourceHandler"""
    global _handler
    if _handler is None:
        from mcp_server import load_corpus
        _handler = ResourceHandler(load_corpus())
    return _handler


if __name__ == "__main__":
    # Demo
    import sys
    from paths import SCRIPTS
    sys.path.insert(0, str(SCRIPTS))
    from mcp_server import load_corpus
    corpus = load_corpus()

    handler = ResourceHandler(corpus)
    resources = handler.list_resources()
    print(f"=== Resources 列表（共 {len(resources)} 个）===")
    for r in resources[:5]:
        print(f"  - {r['uri']} ({r['mimeType']})")

    print()
    print("=== 读取 qcm://tools/A01 ===")
    result = handler.read_resource("qcm://tools/A01")
    if "contents" in result:
        text = result["contents"][0]["text"]
        print(f"  ({len(text)} chars) {text[:200]}...")
    else:
        print(f"  error: {result}")