# -*- coding: utf-8 -*-
"""网关批量替换文件（75 台，SSH/SCP，零依赖：调用 PuTTY 的 plink/pscp）。

用法（默认只检查不写入，必须显式 --apply 才动设备）：

    # 1) 先看清单能不能解析
    python deploy.py --list

    # 2) 演练：连上去看目标文件在不在、本地 md5 是什么，不写入
    python deploy.py --hosts hosts.csv --files files.json

    # 3) 先拿一台试
    python deploy.py --hosts hosts.csv --files files.json --apply --only 192.168.1.5

    # 4) 全量
    python deploy.py --hosts hosts.csv --files files.json --apply

hosts.csv 表头：ip,user,password[,port]
files.json  ：[{"src": "本地文件", "dst": "/远程/路径", "mode": "644", "owner": "root:root"}]

每台的动作：备份原文件（.bak.<时间戳>）→ 上传到临时名 → mv 原子替换 →
chmod/chown → md5 校验 → 可选重启命令。
"""
import argparse
import csv
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

IS_WIN = os.name == "nt"
DEFAULT_PLINK = r"C:\Program Files\PuTTY\plink.exe"
DEFAULT_PSCP = r"C:\Program Files\PuTTY\pscp.exe"


def _no_window():
    """Windows 下别弹黑框。"""
    if not IS_WIN:
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": si, "creationflags": 0x08000000}


class Runner:
    def __init__(self, plink, pscp, timeout=25, accept_hostkey=False, verbose=False):
        self.plink = plink
        self.pscp = pscp
        self.timeout = timeout
        self.accept_hostkey = accept_hostkey
        self.verbose = verbose
        self._pwfile = None

    def _pw_path(self, password):
        """把密码写到临时文件，用 -pwfile 传（避免出现在命令行/进程列表）。"""
        if self._pwfile is None:
            fd, path = tempfile.mkstemp(prefix="dsh_pw_", suffix=".txt")
            os.close(fd)
            self._pwfile = path
        with open(self._pwfile, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(str(password))
        return self._pwfile

    def _env(self):
        return dict(os.environ, PLINK_PROTOCOL="ssh")

    def run_plink(self, host, cmd, timeout=None):
        target = "%s@%s" % (host["user"], host["ip"])
        base = [self.plink, "-ssh", "-batch", "-no-antispoof",
                "-pwfile", self._pw_path(host["password"]),
                "-P", str(host.get("port", 22)), target, "--", cmd]
        r = subprocess.run(base, capture_output=True, timeout=timeout or self.timeout,
                           env=self._env(), **_no_window())
        out = (r.stdout or b"").decode("utf-8", "replace")
        err = (r.stderr or b"").decode("utf-8", "replace")
        if r.returncode != 0 and "not cached" in (out + err).lower() and self.accept_hostkey:
            # 第一次连接：不带 -batch，回车 y 把主机密钥记到注册表，然后重试
            self._cache_hostkey(host)
            r = subprocess.run(base, capture_output=True, timeout=timeout or self.timeout,
                               env=self._env(), **_no_window())
            out = (r.stdout or b"").decode("utf-8", "replace")
            err = (r.stderr or b"").decode("utf-8", "replace")
        if self.verbose:
            print("    $ %s\n      rc=%s %s" % (cmd, r.returncode, (out + err).strip()[:200]))
        return r.returncode, out, err

    def _cache_hostkey(self, host):
        target = "%s@%s" % (host["user"], host["ip"])
        cmd = [self.plink, "-ssh", "-no-antispoof",
               "-pwfile", self._pw_path(host["password"]),
               "-P", str(host.get("port", 22)), target, "--", "echo ok"]
        try:
            subprocess.run(cmd, input=b"y\n", capture_output=True, timeout=self.timeout,
                           env=self._env(), **_no_window())
        except Exception:
            pass

    def upload(self, host, src, dst_tmp):
        target = "%s@%s:%s" % (host["user"], host["ip"], dst_tmp)
        cmd = [self.pscp, "-batch", "-pwfile", self._pw_path(host["password"]),
               "-P", str(host.get("port", 22)), src, target]
        r = subprocess.run(cmd, capture_output=True, timeout=max(self.timeout, 120),
                           env=self._env(), **_no_window())
        out = (r.stdout or b"").decode("utf-8", "replace")
        err = (r.stderr or b"").decode("utf-8", "replace")
        return r.returncode, out, err


def md5_local(path):
    h = hashlib.md5()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_hosts(path):
    hosts, seen = [], set()
    with open(path, encoding="utf-8-sig", newline="") as fp:
        rdr = csv.DictReader(fp)
        need = {"ip", "user", "password"}
        if not need.issubset({(c or "").strip().lower() for c in (rdr.fieldnames or [])}):
            raise SystemExit("hosts.csv 表头必须包含 ip,user,password（可选 port）")
        for row in rdr:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            ip = row.get("ip")
            if not ip or ip.startswith("#") or ip in seen:
                continue
            seen.add(ip)
            try:
                port = int(row.get("port") or 22)
            except ValueError:
                port = 22
            hosts.append({"ip": ip, "user": row.get("user") or "root",
                          "password": row.get("password") or "", "port": port})
    return hosts


def load_files(path):
    with open(path, encoding="utf-8-sig") as fp:
        items = json.load(fp)
    if isinstance(items, dict):
        items = items.get("files") or []
    out = []
    for it in items:
        src = it.get("src")
        dst = it.get("dst")
        if not src or not dst:
            raise SystemExit("files.json 每项都要有 src 和 dst：%r" % (it,))
        out.append({"src": src, "dst": dst, "mode": str(it.get("mode") or ""),
                    "owner": str(it.get("owner") or ""), "restart": str(it.get("restart") or "")})
    return out


def deploy_one(runner, host, files, apply, backup=True, after=""):
    """返回 (ip, ok, [明细])。"""
    details = []
    label = "%s@%s" % (host["user"], host["ip"])
    rc, out, err = runner.run_plink(host, "echo __DSH_OK__")
    if "__DSH_OK__" not in out:
        return host["ip"], False, ["连接失败: %s" % (err or out).strip()[:160]]
    for f in files:
        dst = f["dst"]
        src = f["src"]
        md5s = md5_local(src)
        base = os.path.basename(dst)
        tmp = "%s.dshnew.%d" % (dst, int(time.time()))
        q_dst = shlex.quote(dst)
        q_tmp = shlex.quote(tmp)
        # 看目标是否存在 + 目录可写
        rc, out, err = runner.run_plink(
            host, "[ -e %s ] && echo EXISTS || echo MISSING; [ -w %s ] && echo W_OK || echo NO_W"
            % (q_dst, shlex.quote(os.path.dirname(dst) or "/")))
        exists = "EXISTS" in out
        writable = "W_OK" in out
        if not writable:
            details.append("%s: 目录不可写（%s）" % (base, os.path.dirname(dst)))
            continue
        if not apply:
            details.append("%s: %s%s" % (base, "存在→将备份" if exists else "不存在→新建",
                                         "" if backup else "（不备份）"))
            continue
        ts = time.strftime("%Y%m%d_%H%M%S")
        steps = []
        if exists and backup:
            steps.append("cp -p %s %s.bak.%s" % (q_dst, q_dst, ts))
        rc, out, err = runner.upload(host, src, tmp)
        if rc != 0:
            details.append("%s: 上传失败 %s" % (base, (err or out).strip()[:160]))
            continue
        mv = "mv -f %s %s" % (q_tmp, q_dst)
        if f["mode"]:
            mv += " && chmod %s %s" % (f["mode"], q_dst)
        if f["owner"]:
            mv += " && chown %s %s" % (f["owner"], q_dst)
        steps.append(mv)
        steps.append("md5sum %s" % q_dst)
        cmd = "set -e; " + " && ".join(steps)
        rc, out, err = runner.run_plink(host, cmd)
        if rc != 0:
            details.append("%s: 替换失败 %s" % (base, (err or out).strip()[:160]))
            continue
        remote_md5 = ""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and len(parts[0]) == 32:
                remote_md5 = parts[0]
                break
        if remote_md5 and remote_md5 != md5s:
            details.append("%s: md5 不一致（本地 %s / 远程 %s）" % (base, md5s[:8], remote_md5[:8]))
            continue
        details.append("%s: OK %s" % (base, "已备份" if (exists and backup) else "新建"))
    if apply and after:
        rc, out, err = runner.run_plink(host, after)
        details.append("后置命令: %s" % ("OK" if rc == 0 else "失败 " + (err or out).strip()[:120]))
    ok = all(("OK" in d or "新建" in d or "存在→将备份" in d or "不存在→新建" in d)
             and "失败" not in d and "不一致" not in d and "不可写" not in d for d in details)
    return host["ip"], ok, details


def main():
    ap = argparse.ArgumentParser(description="网关批量替换文件（SSH/SCP，基于 PuTTY plink/pscp）")
    ap.add_argument("--hosts", default="hosts.csv", help="IP/账号/密码清单 CSV")
    ap.add_argument("--files", default="files.json", help="要替换的文件清单 JSON")
    ap.add_argument("--apply", action="store_true", help="真的写入（不加则只检查）")
    ap.add_argument("--only", default="", help="只处理这些 IP（逗号分隔），先拿一台试")
    ap.add_argument("--jobs", type=int, default=8, help="并发台数（默认 8）")
    ap.add_argument("--timeout", type=int, default=25, help="单条命令超时秒（默认 25）")
    ap.add_argument("--no-backup", action="store_true", help="不备份原文件（不建议）")
    ap.add_argument("--after", default="", help="每台替换完成后执行的命令，如重启服务")
    ap.add_argument("--accept-hostkey", action="store_true",
                    help="首次连接自动接受主机密钥（内网可信时用）")
    ap.add_argument("--plink", default=DEFAULT_PLINK)
    ap.add_argument("--pscp", default=DEFAULT_PSCP)
    ap.add_argument("--list", action="store_true", help="只解析清单并打印，不连设备")
    ap.add_argument("--log", default="", help="日志 CSV 路径（默认 deploy_log_时间.csv）")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    # 相对路径按当前目录解析（脚本可能在别的目录被调用）
    hosts_path = os.path.abspath(args.hosts)
    files_path = os.path.abspath(args.files)
    if not os.path.isfile(hosts_path):
        raise SystemExit("找不到清单：%s" % hosts_path)

    hosts = load_hosts(hosts_path)
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        hosts = [h for h in hosts if h["ip"] in want]
    if args.list:
        print("网关 %d 台（只解析，不连设备）：" % len(hosts))
        for h in hosts:
            print("  %-16s %s:%s" % (h["ip"], h["user"], h["port"]))
        return 0

    if not os.path.isfile(files_path):
        raise SystemExit("找不到文件清单：%s" % files_path)
    files = load_files(files_path)

    print("网关 %d 台，待替换文件 %d 个，并发 %d，模式：%s"
          % (len(hosts), len(files), args.jobs, "写入" if args.apply else "只检查(演练)"))
    for f in files:
        if not os.path.isfile(f["src"]):
            raise SystemExit("源文件不存在：%s" % f["src"])
        print("   %s  →  %s   md5=%s" % (f["src"], f["dst"], md5_local(f["src"])[:12]))

    if not hosts:
        print("没有匹配的网关（检查 --only）")
        return 2

    for p in (args.plink, args.pscp):
        if not os.path.isfile(p):
            raise SystemExit("找不到 %s，用 --plink/--pscp 指定 PuTTY 路径" % p)

    runner = Runner(args.plink, args.pscp, args.timeout, args.accept_hostkey, args.verbose)
    log_path = args.log or ("deploy_log_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    t0 = time.time()
    rows, ok_n = [], 0
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = {ex.submit(deploy_one, runner, h, files, args.apply,
                          not args.no_backup, args.after): h for h in hosts}
        for fut in as_completed(futs):
            h = futs[fut]
            try:
                ip, ok, details = fut.result()
            except Exception as e:
                ip, ok, details = h["ip"], False, ["异常: %s" % e]
            ok_n += 1 if ok else 0
            flag = "OK " if ok else "FAIL"
            print("[%s] %-16s %s" % (flag, ip, "；".join(details)[:200]))
            rows.append([time.strftime("%Y-%m-%d %H:%M:%S"), ip, "OK" if ok else "FAIL",
                         " | ".join(details)])
    try:
        with open(log_path, "w", encoding="utf-8-sig", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["时间", "IP", "结果", "明细"])
            w.writerows(rows)
        print("\n日志：%s" % os.path.abspath(log_path))
    except Exception as e:
        print("日志写入失败：%s" % e)

    cost = time.time() - t0
    print("完成：成功 %d / %d，用时 %.1fs%s"
          % (ok_n, len(hosts), cost, "（演练，未写入）" if not args.apply else ""))
    return 0 if ok_n == len(hosts) else 1


if __name__ == "__main__":
    sys.exit(main())
