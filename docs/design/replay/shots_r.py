import json,time
from restore_rec import *
from playwright.sync_api import sync_playwright
st["trip"]=True; st["stage"]=5
L=[("import_photo_trip","读取照片并还原行程","4 个停留点、33 张照片"),("autoname_stops","给停留点查地名","起名 4 个点"),("tag_regions","标注城市和区县","4 个点"),("set_day_title","给每天起标题","3 天"),("fill_stop_photos","补齐景点照片","最多 6 张")]
st["evs"]=[{"id":f"e{i}","t0":time.time()-60+i,"ts":time.time()-59+i,"name":n,"label":l,"args":"","state":"ok","summary":s} for i,(n,l,s) in enumerate(L)]
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1600,"height":1000},device_scale_factor=2); errs=[]
    pg.on("pageerror",lambda e:errs.append(str(e)))
    pg.route("**/tok/api/**",api); pg.route("**/tok/",lambda r:r.fulfill(status=200,content_type="text/html",body=html))
    pg.goto("http://127.0.0.1:9/tok/"); pg.wait_for_timeout(2000)
    pg.click("#home_restore"); pg.wait_for_timeout(3000); pg.screenshot(path="shots/r_a.png")
    pg.click("#rp_next"); pg.wait_for_timeout(3000); pg.screenshot(path="shots/r_b.png")
    pg.click("#rp_next"); pg.wait_for_timeout(3500); pg.screenshot(path="shots/r_c.png")
    print(errs); b.close()
