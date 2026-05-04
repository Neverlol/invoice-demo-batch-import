# 2026-05-04｜沈阳客户录屏前功能验证与展示建议

## 1. 验证目的

今天录屏面向沈阳客户，目标不是证明系统“全自动开票”，而是证明：

1. 助理可以在 Windows 工作台中完成材料导入、草稿复核、批量模板、税局预览前执行记录闭环。
2. 系统能识别常见材料，但所有自动识别结果都需要人工复核。
3. 系统只到税局预览页，不自动最终开具。
4. 出现问题时，可以通过执行记录回看卡在哪一步。

## 2. 本轮本地验证结果

### 2.1 代码与核心功能测试

已通过：

```text
py_compile: app.py / extraction_pipeline.py / ocr.py / llm_adapter.py / source_documents.py / lean_workbench.py / batch_runner.py / sync_center
unit tests: 65 tests OK
UI rendering tests: 7 tests OK
```

关键页面 smoke：

```text
/         200  terminal-logo=True  css=20260503-assistant-copy
/ledger   200  terminal-logo=True  css=20260503-assistant-copy
/profiles 200  terminal-logo=True  css=20260503-assistant-copy
```

云端 sync center health：

```text
status: ok
elapsed: 0.284s
total_events: 373
total_cases: 66
total_tenants: 1
total_seller_profiles: 7
total_buyer_profiles: 34
total_line_profiles: 20
```

### 2.2 LLM 配置诊断

当前本机 workspace 诊断结果：

```text
LLM enabled: False
provider: empty
api_key_configured: False
ready: False
issue: LLM is disabled.
```

结论：

- 本机当前不能代表 Windows 私密配置下的 MiMo / MiniMax 真实调用表现。
- 本轮可验证本地 OCR、规则解析、失败兜底、页面和模板链路。
- 若 Windows 端已安装私密配置，需要在 Windows 端单独做一次真实 LLM ping / 图片识别计时。

## 3. 新增测试材料

测试材料目录：

```text
deliverables/demo-validation-20260504/
```

包含：

```text
case_a_clear_invoice_screenshot.png
case_b_platform_batch_screenshot.png
case_c_weak_oral_text.txt
case_d_blur_low_contrast_boundary.png
platform_order_01.png
platform_order_02.png
validation_result.json
platform_batch_two_images_result.json
```

## 4. 图片 / 截图识别边界

### Case A：清晰单张开票截图

结果：

```text
OCR engine: tesseract (chi_sim+eng)
耗时: 3.704s
buyer: 辽宁恒润电力科技有限公司
tax_id: 91210102MABWM3X12T
line: 代理记账和税务申报 / 500.00 / 3%
strategy: rules_only
```

判断：

- 清晰截图在本地 OCR 下可用。
- 仍需要复核，因为 OCR 把“数量：1”识别成了“数量：|”，虽然最终草稿仍能生成。

### Case B：平台截图批量，两张独立图片

结果：

```text
OCR engine: tesseract (chi_sim+eng)
耗时: 8.854s
platform_request_count: 2
batch items: 2
export template: 0 error / 0 warning
```

识别出的两条：

```text
1. 黑龙江源速商贸有限公司 / 91230102MA1CDKE47Y / 13.80 / 餐费
2. 哈尔滨星河传媒有限公司 / 91230102MAEMEM2C2M / 14.80 / 餐费
```

注意：

- 第二条原始测试税号设计为 `91230102MAEMEM2G2M`，OCR 识别成了 `91230102MAEMEM2C2M`。
- 该错误仍是 18 位合法格式，所以模板校验不会阻断。
- 因此录屏时必须强调：税号、金额、购买方名称必须由助理复核，不能承诺图片识别 100% 自动准确。

### Case C：弱口语自然语言文本

输入：

```text
帮辽宁恒润开个票，普票，代理记账和税务申报，金额五百，税号 91210102MABWM3X12T，税率按 3 个点。
```

本机无 LLM 时结果：

```text
buyer: empty
tax_id: 91210102MABWM3X12T
line: 个点 / 500 / 3%
strategy: rules_only
```

判断：

- 无 LLM 时，弱口语文本不是适合录屏展示的强项。
- 如果 Windows 端 LLM 正常，理论上这类输入应由 LLM 补强；但今天录屏前必须先在 Windows 端实测。
- 若没有实测通过，不建议在客户视频里演弱口语自动识别。

### Case D：模糊低对比截图

结果：

```text
OCR 耗时: 6.248s
buyer 被误识别为：江宁但酒电力科技有限会司
tax_id 正确
line 可生成
```

判断：

- 模糊 / 低对比截图能产生草稿，但购买方名称可能错。
- 这类材料应该展示为“系统可生成待复核草稿”，不能展示为“自动准确识别”。

## 5. 大模型解析能力当前结论

本轮不能确认真实 MiMo / MiniMax 线上调用是否更快或更稳，因为当前本机没有 LLM 私密配置。

代码层面的改进边界：

1. 图片识别现在优先支持 `vision_extract_invoice`：有图片且 LLM 可用时，图片可直接交给视觉大模型结构化识别。
2. 如果本地 OCR 可用，则无 LLM 也能处理清晰截图。
3. LLM 调用失败不会导致整个草稿流程崩掉，会记录 warning / metric，并回退到规则或待补全。
4. 前台超时已有短超时控制：
   - 文本结构化默认上限约 8s
   - 图片 OCR 默认上限约 12s
   - 视觉结构化默认上限约 18s
   - adapter 总 timeout cap 约 25s

今天录屏前必须在 Windows 端确认：

```text
LLM 配置是否 ready
真实图片识别是否成功
单张图片耗时是否可接受
失败时页面是否进入待补全而不是崩溃
```

## 5.1 批量模式规则更新

录屏和现场培训时，以用户是否勾选“批量开具发票”为唯一判断：

```text
未勾选批量模式：
  始终按单张发票处理；即使上传多个文件 / 多张图片，也视为同一张发票的材料，并进入 LLM / 视觉识别链路。

勾选批量模式：
  才进入批量处理；图片按“一张图一张子草稿”处理，缺字段进入待补全。
```

不要再向客户解释为“系统会自动判断是否批量”。

## 6. 今天录屏建议

### 推荐录屏主线：稳妥版 8-10 分钟

1. 打开工作台首页
   - 展示 Neverlol logo、税局连接、当前主体、客户档案缓存。
   - 说清楚：系统只到预览，不自动最终开具。

2. 识别当前税局主体 / 加载档案
   - 如果没有税局登录，可只展示按钮和状态，不强演税局。
   - 说明提交前会核对税局主体与销售方是否一致。

3. 演示清晰文字或 Excel/PDF 材料生成草稿
   - 选择稳定材料，不建议一上来演弱口语。
   - 展示草稿页：购买方、明细、税率、赋码、预校验。

4. 展示草稿复核
   - 修改一个字段，然后保存。
   - 强调：系统建议只作辅助，最终以复核为准。

5. 下载税局 Excel 模板
   - 展示模板生成成功。
   - 不必打开过多 Excel 细节，避免录屏冗长。

6. 演示平台截图批量
   - 使用两张清晰平台截图。
   - 勾选“批量开具发票”。
   - 展示批量页 Sheet 1 / Sheet 2 / Sheet 3。
   - 强调一张截图一张草稿，缺字段会进入待补全。

7. 展示执行记录
   - 打开 `/ledger`。
   - 说明这里可以回看每一单走到了哪一步：识别、复核、模板、税局执行、人工确认。

8. 展示主体与档案
   - 说明系统可信来源：税局历史明细、active 档案、正常/正数/未作废/未红冲。
   - 说明执行记录不会污染客户档案。

### 不建议今天视频里强演

除非 Windows 端刚刚实测通过，否则不建议演：

1. 弱口语自然语言自动识别。
2. 模糊低对比截图自动识别。
3. 最终税局提交到真实开票按钮。
4. 大批量 10+ 图片一次识别。
5. LLM 长等待场景。

### 可以诚实表达的边界

建议说法：

```text
图片和截图可以辅助识别，但税号、购买方、金额这些关键字段仍然需要复核。
系统的目标不是替代助理判断，而是把材料整理成可检查的草稿，并把错误、缺字段和税局退回留痕。
```

## 7. Windows 端录屏前快速检查清单

录屏前请确认：

```text
1. 双击 02_START_INVOICE_ASSISTANT.bat 能打开工作台。
2. 首页 logo、文案、左侧菜单显示正常。
3. Ctrl + F5 后仍正常。
4. 打开 /ledger 正常。
5. 打开 /profiles 正常。
6. 上传一份稳定文字/Excel/PDF，可生成草稿。
7. 上传一张清晰图片，观察耗时和是否生成草稿。
8. 若启用 LLM，确认一次真实图片识别耗时。
9. 批量两张平台截图能生成 2 条批量草稿。
10. 下载税局 Excel 能成功。
```

## 8. 录屏结论建议

今天视频应传递：

```text
这是一个现场助理可以用来减少整理和返工的开票工作台。
它已经能覆盖材料导入、草稿复核、批量模板、主体档案、执行记录。
它不会自动最终开具，关键字段仍由助理复核。
5 月 8 日现场重点是部署、培训、真实材料测试和流程磨合。
```
