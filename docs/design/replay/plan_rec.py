import json,time,sys
from lib import *
P=U+"_demo/out/plan/"
snaps={k:json.load(open(P+f"{k}.snap.json")) for k in ["init","R6","R10","R12","R13","R14","R14w","R23w"]}
CHAT=json.load(open(P+"chat.json")); SH=json.load(open(P+"share_prev.json"))
for _k,_v in SH.items(): _v["html"]=_v["html"].replace("苏州3日-录制","苏州3日"); _v["png_ok"]=True; _v["gif_ok"]=True; _v["key_ok"]=False
html=open(U+"_page_rp.html",encoding="utf-8").read()
st={"evs":[],"key":"init","trip":False,"msgs":[]}
def api(r):
    k=r.request.url.split("/api/")[1].split("?")[0]
    try: b=json.loads(r.request.post_data or "{}")
    except Exception: b={}
    if k=="activity": body={"events":st["evs"],"now":time.time()}
    elif k=="restore_mode": body={"auto":False}
    elif k=="new_trip": st["trip"]=True; body={"message":"已新建行程"}
    elif k=="trips": body={"trips":[{"slug":"suzhou","name":"苏州3日","active":True,"kind":"plan"}] if st["trip"] else [],"active":"suzhou" if st["trip"] else None,"current":"suzhou" if st["trip"] else None,"single":False}
    elif k=="share_preview": body=SH.get(b.get("theme","default"),SH["default"])
    elif k in ("share_pdf",): body={"pdf":"data:application/pdf;base64,JVBERi0xLjQK"}
    elif k=="share_gif": body={"gif":"data:image/gif;base64,R0lGODlhAQABAAAAACw="}
    elif k=="cal_export": body={"message":"已生成日历文件，双击导入即可","path":"~/Documents/TripSight/苏州3日.ics"}
    elif k=="export_dir": body={"path":"~/Documents/TripSight","custom":False,"locked":False}
    elif k=="chat_history": body={"messages":st["msgs"]}
    elif k=="refine": body={"ok":True,"message":"已更新为真实路线"}
    else: body={"state":snaps[st["key"]],"rev":{"revision":len(st["key"])*10+st["trip"],"trip":"suzhou" if st["trip"] else None},"chat_status":{"connected":True,"message":""},"tools":{}}.get(k,{})
    r.fulfill(status=200,content_type="application/json",body=json.dumps(body,default=str))
if __name__=="__main__":
    L={"lookup_coords":"查询地点坐标","add_place":"添加景点","schedule_days":"排每天的行程","check_plan":"检查行程","propose_change":"生成修改提案","find_food":"按店名找餐厅","apply_proposal":"套用你确认的提案","choose_food":"记下选定的餐厅","suggest_lodging":"推荐住在哪一带","add_lodging":"记录住宿","refine_routes":"换成高德真实路线","submit_candidates":"整理攻略里的候选地点","get_weather":"查天气预报"}
    # (用户消息序号, [(工具, 说明, 之后行程快照)...])
    TURNS=[(0,[("lookup_coords","5 个景点",None),("add_place","5 个景点",None),("schedule_days","分 3 天","R6"),("check_plan","",None)]),
           (2,[("lookup_coords","3 个景点",None),("add_place","3 个景点",None),("schedule_days","重新分 3 天","R10")]),
           (4,[("propose_change","观前街挪到第 3 天最后",None),("find_food","虎丘附近午餐",None)]),
           (6,[("apply_proposal","确认码 5705",None),("choose_food","万景庭·苏式面馆","R12")]),
           (8,[("suggest_lodging","平江路附近",None)]),
           (10,[("add_lodging","全季酒店(观前街中心)","R13")]),
           (12,[("refine_routes","11 段","R14")]),
           (14,[("submit_candidates","小红书攻略 · 6 个新景点",None)])]
    rc=R(); pg=rc.pg
    pg.route("**/tok/api/**",api); pg.route("**/tok/",lambda r:r.fulfill(status=200,content_type="text/html",body=html))
    pg.goto("http://127.0.0.1:9/tok/"); rc.w(1200)
    rc.click("#home_plan",1200)
    rc.click("#trip",500); pg.evaluate("ntOpen()"); rc.w(900)
    rc.type("#nt_name","苏州3日"); rc.type("#nt_city","苏州",60); pg.fill("#nt_tv","2"); rc.w(300)
    pg.fill("#nt_sd","2026-11-07"); pg.fill("#nt_ed","2026-11-09"); rc.w(900)
    rc.click("#nt_ok",1200); pg.screenshot(path="p2.png")
    st["key"]="init"
    evs=[]; n_ev=0
    for ui,tools in TURNS:
        rc.type("#ctext",CHAT[ui]["text"],delay=12 if len(CHAT[ui]["text"])<120 else 1); rc.w(500)
        rc.click("#csend",500)
        for name,args,key in tools:
            n_ev+=1; e={"id":f"e{n_ev}","t0":time.time(),"ts":time.time(),"name":name,"label":L[name],"args":args,"state":"run"}
            evs.append(e); st["evs"]=list(evs); rc.w(900)
            e["state"]="ok"; e["ts"]=time.time(); e["summary"]=args; st["evs"]=list(evs)
            if key: st["key"]=key
            rc.w(700)
        rc.stream(CHAT[ui+1]["text"],700); rc.finish(); rc.w(1300)
        if ui==12:   # 路线换成真实路线后，页面自动查天气
            snaps["Rbusy"]=dict(snaps["R14"],weather_busy=True); st["key"]="Rbusy"; rc.w(2000); st["key"]="R14w"; rc.w(2000)
        st["msgs"]=st["msgs"]+[CHAT[ui],CHAT[ui+1]]
    st["key"]="R14w"
    pg.evaluate("document.getElementById('chat').classList.contains('hide')"); rc.w(500)
    rc.click("#cclose",600)
    for i in (1,2,0):
        rc.click(f"#tabs button:nth-child({i+1})" if pg.locator("#tabs button").count() else "body",1800)
    rc.click("#more",1200)
    rc.w(1500); pg.select_option("#sh_t","magazine"); rc.w(1500); pg.select_option("#sh_t","dopamine"); rc.w(1500); pg.select_option("#sh_t","default"); rc.w(1500)
    rc.click("#sh_pdf",1500); rc.click("#sh_gif",1500); rc.click("#sh_cal",2500); rc.w(1500)
    print(len(rc.errs),rc.errs[:2])
    rc.close()
