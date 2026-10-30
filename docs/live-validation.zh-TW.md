# 真實 OpenShell 驗收與本機 Linux VM

2026-10-29 已在資料夾內的 Ubuntu VM 完成真實 OpenShell v0.1.6 驗收。
使用官方 gateway、sandbox runtime 與 supervisor 執行檔、Docker-backed sandbox，
以及兩個獨立 MCP stdio 連線。Keyper 身分目前仍使用明確開啟的 mock。

## 實際結果

| 項目 | 結果 |
| --- | --- |
| Windows Python 3.14.7 | 73 個測試通過 |
| Ubuntu Python 3.12.3，實跑 `prepare-linux-lab.sh` | 73 個測試通過 |
| 真實 gateway 啟動並接受 interceptor manifest | 通過 |
| 真實 sandbox 進入 Ready | 通過 |
| 直接提交未核准的 UpdateConfig | PERMISSION_DENIED |
| 核准前連線到 example.com:443 | curl exit 7，無法連線 |
| 私有 operator MCP 模擬人員核准，Agent MCP 提交 | gateway 回覆政策版本 2 |
| sandbox 確認政策已載入 | active_version=2 |
| 核准後 HTTPS 連線，保留 TLS 憑證驗證 | curl exit 0，取得 Example Domain 頁面 |
| 連線至未核准的 www.iana.org:443 | curl exit 7，無法連線 |
| 再次透過 MCP 提交同一核准 | 拒絕 |

可核對的 [真實驗收報告](evidence/openshell-v0.1.6-live.json)、
[Linux JUnit 報告](evidence/linux-tests.xml) 與
[環境、官方執行檔來源及已驗證程式碼雜湊](evidence/validation-environment.json) 已保留。
`example.com` 是本次公開網站探測結果，不是我們控制的測試服務；後續正式驗收應換成自有服務。

## 隔離方式

本機狀態放在 `.approval-lab/portable-vm/`，QEMU 11.1.0 使用 TCG 軟體模擬、2 vCPU、
2048 MiB 記憶體。Ubuntu 24.04.4 使用 Linux 6.8.0-138-generic 與 Docker 29.1.3。
Windows 沒有啟用 WSL/Hyper-V、安裝 Docker 或新增系統服務，原專案 Python 環境未加裝 VM 工具。
QEMU、磁碟、快取、測試金鑰都留在 lab 資料夾；VM 沒有掛載 Windows 個人目錄。

SSH 只轉送到 Windows loopback `127.0.0.1:22322`。gateway 綁在 VM 內 loopback，
驗收使用 local-dev 身分與私有 Unix socket interceptor；這是隔離實驗環境的設定。
正式部署需配置真正 gateway 認證、TLS、操作者與 Agent 的權限隔離。

本機 DNS 整合只綁 `127.0.0.1:10053`，使用 Windows 既有的正常 resolver；
`network` 指令僅把公開信任根憑證同步到 VM，沒有匯出私鑰或修改 Windows 信任庫。

## 重新使用已建立的 VM

先選擇已安裝 portable-vm 工具的專用 Python。這台電腦目前已驗證的路徑是：

```powershell
$labPython = '.\.approval-lab\isolated-run\20261029-140933-0e39e6fe\venv\Scripts\python.exe'
& $labPython scripts/control-local-vm.py start
```

等待 VM 啟動後：

```powershell
& $labPython scripts/control-local-vm.py status
& $labPython scripts/control-local-vm.py network
& $labPython scripts/control-local-vm.py exec 'bash /home/lab/run-live.sh'
```

`run-live.sh` 是本次 VM 中已建立的驗收入口，會建立新的私有報告目錄，執行後停止它自己的
gateway/interceptor 並要求刪除測試 sandbox。查看輸出的 evidence directory 即可取得當次報告。
不要把另一份 VM 的 SSH host key 默默替換；控制工具會比對本次 provisioning 保存的 known_hosts。

結束後可關閉 VM：

```powershell
& $labPython scripts/control-local-vm.py stop
```

此控制工具使用已 provision 的磁碟與 SSH 金鑰。來源 ZIP 不包含 VM 磁碟、私鑰、
安裝快取或私有執行狀態，因此不會把你的 lab 登入金鑰交給同事。
若專用 Python 已刪除，可用 `run-local-lab.ps1 -OpenShell -PortableVM` 重建工具環境，
再把 `$labPython` 換成新報告中的 Python 路徑。

## 在另一台 Linux 測試機驗收

安裝符合官方要求的 Docker，以及 Python 3.11+、uv；依官方 SHA-256 校驗下載並解開
v0.1.6 的 gateway、sandbox runtime、supervisor 執行檔，以及官方 `openshell-0.1.6-py3-none-any.whl`。
然後從專案根目錄執行：

```bash
bash scripts/prepare-linux-lab.sh
bash scripts/build-live-workload.sh
# 使用 prepare-linux-lab.sh 最後輸出的專用 Python 路徑：
/path/to/lab/venv/bin/python scripts/validate-live-openshell.py \
  --bin-dir /path/to/verified/openshell-binaries \
  --sdk-wheel /path/to/openshell-0.1.6-py3-none-any.whl
```

workload image 在官方 Ubuntu 基礎映像加入 curl；supervisor image 沿用官方 runtime，
加入此測試機的公開信任根，以支援需要自訂企業 CA 的環境。沒有關閉 TLS 驗證。
workload 透過 OpenShell 提供的 `SSL_CERT_FILE` 取得每次 runtime 的 CA bundle，
再與測試機公開信任根組合供 curl 使用。

## 已確認的版本競爭限制

OpenShell 非同步儲存 denial analysis 也會更新 sandbox resource version。
若這發生在審閱之後，UpdateConfig 可能回覆
`INTERNAL: persist policy revision failed: resource version conflict`。
本版不會修改已核准操作或恢復已消耗核准；須重新讀取版本並建立新的申請、重新核准。

驗收腳本先完成拒絕連線探測，等待觀察事件的版本更新穩定，再建立審閱內容。
這個等待只發生在核准之前；核准後的 sandbox/workspace/binary/host/port/版本全部保持綁定。
正式多 Agent／高頻更新情境仍需另外設計政策版本與重試語意。

## Keyper 下一步

Agent MCP 與私有 Keyper MCP 的 schemas、設定範本及
`verify_decision(assertion, context)` 接口已保留，見 [bridge 接線說明](openshell-bridge.zh-TW.md)。
真實 Keyper 驗證器需要綁定服務提供的 challenge，驗證身分、效期及可信核准角色。
目前通過的真實 OpenShell 驗收使用 mock approver，尚未驗證 Keyper 產品的登入或簽章。
