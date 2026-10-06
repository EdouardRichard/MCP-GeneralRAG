# recall_memory Additive Extensions v2

013只扩展既有recall_memory的显式增强选择，不新增工具、不将Distiller接入检索状态图。search_knowledge/get_evidence/list_knowledge_domains与start_work契约沿原版本。

新增可选StrictBool参数：include_linked=false、include_context=false。未传/false保持012原输入语义与原输出字段/排序；域policy允许不等于客户端请求增强。原错误/数量/超时仍适用，三个历史知识工具schema保持byte兼容。新增memory-tool schema独立发布v2并验证旧原样例，不编辑012历史契约充作唯一新版本。

include_linked=true仍需consolidation_enabled/config/link_expansion_enabled与当前版本三闸证明；否则返回原合法候选并显示enhancement.link_expansion_status=disabled/not_available。应用时applied，失败时degraded；每节点same-scope/active/complete/valid/必要支持复验，总limit≤50、原3秒timeout及内容预算不变。历史读取参数不允许扩展复活退出节点。

证明由services/consolidation_gate.py按 [gate-proof.md](gate-proof.md) 加载CONSOLIDATION_GATE_REGISTRY_PATH指定的只读登记；路径缺省即无证明。报告013.2/固定字节hash/同scope/当前gate_binding/有效期/完整三闸和candidate_expansion variant必须全通过；direct报告不能授权扩展。生产不导入eval、不取请求或正文路径、不自动安装报告。坏证明、撤销或版本/数据变更均not_available+确定性原因，并返回原合法直接候选；新增IO等待≤100ms且计入原超时，旧flags=false路径不加载登记。

include_context=true仅最终选择后增加memory.context（digest/keywords/version/source），按剩余预算显示，不影响候选/排序/正文/证据。无合法值可省略context，context_status=unavailable/partial/available；不现场调用模型。

仅至少一个增强flag=true时增加根enhancement字段：link_expansion_status、linked_count、context_status、degradation_reasons。旧调用不添字段，新输出Schema只增加这些可选结构，原必填/错误shape不变。原因来自确定代码状态。

代码边界：mcp/recall_memory.py参数/序列化契约、MemoryService透传、MemoryReader受闸扩展/最终显示。契约测flags缺省/单独/组合和旧样例一致；集成测reader只读/scope/预算/降级。014 search_knowledge记忆感知与高级work包不在范围。
