# OpenShell 整合驗證紀錄

後續進度：已新增可執行的 gRPC client/interceptor 與 Agent、Keyper operator MCP，
詳見 [bridge 接線說明](openshell-bridge.zh-TW.md)。以下保留第一階段的驗證範圍；
真實 gateway 與 sandbox 驗收已完成，見 [後續驗收紀錄](live-validation.zh-TW.md)。

驗證日期：2026-10-29。這是來源介面與本機環境驗證，尚未完成真實 gateway 或 sandbox 的端對端測試。

## 可重跑的檢查

```powershell
uv run --locked python -m approval_lab.openshell_probe
```

若 uv 的共用快取無法存取，但已完成 `uv sync`，可直接使用：

```powershell
.\.venv\Scripts\python.exe -m approval_lab.openshell_probe
```

報告寫入 `.approval-lab/openshell-probe.json`（不進 Git）。檢查工具只讀取版本、Docker daemon 狀態與 WSL 清單，下載固定 commit 的四份官方來源並計算 SHA-256；不啟動 gateway、不寫入政策、不安裝系統元件。子程序在 Windows 使用 `CREATE_NO_WINDOW`。

也可用 `--source-dir C:/path/to/OpenShell` 檢查既有原始碼而不下載；此模式標示為未確認版本的本機 checkout。退出碼 0 只代表所選來源符合檢查的文字介面條件，**不表示環境已可執行或整合成功**。工具不是 protobuf 編譯器，也不驗證實際 handler 行為。報告中的 `live_integration_verified` 固定為 false。

## 已確認的官方介面

固定來源 commit：`4d4c15c133d40a50234ce9d2d198e5ba79b9553e`。官方 latest 文件與 main 可能更新，部署時必須另外比對實際執行版本。

| 來源 | 確認結果 | 整合意義 |
| --- | --- | --- |
| [RPC allowlist](https://github.com/NVIDIA/OpenShell/blob/4d4c15c133d40a50234ce9d2d198e5ba79b9553e/crates/openshell-gateway-interceptors/src/routes.rs) | `UpdateConfig` 可攔截 | 在 `validate` 階段檢查最終提案 |
| [公開 API](https://github.com/NVIDIA/OpenShell/blob/4d4c15c133d40a50234ce9d2d198e5ba79b9553e/proto/openshell.proto) | 請求包含 `sandbox`、`workspace_scope`、`annotations`、`merge_operations`、`expected_resource_version` | 有核准參照的候選通道與樂觀併發控制；還須實際捕捉 gateway 傳入的 protobuf JSON |
| [攔截器協定](https://github.com/NVIDIA/OpenShell/blob/4d4c15c133d40a50234ce9d2d198e5ba79b9553e/proto/gateway_interceptor.proto) | `Describe`、`Evaluate`、principal、validate payload | 需要獨立 gRPC 服務、協定協商與呼叫者驗證；MCP stdio 不能直接當 gRPC 攔截器 |
| [網路規則](https://github.com/NVIDIA/OpenShell/blob/4d4c15c133d40a50234ce9d2d198e5ba79b9553e/proto/sandbox.proto) | 規則包含 endpoints 與 binaries；endpoint 可指定多個 ports、L7 等欄位 | 核准不能只比對網域與單一 port，忽略其他權限範圍 |

[官方 Gateway Interceptors 文件](https://docs.nvidia.com/openshell/extensibility/gateway-interceptors) 說明：validate 可拒絕操作；`current_state` 尚未填入方法專屬狀態；post_commit 不能阻止已完成的操作。因此尚不能直接把目前的 `NetworkChange` 當作完整政策更新的授權證據。

## 下一階段的實作邊界

1. 建立獨立 gRPC interceptor，採 `validate`、`fail_closed`、`binding_policy=exact` 或 `allowlist`；MCP 仍只提供申請及查詢。
2. 在真實 gateway 捕捉去識別的 `UpdateConfig` evaluation，確認 annotations 的傳遞、workspace、principal 與 JSON 欄位正規化。annotations 只攜帶核准參照，不是證明；禁止相信使用者送來的 `approved=true`。
3. 擴充核准資料模型，綁定 gateway/租戶、workspace、sandbox、請求人、非零預期版本、完整操作及 binary/endpoint 範圍。人工審閱畫面必須顯示同一份內容。不能從核准的一條網路規則推論可任意替換整份 policy。
4. 先限縮為明確支援的一種增量操作，拒絕全域更新、混合設定變更及未知操作；確認 rule 名稱碰撞、現行政策讀取與版本競爭的處理方式。
5. 核准消耗後 gateway 若失敗，先維持不可重用；定義與 OpenShell request ID 的持久映射及重試語意，不能因客戶端宣稱失敗就恢復核准。
6. 列舉其他可能建立或改變網路政策的路徑，包括 CreateSandbox 與政策草稿核准，確認拒絕或同等治理；只攔 UpdateConfig 不能宣稱不存在繞過。

上述是待實測設計，不是可直接部署的 gateway 設定。目前沒有新增會放行真實政策的 adapter。

## 本機環境與已執行結果

- Python 虛擬環境可執行；既有 MCP demo 成功。
- PATH 找不到 `openshell`、`docker`；`wsl --list --quiet` 回報 WSL 未安裝。
- 固定來源的七項介面檢查全部通過，四份來源雜湊可在 JSON 報告核對。
- `pytest` 共 50 個測試通過；為避開既有系統暫存目錄權限問題，使用全新工作區內暫存目錄：

```powershell
$testTemp = Join-Path (Get-Location) ('.pytest_cache/run-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest -q --basetemp $testTemp
```

尚未執行：gRPC 協商與認證、真實政策提交、sandbox 核准前後連線、其他更新路徑的繞過測試。這些需要可連線的 OpenShell 部署；本次未安裝 WSL/Docker 或變更 Windows 系統設定。

## 真實環境驗收

使用可控制的 HTTPS 測試服務；`api.example.com` 只作範例，不能當作預期可連線的服務。

| 測試 | 必須觀察到的結果 |
| --- | --- |
| 未核准送出政策更新 | gateway 拒絕，sandbox 仍無法連線 |
| 核准精確操作 | gateway 成功提交，sandbox 回報新政策已載入，指定程式才能連到測試服務 |
| 修改 host、port、binary、workspace 或版本 | 拒絕，沒有放寬其他權限 |
| 過期、重放、並發提交 | 不得產生額外授權；重試結果符合已定義的單次操作語意 |
| interceptor 停機、逾時或認證失敗 | 政策更新 fail closed |
| 直接 CLI/RPC、全域政策、建立 sandbox、草稿核准 | 無法繞過部署宣告的人工核准邊界 |

## Keyper 之後需要提供的資料

目前維持 `MockIdentity`，只作本機測試。接入前需要由 Keyper 團隊確認：

- 使用的產品/SDK 版本、支援平台、登入與核准流程、測試帳號或測試環境。
- 身分證明格式與官方驗證方式，包括信任根/公鑰取得、issuer、audience、效期、撤銷與金鑰輪替。
- challenge/nonce 與完整操作指紋如何綁定，如何避免重放或把另一筆登入結果用於本次核准。
- 穩定的人員識別碼與核准角色來源；成功驗證身分不等於具有核准權限。
- 逾時、取消、裝置不可用及稽核欄位的規格；文件範例必須去除真實憑證。

在這些資料到齊前，不新增臆測的 Keyper endpoint、token 或驗證邏輯。
