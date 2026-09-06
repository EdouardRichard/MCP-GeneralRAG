# Contract: FormatHandler 注册表与转换器接口

**Branch**: `008-universal-ingestion-channel` | **Date**: 2026-09-06

本契约定义 008 的单一格式分发事实源（FormatHandler 注册表）、可插拔转换器接口，以及四处分发点的委托契约。实现与测试以本契约为准。

## 1. FormatHandler 条目（数据契约）

每条目为一个不可变 dataclass，字段（对齐 FR-002）：

```text
@dataclass(frozen=True)
class FormatHandler:
    format: str                  # 规范化格式名
    extensions: tuple[str, ...]  # 扩展名集（小写，含点）
    tier: Literal["native", "converter"]
    binary: bool                 # 是否二进制
    parser_factory: Callable[..., Any] | None   # native tier 必填
    converter_spec: ConverterSpec | None         # converter tier 必填
    locator_prefix: LocatorPrefix                 # sheet/path/msg/heading/page/symbol
```

> **Supersession（010 起）**：`graph_extractor` 字段与 §3 的 `graph_extractor(fmt)` 查询、§4 的「图提取分派」行自 010 起由
> `specs/010-graph-relation-registry/contracts/graph-extractor-registry.md` 承载（research R2）。图提取分派的单一事实源
> 迁至图层 `GraphExtractorRegistry`（format + 域词表双轴），FormatHandlerRegistry 仍是格式检测 / 解析分派 / 二进制
> 声明的单一事实源（其余契约不变）。

不变式：
- `native` tier：`parser_factory` 非空、`converter_spec` 为空。
- `converter` tier：`converter_spec` 非空、`parser_factory` 为空。
- 17 条条目：8 原生（markdown/java/openapi/ddl/go/python/word/pdf，冻结既有工厂）+ 9 新（html/txt/csv/json/yaml/xml/xlsx/pptx/eml）。

## 2. Converter 接口（可插拔契约）

```text
class Converter(Protocol):
    def convert(self, raw_bytes: bytes, format: str, filename: str) -> str:
        """任意通用格式原始字节 → Markdown IR。

        失败/空产物 MUST 抛异常（携带原因），不得返回空串或伪造内容。
        """
        ...
```

实现：
- `MarkitdownConverter`：主选，包装 markitdown `MarkItDown.convert()`；对应 extras `[xlsx,pptx]`。
- `YamlAdapter`：pyyaml 解析 → dict → 复用 JSON 转换路径。
- `NoopConverter`：占位，供未来 pandoc/tika 等价替换（替换行为由契约测试把关，FR-036）。

替换约束：任何新转换器实现须通过转换层契约测试（给定输入 → 期望 Markdown IR / chunk_type / 定位标识）。

## 3. 注册表查询 API（分发契约）

```text
class FormatHandlerRegistry:
    @classmethod
    def build(cls) -> "FormatHandlerRegistry": ...
        # 构建失败（导入错误/重复 format/重复扩展名）MUST 抛异常 → 调用方启动失败

    def detect_format(self, filename: str, content: bytes | None) -> str:
        # 扩展名 → 条目；.json/.yaml/.yml 先内容嗅探 OpenAPI 特征，
        # 命中归 openapi，未命中回落通用 json/yaml；converter 依赖缺失时抛异常。
        # 未识别扩展名/不支持格式 → 抛 RegistryFormatError（含可接受格式清单）。

    def parse_content(self, content, fmt: str, filename: str) -> list[dict]:
        # native → parser_factory(content)；converter → converter.convert → 切片。

    def is_binary(self, fmt: str) -> bool: ...
```

（`graph_extractor(fmt)` 查询自 010 起退役，图提取分派见 `graph-extractor-registry.md`。）

## 4. 四处分发点委托契约

| 分发点 | 现状位置 | 委托目标 |
|--------|----------|----------|
| 格式检测 | `api/knowledge_sources.py::_detect_format` | `registry.detect_format` |
| 解析分派 | `services/ingestion_service.py::_parse_content` | `registry.parse_content` |
| 二进制声明 | `parsers/text_extractor.py::BINARY_FORMATS` | `registry.is_binary` |
| 图提取分派 | ~~`services/ingestion_service.py::_extract_graph_relations`~~ | ~~`registry.graph_extractor`~~ → **superseded by 010 `GraphExtractorRegistry.discover`** |

- `BINARY_FORMATS` 常量由注册表 `binary` 声明取代（FR-005）。
- 错误消息由注册表统一生成（FR-007），四处文案一致。

## 5. 启动失败契约（回退安全）

- 注册表 `build()` 在应用/服务启动时执行一次。
- 构建失败（依赖导入失败、重复条目、非法条目）MUST 抛出异常 → **启动失败**，不静默回落旧 if/elif（FR-001 单一事实源、宪法 VI）。
- 注册表为只读单例，无运行时可变状态。

## 6. 错误消息契约

- `RegistryFormatError`：不支持格式/未识别扩展名，消息含可接受格式清单（由注册表条目生成）。
- 转换器不可用：消息指明 `converter unavailable: <format>`（fail fast，FR-003）。
- 空产物/转换失败：消息说明原因，不产生空 Chunk（FR-015）。
