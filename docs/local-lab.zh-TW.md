# 獨立資料夾執行方式

新增 OpenShell 協定接線測試可使用 `run-local-lab.ps1 -OpenShell`；
它啟動短暫的 loopback gRPC 測試服務，不安裝 OpenShell runtime。
真實 gateway 接線與私有 Keyper MCP 見 [bridge 說明](openshell-bridge.zh-TW.md)。

這個模式將專案副本、Python 套件、uv 快取、暫存與測試報告集中在專案的
`.approval-lab/isolated-run/`。它仍使用目前的 Windows 使用者權限，**不是作業系統或網路安全沙箱**。
它適合執行此專案的本機模擬，不應拿來執行不信任的程式。

## 一鍵執行

需要已安裝 Python 3.11+ 與 uv；腳本優先借用原專案 `.venv` 所指向的基礎 Python，
但不修改該環境、不下載另一套 Python、不要求管理員權限。

從專案根目錄執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-local-lab.ps1
```

`ExecutionPolicy Bypass` 僅作用於這次子程序，不會呼叫 `Set-ExecutionPolicy` 或修改永久原則。
若公司政策禁止執行，應遵守管理政策，不要修改登錄或系統安全設定。

要另外下載固定版本的官方來源並檢查介面：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-local-lab.ps1 -ProbeUpstream
```

第一次會連線至套件來源下載鎖定依賴。uv 使用系統信任的 TLS 憑證，不停用憑證驗證。
此模式不封鎖網路；`-ProbeUpstream` 會另外連線 GitHub 並讀取本機工具狀態。

## 產物與操作

每次執行會建立新的時間戳記資料夾，不覆蓋舊的測試資料；uv 快取由本專案的各次執行共用。

```text
.approval-lab/isolated-run/
  uv-cache/
  <時間戳記與隨機碼>/
    project/       只複製 src、tests、docs、examples 與建置所需檔案
    venv/          專用套件環境
    temp/          demo 暫存資料庫與 pytest 暫存
    data/          手動操作用資料庫
    reports/       setup.log、demo.log、tests.log、tests.xml、summary.json
```

不複製 `.git`、`.env`、原來的虛擬環境或既有資料庫。這些產物已由 `.gitignore` 排除。
demo 資料庫會在正常結束後刪除；要保留核准及稽核資料，請用下面的手動操作。
失敗時也會保留當次的報告與 `summary.json`，其中 `success=false`；不會清理其他資料夾。

使用執行完成後輸出的實際路徑：

```powershell
$run = 'C:\完整專案路徑\.approval-lab\isolated-run\實際執行目錄'
$labPython = Join-Path $run 'venv\Scripts\python.exe'
$db = Join-Path $run 'data\approvals.sqlite3'
$request = & $labPython -m approval_lab.cli --db $db request --sandbox sandbox-demo --domain api.example.com --port 443 --reason 'Local mock test' | ConvertFrom-Json
& $labPython -m approval_lab.cli --db $db approve $request.request_id --identity demo-approver
& $labPython -m approval_lab.cli --db $db apply $request.request_id --sandbox sandbox-demo --domain api.example.com --port 443
& $labPython -m approval_lab.cli --db $db audit $request.request_id
```

所有 `apply` 都仍是模擬。腳本只設定自己的程序環境變數並在結束時還原，
不啟用環境、不修改系統 PATH、不啟動服務，也不安裝 WSL、Docker 或 OpenShell。
基礎 Python、uv 執行檔與 Windows 信任庫來自原本電腦，並非全部自包含。
Windows 防毒、系統紀錄與 OneDrive 同步仍可能產生活動，因此不能保證系統零寫入。
目前專案位於 OneDrive，測試產物也可能被同步；不要在測試資料內放真實憑證或個資。

## 真正 OpenShell 的下一階段

實際 gateway、interceptor 與 sandbox 測試應放在一台可丟棄的遠端 Linux 測試機。
建立、付費或登入遠端機器不包含在這份腳本內。

1. 準備符合 [OpenShell 支援矩陣](https://docs.nvidia.com/openshell/latest/reference/support-matrix) 的 Linux 測試機，記錄版本並建立還原點。
2. 只傳送專案原始碼，或 clone 已提交的專案版本；不傳送本機 `.env`、資料庫、SSH 金鑰或整個 OneDrive。
3. 在測試機內依 [官方安裝文件](https://docs.nvidia.com/openshell/latest/about/installation/) 安裝執行環境，鎖定可比對的 OpenShell 版本。
4. 避免掛載 Windows 工作區、個人家目錄或正式 Docker socket；gateway 與操作端點不公開到網際網路，僅使用受控管理通道。
5. 在完成真實 interceptor 後，依 [整合驗證紀錄](integration-verification.zh-TW.md) 的驗收表測試核准前後連線、版本競爭與繞過路徑。
6. 匯出去識別的報告；測試結束後由管理者銷毀測試機及其磁碟。

這個本機腳本不代表已完成第 3–5 步；Keyper 仍使用 mock。

## 清理

確認沒有測試程序使用環境後，可在檔案總管刪除當次的時間戳記資料夾，保留報告副本即可。
若不再需要任何測試產物，可刪除 `.approval-lab/isolated-run`；這會移除專用環境與快取，
不會解除安裝原本的 Python 或 uv。下次執行會重新建立所需資料。
