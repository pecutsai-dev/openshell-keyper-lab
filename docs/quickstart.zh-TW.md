# 本機模擬核准流程

若希望使用專案副本及獨立套件、快取與暫存目錄，請先看
[獨立資料夾執行方式](local-lab.zh-TW.md)。

第一版已實作 MCP、SQLite 核准服務與獨立核准 CLI。使用模擬身分，尚未連接
Keyper 或 OpenShell，也不會真的開放 sandbox 網路。

## 一次跑完整示範

在專案目錄執行：

```powershell
uv sync --locked
uv run python -m approval_lab.demo
uv run pytest -q
```

示範會建立暫存 SQLite，透過真正的 MCP stdio 建立申請，再由另一個 CLI 程序
模擬人類核准，驗證「未核准被拒、無權限身分被拒、修改 port 被拒、正確變更
成功一次、重複使用被拒」。測試另涵蓋過期、並行消耗與服務故障。

## 手動操作

```powershell
uv run approval-lab request --sandbox sandbox-demo --domain api.example.com --port 443 --reason "Test API access"
```

將回傳的 request ID 填入 `$requestId`，先看完整變更再核准：

```powershell
$requestId = "貼上剛才的 request_id"
uv run approval-lab status $requestId
uv run approval-lab approve $requestId --identity demo-approver
uv run approval-lab apply $requestId --sandbox sandbox-demo --domain api.example.com --port 443
uv run approval-lab apply $requestId --sandbox sandbox-demo --domain api.example.com --port 443
uv run approval-lab audit $requestId
```

最後一次 apply 應回傳 `already_consumed` 並以 exit code 1 結束。
`demo-viewer` 沒有核准權限；`demo-approver` 是明確標示的測試身分，並非真正登入。
預設有效期限是申請後 5 分鐘。

MCP 只提供 `request_network_access` 與 `get_approval_status`。啟動方式：

```powershell
uv run approval-lab-mcp
```

它以 stdio 等待 MCP 客戶端，不會開啟網頁。核准、拒絕與消耗均不提供給 Agent
作為 MCP 工具。MCP 客戶端與操作 CLI 必須使用同一個資料庫路徑；不同工作目錄
時請明確設定 `--db` 或 `APPROVAL_LAB_DB` 的絕對路徑。

目前 apply 只回傳模擬結果。真正強制檢查仍須接進 OpenShell 執行路徑，下一階段
要驗證的操作、攔截點與核准消耗時機見 [整合說明](openshell-integration.md)。
