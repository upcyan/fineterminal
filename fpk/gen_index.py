#!/usr/bin/env python3
"""把 www 源文件内联生成单文件 index.html。

背景：fnOS 桌面网关环境下 <script src>/<link> 子资源请求不落服务器（疑似
代理或 webview 缓存/拦截），只有 HTML 主请求稳定可达。因此把 CSS/JS 全部
内联为单请求页面。

用法: python3 gen_index.py
输入: www-src/index.template.html + www-src/{app.js, vendor/*}
输出: fpk/app/www/index.html
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "www-src")
OUT = os.path.join(HERE, "app/www/index.html")

DIAG = """<script>
/* 内联诊断：JS 可执行时向服务端打点（服务端日志可见），错误显示红色横幅 */
(function(){
  try { new Image().src = "/app/fineterminal/__jsok?t=" + Date.now(); } catch(e){}
  window.onerror = function(m,s,l){
    try{
      var b=document.getElementById("errbar");
      if(!b){b=document.createElement("div");b.id="errbar";
        b.style.cssText="position:fixed;top:0;left:0;right:0;z-index:9999;background:#c0392b;color:#fff;font:12px monospace;padding:6px 10px;white-space:pre-wrap;";
        document.body.appendChild(b);}
      b.textContent += "JS错误: "+m+" @"+String(s||"?").split("/").pop()+":"+l+"\\n";
    }catch(e){}
    return false;
  };
})();
</script>"""


def read(rel):
    with open(os.path.join(SRC, rel), "r", encoding="utf-8") as f:
        return f.read()


def main():
    tpl = read("index.template.html")

    # 内联诊断脚本放到 <head> 之后
    if "</head>" in tpl:
        tpl = tpl.replace("</head>", DIAG + "\n</head>", 1)

    # 替换 <script src="X"></script> 为内联内容
    def inline_script(m):
        src = m.group(1).split("?")[0]
        if src.startswith("http"):
            return m.group(0)
        path = os.path.join(SRC, src)
        if not os.path.isfile(path):
            sys.exit("missing: " + path)
        return "<script>\n/* inlined: %s */\n%s\n</script>" % (src, read(src))

    tpl = re.sub(r'<script src="([^"]+)"></script>', inline_script, tpl)

    # 替换 <link rel="stylesheet" href="vendor/...css"> 为内联 style
    def inline_css(m):
        href = m.group(1).split("?")[0]
        if href.startswith("http"):
            return m.group(0)
        path = os.path.join(SRC, href)
        if not os.path.isfile(path):
            sys.exit("missing: " + path)
        return "<style>/* inlined: %s */\n%s</style>" % (href, read(href))

    tpl = re.sub(r'<link rel="stylesheet" href="([^"]+)">', inline_css, tpl)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(tpl)
    print("generated %s (%d bytes)" % (OUT, len(tpl.encode())))


if __name__ == "__main__":
    main()
