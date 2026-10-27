# -*- coding: utf-8 -*-
"""
东莞理工学院 校园网自动登录（锐捷 RG-SAM+ / eportal 认证）

用法：
    python autologin.py            守护模式：一直跑，断网就自动登录（默认）
    python autologin.py --watch    同上
    python autologin.py --check    只检查当前在线状态，不登录
    python autologin.py --grab     抓取认证参数并写入 config.ini（断网时用）
    python autologin.py --login    立即执行一次登录（不管当前是否在线）
    python autologin.py --once     检查，未在线则登录一次，然后退出

配置文件：同目录 config.ini
运行日志：同目录 login.log
"""

import os
import sys
import json
import time
import re
import socket
import configparser
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.ini")
LOG_PATH = os.path.join(HERE, "login.log")
LOG_MAX = 2 * 1024 * 1024

PORTAL_HOST = "login.dgut.edu.cn"
# 门户服务器的直连 IP：断网时 DNS 往往也跟着挂，用 IP 兜底才能把登录请求发出去
PORTAL_IP = "172.31.252.91"
PORTAL = "http://" + PORTAL_HOST + "/eportal"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 联网探测：返回 204 且无正文 = 正常联网
PROBES = [
    "http://connect.rom.miui.com/generate_204",
    "http://www.gstatic.com/generate_204",
    "http://connectivitycheck.platform.hicloud.com/generate_204",
]

# 用于捕获认证跳转（http 才会被 NAS 劫持，https 不会）
REDIRECT_PROBES = [
    "http://connect.rom.miui.com/generate_204",
    "http://www.gstatic.com/generate_204",
    "http://captive.apple.com/hotspot-detect.html",
    "http://www.baidu.com",
]


# ---------------------------------------------------------------- 输出

def _init_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg, quiet=False):
    line = "[{}] {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    if not quiet:
        try:
            print(line, flush=True)
        except Exception:
            pass
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX:
            old = LOG_PATH + ".old"
            if os.path.exists(old):
                os.remove(old)
            os.replace(LOG_PATH, old)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 配置

def read_config():
    if not os.path.exists(CONFIG_PATH):
        log("找不到配置文件: " + CONFIG_PATH)
        return None
    cp = configparser.RawConfigParser()
    try:
        cp.read(CONFIG_PATH, encoding="utf-8")
    except Exception as e:
        log("读取配置文件失败: {}".format(e))
        return None

    def g(sec, key, default=""):
        try:
            return cp.get(sec, key).strip()
        except Exception:
            return default

    cfg = {
        "userId": g("account", "userId"),
        "password": g("account", "password"),
        "service": g("account", "service"),
        "queryString": g("account", "queryString"),
    }
    try:
        cfg["interval"] = int(g("options", "interval", "15"))
    except ValueError:
        cfg["interval"] = 15

    global PORTAL_IP
    _ip = g("options", "portalIp", "")
    if _ip:
        PORTAL_IP = _ip

    if not cfg["userId"] or not cfg["password"]:
        log("config.ini 里学号或密码为空，请先填写")
        return None
    return cfg


def save_query_string(qs):
    """把抓到的 queryString 写回 config.ini（保留原有注释）。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return False

    pat = r"(?m)^\s*queryString\s*=.*$"
    line = "queryString = " + qs
    if re.search(pat, txt):
        txt = re.sub(pat, lambda m: line, txt, count=1)
    else:
        txt = txt.replace("[account]", "[account]\n" + line, 1)

    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(txt)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- HTTP

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def new_opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        NoRedirect,
    )
    op.addheaders = [("User-Agent", UA)]
    return op


def portal_bases():
    """门户地址：先用域名，域名解析失败自动改用直连 IP。"""
    bases = [PORTAL]
    ip_base = "http://{}/eportal".format(PORTAL_IP)
    if ip_base not in bases:
        bases.append(ip_base)
    return bases


def _post(op, suffix, data=b"", timeout=10, referer=None):
    """向门户发 POST；域名不通（DNS 挂了）时自动退回直连 IP。"""
    last = None
    for base in portal_bases():
        headers = {
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        if PORTAL_HOST not in base:
            headers["Host"] = PORTAL_HOST      # IP 直连必须手动带 Host
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(base + suffix, data=data,
                                     headers=headers, method="POST")
        try:
            return op.open(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except Exception as e:
            last = e
            continue
    raise last if last is not None else RuntimeError("门户地址不可用")


def portal_reachable(timeout=4):
    """门户服务器是否可达（用来区分「认证失效」和「链路中断」）。"""
    for host in (PORTAL_IP, PORTAL_HOST):
        try:
            socket.create_connection((host, 80), timeout=timeout).close()
            return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------- 状态

def net_ok(op, timeout=6):
    """True = 可以正常上网。"""
    for url in PROBES:
        try:
            r = op.open(url, timeout=timeout)
            if r.getcode() == 204:
                try:
                    body = r.read(256) or b""
                except Exception:
                    body = b""
                if len(body.strip()) == 0:
                    return True
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return False          # 被劫持 = 需要认证
            continue
        except Exception:
            continue
    return False


def grab_query_string(op, timeout=6):
    """从认证劫持中提取 index.jsp 后面的 query 串。"""
    for url in REDIRECT_PROBES:
        try:
            r = op.open(url, timeout=timeout)
            # 没有跳转：可能是 200 + JS 跳转
            try:
                body = r.read(8000) or b""
            except Exception:
                body = b""
            if body:
                text = body.decode("utf-8", "ignore") + " " + body.decode("gbk", "ignore")
                m = re.search(r"""https?://[^\s'"<>\)]+index\.jsp\?[^\s'"<>\)]+""", text)
                if m:
                    loc = m.group(0).replace("&amp;", "&")
                    return loc.split("?", 1)[1]
            continue
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location", "") or ""
                if "index.jsp" in loc.lower() and "?" in loc:
                    return loc.split("?", 1)[1]
        except Exception:
            continue
    return ""


def online_info(op, timeout=8, tries=3):
    """查在线信息。接口偶发失败，重试几次再判定为离线。"""
    for i in range(tries):
        try:
            r = _post(op, "/InterFace.do?method=getOnlineUserInfo", b"", timeout)
            j = json.loads(r.read().decode("utf-8", "ignore"))
            if str(j.get("result", "")).lower() == "success":
                return j
        except Exception:
            pass
        if i + 1 < tries:
            time.sleep(1)
    return None


# ---------------------------------------------------------------- 登录

def do_login(op, user, pwd, query_string, service=""):
    payload = {
        "userId": user,
        "password": pwd,
        "service": service,
        "queryString": query_string,
        "operatorPwd": "",
        "operatorUserId": "",
        "validcode": "",
        "passwordEncrypt": "false",
    }
    body = urllib.parse.urlencode(payload).encode("utf-8")
    try:
        r = _post(op, "/InterFace.do?method=login", body, timeout=12,
                  referer=PORTAL + "/index.jsp")
        txt = r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        try:
            txt = e.read().decode("utf-8", "ignore")
        except Exception:
            return False, "HTTP {}".format(e.code)
    except Exception as e:
        return False, "网络异常: {}".format(e)

    txt = txt.strip()
    try:
        j = json.loads(txt)
    except Exception:
        return False, "返回非 JSON: " + txt[:200]

    result = str(j.get("result", "")).lower()
    msg = j.get("message") or j.get("msg") or txt[:200]

    if result == "success":
        return True, msg
    if any(k in msg for k in ("已在线", "已经在线", "重复")):
        return True, msg
    return False, msg


# ---------------------------------------------------------------- 流程

def cmd_check():
    op = new_opener()
    info = online_info(op)
    if info:
        log("在线：{}（学号 {}，IP {}，MAC {}）".format(
            info.get("userName", "-"), info.get("userId", "-"),
            info.get("userIp", "-"), info.get("userMac", "-")))
    else:
        log("未查询到在线信息（可能已离线）")
    log("网络连通性：{}".format("正常" if net_ok(op) else "不通"))
    return 0


def cmd_grab():
    op = new_opener()
    qs = grab_query_string(op)
    if not qs:
        log("未捕获到认证参数——请确认此刻已断网（认证页面已弹出）后重试")
        return 1
    log("已捕获认证参数（{} 字符）".format(len(qs)))
    if save_query_string(qs):
        log("已写入 config.ini 的 queryString")
        return 0
    log("写入 config.ini 失败，请手动复制：")
    print(qs)
    return 1


def _resolve_qs(op, cfg):
    """优先用配置里的 queryString，其次现场抓取。"""
    if cfg.get("queryString"):
        return cfg["queryString"], "config"
    qs = grab_query_string(op)
    if qs:
        return qs, "auto"
    return "", "none"


def _try_connect(cfg):
    op = new_opener()
    qs, src = _resolve_qs(op, cfg)
    if src == "none":
        log("警告：未捕获到认证参数，登录可能失败")
        log("提示：断网后双击「5-抓取认证参数.bat」即可固化参数")
    else:
        log("使用认证参数（来源：{}）".format("配置文件" if src == "config" else "现场抓取"))

    ok, msg = do_login(op, cfg["userId"], cfg["password"], qs, cfg["service"])
    if ok:
        log("登录成功：{}".format(msg))
        time.sleep(2)
        if net_ok(new_opener()):
            log("复核通过，网络已恢复")
            return True
        log("接口返回成功但网络仍不通（可能是路由器侧问题）")
        return False

    log("登录失败：{}".format(msg))
    if "设备未注册" in str(msg) or "queryString" in str(msg).lower():
        log("该错误通常表示缺少认证参数，请断网时运行「5-抓取认证参数.bat」")
    return False


def cmd_login(cfg):
    ok = _try_connect(cfg)
    return 0 if ok else 1


def cmd_once(cfg):
    op = new_opener()
    if net_ok(op):
        log("网络正常，无需登录")
        return 0
    log("网络不通，开始登录")
    return 0 if _try_connect(cfg) else 1


def cmd_watch(cfg):
    log("守护模式启动 | 学号 {} | 检测间隔 {} 秒 | 门户 {}".format(
        cfg["userId"], cfg["interval"], PORTAL_IP))
    fail = 0
    down_since = None

    def recovered():
        """恢复正常时写一条带时长的日志。"""
        nonlocal fail, down_since
        if down_since is not None:
            secs = int(time.time() - down_since)
            log("网络已恢复正常（本次中断约 {} 分 {} 秒）".format(secs // 60, secs % 60))
        down_since = None
        fail = 0

    while True:
        try:
            op = new_opener()
            if net_ok(op):
                recovered()
                time.sleep(cfg["interval"])
                continue

            # 二次确认，避免 WiFi 瞬时抖动被误判成断网
            time.sleep(3)
            if net_ok(new_opener()):
                recovered()
                time.sleep(cfg["interval"])
                continue

            if down_since is None:
                down_since = time.time()

            # 门户都连不上 = 链路断了（DNS 也多半解析不了），登录没有意义，等它自己回
            if not portal_reachable():
                fail += 1
                wait = min(120, 10 * fail)
                log("链路中断：校园网门户不可达，判定为非认证问题，暂不登录；{} 秒后重查".format(wait))
                time.sleep(wait)
                continue

            log("认证失效：门户可达但网络被拦截，开始自动登录")
            if _try_connect(cfg):
                recovered()
                time.sleep(cfg["interval"])
            else:
                fail += 1
                wait = min(120, 10 * fail)
                log("第 {} 次失败，{} 秒后重试".format(fail, wait))
                time.sleep(wait)
        except KeyboardInterrupt:
            log("收到中断，守护退出")
            return 0
        except Exception as e:
            log("守护循环异常：{}".format(e))
            time.sleep(15)


def main():
    _init_stdout()
    mode = "watch"
    for a in [x.lower() for x in sys.argv[1:]]:
        if a in ("--check", "-c"):
            mode = "check"
        elif a in ("--grab", "-g"):
            mode = "grab"
        elif a in ("--login", "-l"):
            mode = "login"
        elif a in ("--once", "-o"):
            mode = "once"
        elif a in ("--watch", "-w"):
            mode = "watch"
        elif a in ("--help", "-h", "/?"):
            print(__doc__)
            return 0

    if mode == "check":
        return cmd_check()
    if mode == "grab":
        return cmd_grab()

    cfg = read_config()
    if not cfg:
        return 2

    if mode == "login":
        return cmd_login(cfg)
    if mode == "once":
        return cmd_once(cfg)
    return cmd_watch(cfg)


if __name__ == "__main__":
    sys.exit(main())
