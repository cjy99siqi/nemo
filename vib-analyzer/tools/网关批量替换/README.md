# 网关批量替换文件（75 台，SSH/SCP）

零依赖：调用 Windows 自带的 PuTTY（`plink.exe` / `pscp.exe`），不用装 paramiko。

## 一、准备三样东西

1. **主机清单** `hosts.csv`（每台一行，密码各不相同）

   ```csv
   ip,user,password,port
   192.168.1.101,root,这台的真实密码,22
   192.168.1.102,root,这台的真实密码,22
   ```

   - `port` 可省，默认 22；
   - 文件是 UTF-8；密码里有逗号时用引号包起来；
   - **别把这个文件传到网盘/群里**，用完删掉。

2. **文件清单** `files.json`（所有网关用同一份）

   ```json
   [
     {"src": "C:/部署包/网关/collector.conf",
      "dst": "/opt/gateway/conf/collector.conf",
      "mode": "644", "owner": "root:root",
      "restart": "systemctl restart gateway-collector"},
     {"src": "C:/部署包/网关/gateway.bin",
      "dst": "/opt/gateway/bin/gateway.bin", "mode": "755"}
   ]
   ```

   - `dst` 是**每台机器上的同一个绝对路径**；
   - `mode`/`owner`/`restart` 都可省；`restart` 是这台机器替换完所有文件后执行一次。

3. PuTTY（本机已装）：`C:\Program Files\PuTTY\plink.exe`、`pscp.exe`。

## 二、按顺序执行（默认只检查，不加 `--apply` 什么都不写）

```powershell
cd tools\网关批量替换

# 1) 解析清单，不连设备
python deploy.py --hosts hosts.csv --files files.json --list

# 2) 演练：连上去看目标在不在、目录可不可写、md5 是多少
python deploy.py --hosts hosts.csv --files files.json

# 3) 先拿一台试（第一次连会提示主机密钥，见下）
python deploy.py --hosts hosts.csv --files files.json --apply --only 192.168.1.101

# 4) 全量，8 台并发
python deploy.py --hosts hosts.csv --files files.json --apply --jobs 8
```

**首次连接**：plink 没缓存过该主机密钥时会拒连。两种处理：

- 推荐：先手动连一台 `plink -ssh root@192.168.1.101`，确认指纹后输 `y`；
- 内网可信、想全自动：加 `--accept-hostkey`（会自动记录指纹，等于放弃首次校验，**确认网段可信再用**）。

## 三、每台机器上实际做了什么

1. `cp -p dst dst.bak.<时间戳>`（存在才备份）；
2. 上传到 `dst.dshnew.<时间戳>`；
3. `mv -f` 原子替换 + `chmod`/`chown`；
4. `md5sum` 与本地比对，不一致算失败；
5. 全部文件成功后再执行 `restart` 命令。

失败不会中途留半个文件（先传临时名再 mv）。

## 四、结果

- 屏幕每台一行 `OK` / `FAIL` + 原因；
- 自动写 `deploy_log_<时间>.csv`（UTF-8 带 BOM，Excel 直接打开）；
- 退出码：全成功 0，有失败 1 —— 方便串到别的脚本里。

## 五、出问题怎么办

| 现象 | 原因/处理 |
|---|---|
| `连接失败: ... not cached` | 首次连接没确认主机密钥，见上面「首次连接」 |
| `连接失败: Access denied` | hosts.csv 里该台密码错，或 sshd 关了密码登录 |
| `目录不可写` | 目标目录权限不够，换 `user` 或先 `chmod` 目录 |
| `sftp: No such file` / `No space left` | 目标目录不存在或磁盘满 |
| 想回滚 | 每台 `ls /opt/gateway/conf/*.bak.*`，`cp` 回原文件名即可 |
| 只想重试失败的那几台 | 用 `--only 1.2.3.4,1.2.3.5` 指定 IP |

## 六、建议

- **先拿 1 台跑 `--apply`**，确认业务正常再全量；
- 全量前把 `--jobs` 调小（4）观察网络和网关负载，稳了再 8；
- 75 台大约 3–6 分钟（8 并发，取决于文件大小和链路）；
- 替换前最好在网关上留一个 `backup` 目录，或至少确认 `dst.bak.*` 生成成功。
