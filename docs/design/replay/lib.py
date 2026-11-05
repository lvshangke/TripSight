import json,time,os
from playwright.sync_api import sync_playwright
U="/mnt/user-data/uploads/Desktop/tripcore/"
INIT = r"""
(()=>{
 const c=document.createElement('div');c.id='__cur';c.style.cssText='position:fixed;left:-50px;top:-50px;width:22px;height:22px;z-index:2147483647;pointer-events:none;transition:left .45s cubic-bezier(.2,.7,.2,1),top .45s cubic-bezier(.2,.7,.2,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))';
 c.innerHTML='<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 2l7 19 3-8 8-3z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
 const r=document.createElement('div');r.id='__rip';r.style.cssText='position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:3px solid #c4553a;z-index:2147483646;pointer-events:none;opacity:0';
 const add=()=>{document.body.appendChild(c);document.body.appendChild(r)};
 if(document.body)add();else document.addEventListener('DOMContentLoaded',add);
 window.__mv=(x,y)=>{c.style.left=x+'px';c.style.top=y+'px'};
 window.__clk=(x,y)=>{r.style.left=x+'px';r.style.top=y+'px';r.style.transition='none';r.style.opacity='.9';r.style.transform='scale(.4)';requestAnimationFrame(()=>requestAnimationFrame(()=>{r.style.transition='all .45s ease-out';r.style.opacity='0';r.style.transform='scale(1.3)'}))};
 const of=window.fetch.bind(window);
 window.fetch=(u,o)=>{ if(String(u).includes('api/chat')&&o&&o.method==='POST'){
   const enc=new TextEncoder();
   const body=new ReadableStream({start(ctl){window.__ctl=ctl;window.__enc=enc}});
   return Promise.resolve(new Response(body,{status:200,headers:{'Content-Type':'text/event-stream'}})); }
   return of(u,o)};
 window.__emit=t=>{window.__ctl.enqueue(window.__enc.encode('data: '+JSON.stringify({choices:[{delta:{content:t}}]})+'\n\n'))};
 window.__done=()=>{window.__ctl.enqueue(window.__enc.encode('data: [DONE]\n\n'));window.__ctl.close()};
})();
"""
class R:
    def __init__(s, w=1600, h=1000, out="vid"):
        s.p=sync_playwright().start(); s.b=s.p.chromium.launch()
        s.ctx=s.b.new_context(viewport={"width":w,"height":h},record_video_dir=out,record_video_size={"width":w,"height":h})
        s.ctx.add_init_script(INIT); s.pg=s.ctx.new_page(); s.errs=[]; s.pg.on("pageerror",lambda e:s.errs.append(str(e)))
    def w(s,ms): s.pg.wait_for_timeout(ms)
    def center(s,sel):
        bb=s.pg.locator(sel).first.bounding_box(); return bb["x"]+bb["width"]/2, bb["y"]+bb["height"]/2
    def click(s,sel,pause=450):
        x,y=s.center(sel); s.pg.evaluate(f"__mv({x},{y})"); s.w(520); s.pg.evaluate(f"__clk({x},{y})")
        s.pg.locator(sel).first.click(force=True); s.w(pause)
    def move(s,sel):
        x,y=s.center(sel); s.pg.evaluate(f"__mv({x},{y})"); s.w(500)
    def type(s,sel,text,delay=55):
        x,y=s.center(sel); s.pg.evaluate(f"__mv({x},{y})"); s.w(450); s.pg.evaluate(f"__clk({x},{y})"); s.pg.locator(sel).first.click(force=True)
        s.pg.keyboard.type(text,delay=delay)
    def stream(s,text,cps=70):
        i=0; step=max(1,int(cps/20))
        while i<len(text):
            s.pg.evaluate("t=>__emit(t)",text[i:i+step]); i+=step; s.w(50)
    def finish(s): s.pg.evaluate("__done()")
    def close(s):
        s.ctx.close(); s.b.close(); s.p.stop()
