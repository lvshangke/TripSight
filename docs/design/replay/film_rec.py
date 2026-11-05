import json,time
from lib import *
P=U+"_demo/out/"
snap=json.load(open(P+"vid.snap.json")); hb=json.load(open(P+"film.hb.json")); M=json.load(open(P+"film.msgs.json"))
hb["videos"]=7; hb["folder"]="~/Pictures/台州"; hb["name"]="台州"
html=open(U+"_page_rp.html",encoding="utf-8").read()
st={"n":0,"go":False}
STY=json.load(open(P+"film.styles.json"))
def api(r):
    k=r.request.url.split("/api/")[1].split("?")[0]
    if k=="activity": body={"events":[],"now":time.time()}
    elif k=="restore_mode": body={"auto":False}
    elif k=="video_scan": body={"message":M["scan"],**M["groups"]}
    elif k=="video_cut": st["go"]=True; st["n"]=0; body={"started":True}
    elif k=="video_status":
        if not st["go"]: body={"state":"idle"}
        else:
            st["n"]+=1; tot=11
            body={"state":"run","done":st["n"],"total":tot} if st["n"]<tot else {"state":"ok","message":"已生成旅行短片：~/Documents/TripSight/短片/旅行短片.mp4（51 秒，720×1280，用了 7 段）\n字幕、片段清单和封面图在同一个文件夹。\n路线卡用了高德底图和驾车路径示意。\n没有配乐，需要的话在剪映里再加。","video":"video/film.mp4?t=1","seconds":51}
    elif k=="hb_style_preview": body=STY.get(json.loads(r.request.post_data or "{}").get("style"),STY["手账"])
    elif k=="export_dir": body={"path":"~/Documents/TripSight","custom":False,"locked":False}
    elif k=="trips": body={"trips":[{"slug":"x","name":"台州","active":True,"kind":"restore"}],"active":"x","current":"x","single":False}
    elif k=="chat_history": body={"messages":[]}
    else: body={"state":snap,"hb_state":hb,"rev":{"revision":5,"trip":"x"},"chat_status":{"connected":True,"message":""},"tools":{}}.get(k,{})
    r.fulfill(status=200,content_type="application/json",body=json.dumps(body,default=str))
T0=time.time(); rc=R(out="vfilm"); pg=rc.pg; pg.route("**/tok/api/**",api)
pg.route("**/tok/video/film.mp4*",lambda r:r.fulfill(status=200,content_type="video/webm",body=open("film.webm","rb").read())); pg.route("**/tok/",lambda r:r.fulfill(status=200,content_type="text/html",body=html))
pg.goto("http://127.0.0.1:9/tok/"); rc.w(2000)
rc.click("#home_restore",1500); pg.screenshot(path="f_a.png")
for i in range(4):
    if pg.locator("#hb_vid").is_visible(): break
    rc.click("#rp_next",1500)
rc.w(2500)
pg.select_option("#hb_style","杂志"); rc.w(2200); pg.select_option("#hb_style","手账"); rc.w(1800)
pg.evaluate("document.querySelector('#hb_vid').scrollIntoView({block:'start',behavior:'smooth'})"); rc.w(1800)
pg.screenshot(path="f_c.png")
rc.click("#hv_scan",2800); pg.screenshot(path="f_d.png")
rc.click("#hv_t",600); pg.select_option("#hv_t","60"); rc.w(900)
rc.click("#hv_bm",700); rc.click("#hv_go",800); pg.screenshot(path="f_e.png"); rc.w(13500)
pg.evaluate("document.querySelector('#hv_prev').scrollIntoView({block:'center',behavior:'smooth'})"); rc.w(1200)
pg.screenshot(path="f_f.png")
TP=time.time()-T0; rc.click(".vdvid",300); rc.w(54000); open("tplay.txt","w").write(str(TP))
print(rc.errs); rc.close()
