# -*- coding: utf-8 -*-
"""deploy.py 离线自检：用假 Runner 模拟一台网关，验证执行顺序和判定，不连真机。"""
import hashlib
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("deploy", os.path.join(HERE, "deploy.py"))
dep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dep)

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


SRC = os.path.join(HERE, "_selftest_src.bin")
with open(SRC, "wb") as fp:
    fp.write(b"hello gateway\n")
MD5 = hashlib.md5(b"hello gateway\n").hexdigest()


class FakeRunner:
    """记录调用；remote_md5 可改，用来模拟校验失败。"""

    def __init__(self, exists=True, writable=True, remote_md5=None, connect_ok=True):
        self.exists = exists
        self.writable = writable
        self.remote_md5 = remote_md5 or MD5
        self.connect_ok = connect_ok
        self.calls = []

    def run_plink(self, host, cmd, timeout=None):
        self.calls.append(cmd)
        if cmd == "echo __DSH_OK__":
            return (0, "__DSH_OK__\n", "") if self.connect_ok else (1, "", "not cached")
        if "echo EXISTS" in cmd:
            return (0, ("EXISTS" if self.exists else "MISSING") + "\n" +
                    ("W_OK" if self.writable else "NO_W") + "\n", "")
        if "md5sum" in cmd:
            return (0, "%s  %s\n" % (self.remote_md5, "/x"), "")
        return (0, "", "")

    def upload(self, host, src, dst_tmp):
        self.calls.append("UPLOAD %s" % dst_tmp)
        return (0, "", "")


HOST = {"ip": "10.0.0.1", "user": "root", "password": "x", "port": 22}
FILES = [{"src": SRC, "dst": "/opt/gw/app.conf", "mode": "644", "owner": "", "restart": ""}]

print("[演练：不写入]")
r = FakeRunner(exists=True)
ip, ok, det = dep.deploy_one(r, HOST, FILES, apply=False)
check(ok, "演练结果 OK")
check(any("存在→将备份" in d for d in det), f"提示会备份（{det}）")
check(not any(c.startswith("UPLOAD") for c in r.calls), "演练不上传")
check(not any("cp -p" in c for c in r.calls), "演练不备份")

print("\n[写入：备份→上传→mv→md5]")
r = FakeRunner(exists=True)
ip, ok, det = dep.deploy_one(r, HOST, FILES, apply=True, backup=True)
check(ok, f"写入结果 OK（{det}）")
joined = " | ".join(r.calls)
check("UPLOAD" in joined, "调用了上传")
check("cp -p" in joined, "备份了原文件")
check("mv -f" in joined, "用 mv 原子替换")
check("chmod 644" in joined, "设置了权限")
check("md5sum" in joined, "做了 md5 校验")

print("\n[目标不存在：不备份，直接新建]")
r = FakeRunner(exists=False)
ip, ok, det = dep.deploy_one(r, HOST, FILES, apply=True, backup=True)
check(ok, f"新建结果 OK（{det}）")
check(not any("cp -p" in c for c in r.calls), "不存在时不执行备份")

print("\n[md5 不一致：判失败]")
r = FakeRunner(remote_md5="0" * 32)
ip, ok, det = dep.deploy_one(r, HOST, FILES, apply=True, backup=True)
check(not ok, f"md5 不一致判失败（{det}）")

print("\n[目录不可写：跳过该文件]")
r = FakeRunner(writable=False)
ip, ok, det = dep.deploy_one(r, HOST, FILES, apply=True, backup=True)
check(not ok, f"不可写判失败（{det}）")
check(not any(c.startswith("UPLOAD") for c in r.calls), "不可写时不上传")

print("\n[连不上：直接失败]")
r = FakeRunner(connect_ok=False)
ip, ok, det = dep.deploy_one(r, HOST, FILES, apply=True, backup=True)
check(not ok, f"连接失败判失败（{det}）")

print("\n[后置重启命令]")
r = FakeRunner(exists=True)
ip, ok, det = dep.deploy_one(r, HOST, FILES, apply=True, backup=True, after="systemctl restart gw")
check("systemctl restart gw" in r.calls, "执行了后置命令")

try:
    os.remove(SRC)
except OSError:
    pass

print()
print("共 %d 项断言，失败 %d 项" % (len(RESULTS), RESULTS.count(False)))
print("RESULT:", "ALL PASS" if all(RESULTS) else "FAIL")
sys.exit(0 if all(RESULTS) else 1)
