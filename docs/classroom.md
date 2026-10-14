# 上课模式 v0.1

## 现状与设计

原项目是 Next.js 16 / React 19 前端、FastAPI 后端、SQLite 或 PostgreSQL、Qdrant。上传会把 PDF 原文件保存在 `UPLOAD_DIR`，并在 `documents.storage_path` 记录路径；`GET /api/documents/{id}/file` 已能只读返回原文件。原 Chat 仍是 `/`。Windows 包使用 Next 静态导出，Docker 使用 standalone。仓库目前没有实际登录或用户身份验证，`SECRET_KEY` 等配置并未构成访问控制，因此本版本只适合原有的单用户本机或可信网络部署；在公网多人环境启用前，必须给课程、原文件、课堂列表、笔迹和 Chat 统一增加鉴权与权限校验。

点击 Chat 左侧「上课模式」进入 PDF 列表，再进入阅读器。PDF.js 负责页面画布和可选择的文字层（Apache-2.0）；`idb` 负责浏览器 IndexedDB（ISC）。PDF 原件绝不因笔迹而改变。笔迹用每页独立 JSON 保存，点位归一化到 `[0,1]`，保留 Pointer Events 的压力值。后端新增 `page_annotations` 表，`init_db()` 的 `create_all` 会为既有数据库补建表，旧文档无需迁移。课程删除时同步删除云端笔迹。

## 操作与离线边界

- 阅读模式：触摸滚动、翻页、缩放。选择模式：选择文字后「询问 AI」。书写模式：触控笔或鼠标落笔；手指仍用于滚动和浏览器缩放。笔迹工具有画笔、荧光笔、整笔橡皮擦、颜色、粗细、撤销/重做。撤销/重做只保留当前页的本次打开记录；重开后仍可用橡皮擦修改既有笔迹。
- 首次联网打开 PDF 后，浏览器尝试缓存整份文件。缓存成功后可断网阅读和书写；大 PDF 或 Safari 存储限制可能导致缓存失败，页面会提示。缓存按需逐份保存，没有容量上限管理。扫描版 PDF 无文字可选，v0.1 不提供 OCR。
- 每次改笔迹先写 IndexedDB，再尝试后台同步。状态分别为「本地已保存」「同步中」「已同步」「同步失败」。恢复联网后自动重试。同步是每页版本比较；409 冲突会保留本地笔迹并提示，不会覆盖云端。本版本只支持单设备离线编辑再联网同步，不自动合并多设备更改。
- 清除浏览器站点数据、使用隐私模式或设备丢失会移除尚未同步的笔迹。看到「已同步」后才表示后端已有副本。对重要笔记应备份服务端数据库与 `uploads` 目录。
- 文字选中后的提问经现有 `/api/chat/ask`，包含文档 ID、页码、选文和页面上下文；后续问题复用同一 `conversation_id`。AI 回答只显示在侧栏/抽屉，不写进 PDF。

## API 与验证

- `GET /api/classroom/documents`：现有 PDF 文档列表。
- `GET /api/classroom/documents/{id}/pages/{page}`：返回 `version`、`strokes`、`updated_at`。
- `PUT` 同一路径：提交 `base_version` 与完整笔迹。版本不匹配返回 409；非法点位、颜色、宽度、页码拒绝。单页最多 3000 笔，每笔最多 10000 点。

在 `frontend` 运行 `npm ci`、`npm run lint`、`npm run typecheck`、`npm test`、`npm run build`；另用 `NEXT_EXPORT=1 npm run build` 检查 Windows 静态导出。在仓库根运行 `python backend/scripts/run_tests.py`。手工验收：上传可选文字 PDF → 列表打开 → 笔书写 → 看到「已同步」→ 重开恢复 → 断网打开已缓存 PDF 并书写 → 联网同步 → 选字提问并连续追问 → 检查原 PDF 字节未变。另在 iPad Safari、Android Chrome 实机检查笔与手指区分、系统缩放、横竖屏抽屉和误触；自动化测试不能证明设备级掌误触效果。

## 后续

优先补齐身份验证与服务端按用户隔离，再做多设备冲突处理、PDF 缓存容量管理、OCR、笔迹导出合成 PDF。当前 Docker 前端镜像使用 Node 22 以匹配 PDF.js 依赖要求。
