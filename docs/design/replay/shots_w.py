import json,time
from plan_rec import *
import plan_rec
from playwright.sync_api import sync_playwright
st["trip"]=True; st["key"]="R23w"
st["msgs"]=[CHAT[i] for i in range(0,len(CHAT))][:16]
L=[("lookup_coords","查询地点坐标","5 个景点"),("schedule_days","排每天的行程","分 3 天"),("check_plan","检查行程","3 天都通过检查"),("refine_routes","换成高德真实路线","11 段"),("get_weather","查天气预报","3 天")]
evs=[{"id":f"e{i}","t0":time.time()-60+i,"ts":time.time()-59+i,"name":n,"label":l,"args":a,"state":"ok","summary":a} for i,(n,l,a) in enumerate(L)]
st["evs"]=evs
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1600,"height":1000},device_scale_factor=2)
    errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
    pg.route("**/tok/api/**",api); pg.route("**/tok/",lambda r:r.fulfill(status=200,content_type="text/html",body=html))
    pg.goto("http://127.0.0.1:9/tok/"); pg.wait_for_timeout(2500)
    pg.screenshot(path="shots/w0.png")
    pg.click("#home_plan"); pg.wait_for_timeout(4500)
    pg.screenshot(path="shots/w1.png")
    pg.click("#more"); pg.wait_for_timeout(2500); pg.screenshot(path="shots/w2.png")
    print(errs)
    b.close()
