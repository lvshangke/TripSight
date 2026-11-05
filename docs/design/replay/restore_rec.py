import json,time,sys
from lib import *
names=["s0_empty","s1_import","s2_named","s3_regions","s4_titles","s5_photos"]
snaps=[json.load(open(U+f"_demo/out/{n}.snap.json")) for n in names]
hbs=[json.load(open(U+f"_demo/out/{n}.hb.json")) for n in names]
EX=json.load(open(U+"_demo/out/restore_extra.json")); STY=json.load(open(U+"_demo/out/restore_styles.json"))
html=open(U+"_page_rp.html",encoding="utf-8").read()
st={"evs":[],"auto":False,"stage":0,"trip":False}
def api(r):
    k=r.request.url.split("/api/")[1].split("?")[0]
    try: b=json.loads(r.request.post_data or "{}")
    except Exception: b={}
    if k=="activity": body={"events":st["evs"],"now":time.time()}
    elif k=="restore_mode":
        if "auto" in b: st["auto"]=b["auto"]
        body={"auto":st["auto"]}
    elif k=="trip_new_restore": st["trip"]=True; body={"message":"已新建恢复行程「旧手机」"}
    elif k=="hb_albums": body=EX["albums"]
    elif k=="hb_preview": body=EX["hn"] if b.get("start_date") else EX["all"]
    elif k=="hb_style_preview": body=STY.get(b.get("style"),STY["手账"])
    elif k=="hb_export": body={"message":"手册已生成：~/Documents/TripSight/旧手机-手册\n用浏览器打开其中的 index.html；cards/ 里是每天一张 3:4 图，caption.txt 是文案草稿，发布要用户自己操作。"}
    elif k=="export_dir": body={"path":"~/Documents/TripSight","custom":False,"locked":False}
    elif k=="trips": body={"trips":[{"slug":"x","name":"旧手机（演示）","active":True,"kind":"restore"}] if st["trip"] else [],"active":"x" if st["trip"] else None,"current":"x" if st["trip"] else None,"single":False}
    else: body={"state":snaps[st["stage"]],"hb_state":hbs[st["stage"]],"rev":{"revision":st["stage"]+1,"trip":"x"},"chat_status":{"connected":True,"message":""},"chat_history":{"messages":[]},"restore_context":{}}.get(k,{})
    r.fulfill(status=200,content_type="application/json",body=json.dumps(body,default=str))
if __name__=="__main__":
    rc=R(); pg=rc.pg
    pg.route("**/tok/api/**",api); pg.route("**/tok/",lambda r:r.fulfill(status=200,content_type="text/html",body=html))
    pg.goto("http://127.0.0.1:9/tok/"); rc.w(2200)
    rc.click("#home_restore",1200)
    rc.click("#rp_gate_btn",800); rc.type("#nr_name","旧手机"); rc.w(500); rc.click("#nr_ok",2500); pg.screenshot(path="r1.png")
    pg.select_option("#hb_src","album"); rc.w(200); rc.click("#hb_al",900)
    pg.select_option("#hb_r","1500"); rc.w(500)
    rc.click("#rp_next",3500)                                   # 先预览整个相册
    rc.move('.hbm[data-m="2024-01"]'); rc.w(900)
    rc.click("#hb_d1",300); pg.fill("#hb_d1","2024-01-18"); rc.w(500); rc.click("#hb_d2",300); pg.fill("#hb_d2","2024-01-20"); rc.w(500)
    rc.click("#hb_pv",3500)                                     # 只看这一段
    pg.screenshot(path="r4.png")
    # 自动执行 + 对助手说
    rc.click("#rp_autoc",900)
    rc.type("#ctext","把旧手机相册里 2024-01-18 到 01-20 的照片恢复成行程，按“大景区”聚，再起名、标区县、起标题、补照片，最后停在预览。",delay=38); rc.w(500)
    rc.click("#csend",600)
    evs=[]
    STEPS=[("import_photo_trip","读取照片并还原行程","album=MATE40_camera，radius_m=1500，start_date=2024-01-18，end_date=2024-01-20","已从照片还原行程：读到 33 张，聚成 4 个点",1),
       ("autoname_stops","给停留点查地名","","起名 4 个点，3 个查到了真实地名",2),
       ("tag_regions","标注城市和区县","","已标注 4 个点所在的区县",3),
       ("set_day_title","给每天起标题","","3 天都有了标题",4),
       ("fill_stop_photos","补齐景点照片","","每个景点补到最多 6 张",5)]
    rc.stream("好的，先按你选的日期读取照片并还原行程。",80)
    for i,(name,label,args,summ,stage) in enumerate(STEPS):
        e={"id":f"e{i}","t0":time.time(),"ts":time.time(),"name":name,"label":label,"args":args,"state":"run"}
        evs.append(e); st["evs"]=list(evs); rc.w(3200 if i==0 else 2600)
        st["stage"]=stage; e["state"]="ok"; e["ts"]=time.time(); e["summary"]=summ; st["evs"]=list(evs); rc.w(2600)
    rc.stream("\n\n恢复完成：4 个停留点、33 张照片（3 个点查到了真实地名，1 个仍是“区县 · 时间”）；已标注区县、给 3 天起了标题，并为每个点补到最多 6 张照片。我停在了编辑页，你看一下再决定导出。",90)
    rc.finish(); rc.w(2500); pg.screenshot(path="r5.png")
    # 编辑：翻看
    pg.evaluate("__mv(215,600)"); rc.w(400)
    for _ in range(4): pg.mouse.wheel(0,260); rc.w(700)
    rc.w(800)
    rc.click("#rp_next",2500)                                   # 下一步：导出
    rc.w(1800)
    pg.select_option("#hb_style","杂志"); rc.w(2600); pg.select_option("#hb_style","手账"); rc.w(2200)
    rc.click('.pvt button[data-k="card"]',2000); rc.click('.pvt button[data-k="page"]',1200)
    pg.evaluate("__mv(215,600)"); rc.w(400)
    for _ in range(3): pg.mouse.wheel(0,330); rc.w(600)
    rc.click("#hb_exp",2800); pg.screenshot(path="r7.png"); rc.w(3500)
    print(len(rc.errs),rc.errs[:2])
    rc.close()
