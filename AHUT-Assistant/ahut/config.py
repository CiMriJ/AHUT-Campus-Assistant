"""全局常量与 WebVPN 域名加密。

安徽工业大学校外访问教务系统必须经过 vpncas 的深信服 WebVPN 隧道。
隧道地址形如：https://vpncas.ahut.edu.cn/http/<hex>/路径
其中 <hex> = "77726476706e69737468656265737421" + AES-128-CFB(host) 的十六进制。
"""
from Crypto.Cipher import AES

WEBVPN_BASE = "https://vpncas.ahut.edu.cn"
JWC_BASE = "https://jwc.ahut.edu.cn"

# 深信服 WebVPN 固定魔数 + 密钥
_VPN_MAGIC = "77726476706e69737468656265737421"  # "wrdvpnisthebest!"
_VPN_KEY = b"wrdvpnisthebest!"

CAS_HOST = "cas.paas.ahut.edu.cn"   # 统一身份认证
CAS_BASE = "https://" + CAS_HOST
JWXT_HOST = "jwxt.ahut.edu.cn"      # 正方教务管理系统
JWXT_SSO_SERVICE = "http://jwxt.ahut.edu.cn/jsxsd/sso.jsp"  # 教务系统的统一认证回调地址
PORTAL_HOST = "smart.ahut.edu.cn"   # 智慧校园门户

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 教务系统常用页面（正方 jsxsd 标准路径）
JWXT_PATHS = {
    "timetable": "/xskb/xskb_list.do",
    "grades": "/kscj/cjcx_list",
    "exams": "/xsks/xsksap_list",
    "classroom": "/cdjy/cdjy_cxKxcdlb",
}


def vpn_host_hex(host: str) -> str:
    """把真实域名加密为 WebVPN 隧道路径片段。"""
    cipher = AES.new(_VPN_KEY, AES.MODE_CFB, iv=_VPN_KEY, segment_size=128)
    return _VPN_MAGIC + cipher.encrypt(host.encode()).hex()


def vpn_url(host: str, path: str = "/", scheme: str = "http") -> str:
    """拼接经由 WebVPN 访问真实站点的完整地址。"""
    if not path.startswith("/"):
        path = "/" + path
    return f"{WEBVPN_BASE}/{scheme}/{vpn_host_hex(host)}{path}"


CAS_VPN = vpn_url(CAS_HOST, "/cas/", "https")
JWXT_VPN = vpn_url(JWXT_HOST, "/jsxsd/", "http")

# 课表时间（安徽工业大学作息，可在设置里覆盖）
PERIOD_TIMES = [
    ("1-2节", "08:00", "09:40"),
    ("3-4节", "10:00", "11:40"),
    ("5-6节", "14:00", "15:40"),
    ("7-8节", "16:00", "17:40"),
    ("9-10节", "19:00", "20:40"),
    ("11-12节", "20:50", "22:30"),
]
