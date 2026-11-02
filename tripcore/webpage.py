"""网页工作台的页面（单个自包含 HTML，地图脚本内嵌，只有底图瓦片要联网）。"""

from pathlib import Path

_ASSETS = Path(__file__).with_name("assets")

TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TripSight 工作台</title>
<style>__CSS__</style>
<style>
html,body{height:100%;margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink);background:var(--bg)}
#app{display:flex;height:calc(100% - 48px);margin-top:48px}
#side{width:var(--sw,400px);flex:none;display:flex;flex-direction:column;border-right:1px solid var(--line);background:var(--bg)}
#scroll{flex:1;overflow:auto}
#map{flex:1;min-width:0;height:100%}
.sp{flex:none;width:6px;margin:0 -3px;z-index:1500;cursor:col-resize;background:transparent;touch-action:none}
.sp:hover,.sp.on{background:rgba(196,85,58,.28)}
body.resizing{cursor:col-resize;user-select:none}
body.resizing #map{pointer-events:none}
header{padding:10px 12px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px;background:var(--paper)}
header b{flex:1;font-size:16px}
#trip{flex:1;min-width:0;font:inherit;font-size:15px;font-weight:700;padding:3px 4px;border:1px solid var(--line2);border-radius:6px;background:var(--paper);color:var(--ink)}
button{border:1px solid var(--line2);border-radius:6px;background:var(--paper);padding:4px 10px;cursor:pointer;color:var(--ink)}
button:disabled{opacity:.4;cursor:default}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}
#msg{padding:4px 12px;font-size:13px;color:var(--ink2);min-height:6px}
#msg.err{color:#b91c1c}
#nt{position:fixed;inset:0;background:#0006;z-index:3000;display:none;align-items:center;justify-content:center}
#nt.on{display:flex}
#nt form{background:var(--paper);border-radius:10px;padding:16px 18px;width:min(380px,92vw);box-shadow:0 8px 30px #0005;font-size:14px}
#nt h3{margin:0 0 10px;font-size:16px}
#nt label{display:block;margin:8px 0 2px;color:var(--ink2);font-size:13px}
#nt input,#nt select{width:100%;box-sizing:border-box;font:inherit;padding:5px 6px;border:1px solid var(--line2);border-radius:6px;background:var(--paper);color:var(--ink)}
#nt .row{display:flex;gap:8px}#nt .row>div{flex:1}
#nt .btns{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}
#nt .err{color:#b91c1c;font-size:13px;min-height:16px;margin-top:6px}
#ap{position:fixed;inset:0;background:#0006;z-index:3000;display:none;align-items:center;justify-content:center}
#ap.on{display:flex}
#ap .box{background:var(--paper);border-radius:10px;padding:16px 18px;width:min(440px,94vw);max-height:88vh;overflow:auto;box-shadow:0 8px 30px #0005;font-size:14px}
#ap h3{margin:0 0 10px;font-size:16px}
#ap .q{display:flex;gap:6px}#ap .q input{flex:1;font:inherit;padding:5px 6px;border:1px solid var(--line2);border-radius:6px}
.cand{display:block;border:1px solid var(--line);border-radius:8px;padding:7px 9px;margin:6px 0;cursor:pointer}
.cand:has(input:checked){border-color:var(--acc);background:var(--acc-soft)}
.cand input{margin-right:6px}.cand .a{font-size:12px;color:var(--ink2);margin-left:22px}
#ap .w{color:#b45309;font-size:12px;margin:6px 0}
#ap .err{color:#b91c1c;font-size:13px;min-height:16px;margin-top:6px}
#ap .btns{display:flex;justify-content:flex-end;gap:8px;margin-top:12px;align-items:center}
.dur{width:54px;font:inherit;font-size:12px;padding:1px 3px;border:1px solid var(--line2);border-radius:4px}
.is{font-size:12px;margin-top:2px;color:#b45309;line-height:1.45}.is.error{color:#b91c1c;font-weight:600}
.lk{margin-top:3px;font-size:12px;color:var(--sub)}.lk a{color:var(--acc);text-decoration:none;margin-left:6px}.lk a:hover{text-decoration:underline}
.intro{margin-top:4px;font-size:12px}.intro summary{cursor:pointer;color:var(--acc)}.intro .tx{margin-top:3px;padding:5px 7px;background:#f7f7f2;border-radius:4px;color:var(--ink2);white-space:pre-wrap;line-height:1.5}.intro small{display:block;margin-top:3px;color:#a60}
.mealgap{padding:4px 12px;background:#f3f8ee;border-bottom:1px solid #dfe9d4;font-size:12.5px;color:#456}.mealgap button{margin-left:6px;font-size:12px;padding:1px 8px;border-radius:12px}
.dayiss{padding:5px 12px;background:#fff8ed;border-bottom:1px solid #f1e3cd}
.editonly{display:none}
#app.edit .editonly{display:block}
#app.edit #tabs{display:none}
#tabs{position:sticky;top:0;background:var(--paper);padding:8px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:6px;z-index:5}
#tabs button.on{color:#fff;border-color:transparent}
.sec{border-bottom:1px solid var(--line);padding:8px 12px;background:var(--paper)}
#datedet summary{cursor:pointer;font-weight:700;font-size:14px;padding:2px 0}
#datedet[open] summary{margin-bottom:6px}
.sec h3{margin:0 0 6px;font-size:14px;display:flex;justify-content:space-between;align-items:center}
#cal .nav{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
#cal table{width:100%;border-collapse:collapse;text-align:center;font-size:13px}
#cal td,#cal th{padding:0}
#cal td button{width:100%;border:0;border-radius:4px;padding:5px 0;background:none}
#cal td button:hover{background:var(--acc-soft)}
#cal td.fc button{background:#f1f8e9}
#cal td.in button{background:var(--acc-soft2)}
#cal td.edge button{background:var(--acc);color:#fff}
#calinfo{font-size:13px;margin:6px 0;color:var(--ink2)}
.day{border:1px dashed transparent;border-radius:6px;margin:6px 0 10px;padding:0}
.day.over{border-color:var(--acc);background:var(--acc-soft)}
.dh{font-size:14px;padding:8px 12px;cursor:pointer;display:flex;gap:10px;align-items:center;background:var(--paper);border-bottom:1px solid var(--line)}
.dh.view{cursor:default}
.dh .dot{width:10px;height:10px;border-radius:50%}
.db{width:44px;flex:none;text-align:center;border-radius:8px;background:#f1f3f8;border-top:3px solid #4363d8;padding:2px 0 3px;line-height:1.15}
.db small{display:block;font-size:10px;color:var(--sub)}.db b{display:block;font-size:19px;color:#223}
.dt{flex:1;min-width:0}.dt .t{font-weight:700;font-size:14px}.dt .t em{font-style:normal;font-weight:400;font-size:12px;color:var(--sub);margin-left:6px}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.chip{font-size:11px;font-weight:400;background:#f1f3f8;color:#456;border-radius:10px;padding:1px 8px;white-space:nowrap}
.chip.warn{background:#fff1dc;color:#a05a00}.chip.err{background:#fde8e8;color:#b02020}.chip.mute{color:var(--sub)}
.tags{display:flex;flex-wrap:wrap;gap:4px;margin:0 0 4px -2px}
.hrs,.cat{font-size:11px;border-radius:10px;padding:0 8px;line-height:17px}
.hrs.ok{background:#e6f5e9;color:#256b36}.hrs.warn{background:#fff1dc;color:#a05a00}.hrs.bad{background:#fde8e8;color:#b02020}.hrs.unknown{background:var(--line);color:var(--sub)}
.cat{background:#eef1fb;color:#3a4a8a}
.it.stop{border-left:3px solid #4363d8}.it.stop .tm{font-weight:700;color:var(--ink);font-size:14px}
.dh.cur{background:var(--acc-soft)}
.it{padding:8px 12px;border-bottom:1px solid var(--line);cursor:pointer;background:var(--bg)}
.it:hover{background:var(--acc-soft)}
.it .h{display:flex;gap:8px;align-items:baseline}
.it .tm{font-variant-numeric:tabular-nums;color:var(--ink2);min-width:42px;font-size:13px}
.it .nm{font-weight:600;flex:1}
.it .sub{margin:2px 0 0 50px;font-size:12px;color:var(--ink2);line-height:1.5}
.it.drag{opacity:.4}
.it .mv button{padding:0 5px;font-size:11px}
.leg{padding:4px 12px 4px 62px;font-size:12px;color:var(--ink2);border-bottom:1px dashed #e4e4e4;cursor:pointer;background:var(--paper)}
.leg:hover{background:var(--acc-soft)}
.leg a{color:var(--acc);text-decoration:none;margin-left:6px}
.est{color:#b26a00}
.ins{height:3px;background:var(--acc);border-radius:2px}
.empty{font-size:12px;color:var(--sub);padding:8px 12px}
.pin{border-radius:50%;color:#fff;font-weight:700;text-align:center;border:2px solid #fff;box-shadow:0 1px 4px #0006;width:26px;height:26px;line-height:22px;font-size:13px}
.emo{font-size:22px;line-height:24px;text-align:center;filter:drop-shadow(0 1px 2px #0008)}
#prev{font-size:13px;border-top:2px solid var(--acc);padding:6px 12px;background:var(--acc-soft);display:none;max-height:28%;overflow:auto}
#prev ul{margin:4px 0 6px 18px;padding:0}
#prev .w{color:#b45309}
#note{position:absolute;bottom:0;left:calc(var(--sw,400px) + 6px);max-width:calc(100vw - var(--sw,400px) - var(--cw,340px) - 24px);z-index:1000;background:#fffc;font-size:11px;padding:2px 6px}
#chat{width:var(--cw,340px);flex:none;display:flex;flex-direction:column;border-left:1px solid var(--line);background:var(--paper)}
#chat.hide{display:none}
#chead{padding:8px 12px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:center}#chead b{flex:1}#cstat{font-size:12px;color:#b45309;white-space:nowrap}#cstat.ok{color:#15803d}#chead button{border:0;font-size:18px;padding:0 4px}
#cmsgs{flex:1;overflow:auto;padding:8px 10px;font-size:13px}
.m{margin:6px 0;padding:6px 9px;border-radius:8px;white-space:pre-wrap;word-break:break-word;line-height:1.5}
.m.u{background:var(--acc-soft2);margin-left:30px}.m.a{background:#f3f4f6;margin-right:20px}.m.e{background:#fee2e2;color:#991b1b}
.m.md{white-space:normal}.m.md p{margin:4px 0}.m.md ul,.m.md ol{margin:4px 0;padding-left:20px}.m.md li{margin:1px 0}
.m.md table{border-collapse:collapse;font-size:12px;display:block;overflow-x:auto;margin:4px 0}.m.md th,.m.md td{border:1px solid #d1d5db;padding:2px 6px;text-align:left}.m.md th{background:#e5e7eb}
.m.md blockquote{margin:4px 0;padding:2px 8px;border-left:3px solid #9ca3af;color:#4b5563}.m.md hr{border:0;border-top:1px solid #d1d5db;margin:6px 0}.m.md code{background:#e5e7eb;border-radius:3px;padding:0 3px}
#chips{padding:4px 8px;display:flex;gap:4px;flex-wrap:wrap}#chips button{font-size:12px;padding:2px 8px;border-radius:12px}
#cin{display:flex;gap:6px;padding:8px;border-top:1px solid var(--line)}#cin textarea{flex:1;resize:none;font:inherit;font-size:13px;padding:4px 6px}
@media (max-width:760px){.sp{display:none}#side{width:auto}#note{left:0;max-width:100vw;bottom:auto;top:0}#app{flex-direction:column-reverse}#side{height:50%;border-right:0;border-top:1px solid var(--line)}#map{height:50%;flex:none}#chat{position:fixed;left:0;right:0;bottom:0;width:auto;max-width:none;height:55%;z-index:2000;border-top:2px solid var(--acc)}}

#mo{position:fixed;inset:0;background:#0006;z-index:3500;display:none;align-items:center;justify-content:center}
#mo.on{display:flex}
#mo .box{background:var(--paper);border-radius:10px;width:min(960px,96vw);height:min(86vh,780px);display:flex;flex-direction:column;box-shadow:0 8px 30px #0005;font-size:14px}
#mo .top{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--line)}
#mo .tabs{display:flex;gap:4px;flex:1}#mo .tabs button.on{background:var(--acc);color:#fff;border-color:transparent}
#mo .pane{display:none;flex:1;min-height:0;overflow:auto;padding:12px 16px}#mo .pane.on{display:block}
#mo #pane_share.on{display:flex;gap:16px}
#pane_share .ctl{width:250px;flex:none}#pane_share .ctl label{display:block;margin:6px 0}#pane_share .ctl .sm{font-size:12px;color:var(--sub);margin:0 0 6px 22px}
#pane_share .ctl button{margin:4px 6px 4px 0}
#pane_share .ph{flex:1;display:flex;justify-content:center;min-width:0}
#sh_frame{width:min(430px,100%);height:100%;border:1px solid var(--line2);border-radius:12px;background:#f6f4ef}
#sh_err{color:#b91c1c;font-size:13px;min-height:18px;margin-top:6px}
.warn{background:#fff8ed;border:1px solid #f1e3cd;border-radius:6px;padding:6px 8px;margin:6px 0;font-size:13px;color:#8a4b00}
.hbtop{display:flex;align-items:center;gap:12px;margin-bottom:8px}.seg button{border-radius:0}.seg button:first-child{border-radius:6px 0 0 6px}.seg button:last-child{border-radius:0 6px 6px 0}.seg button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.hbimp{border:1px solid var(--line);background:var(--bg);border-radius:8px;padding:8px 10px;margin:6px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center}#hb_folder{flex:1;min-width:260px}
.hbs{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:8px 0;background:var(--paper)}.dayt{display:flex;gap:8px;align-items:center;margin:14px 0 4px}.dayt b{color:var(--acc)}.dayt input{flex:1;max-width:420px}.hbs .dels{margin-left:auto;color:#b91c1c;border-color:#e7b4ae;background:#fff}.hbs .h{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.hbs .h input.nm{flex:1;min-width:140px;font:inherit;font-weight:700;padding:3px 6px;border:1px solid var(--line2);border-radius:6px}
.hbs .dy{font-size:12px;background:var(--acc-soft);color:#2347a5;border-radius:99px;padding:1px 8px}.hbs .tm{font-size:12px;color:var(--sub)}
.hbp{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.hbp .c{width:96px}.hbp img{width:96px;height:72px;object-fit:cover;border-radius:6px;display:block;cursor:zoom-in}.hbp .c.cover img{outline:2px solid #c4553a}
.hbp .bt{display:flex;justify-content:space-between;margin-top:2px}.hbp .bt{align-items:center}.hbp .bt button,.hbp .bt span{padding:0 5px;font-size:12px;white-space:nowrap;line-height:20px}.hbp .add{width:96px;height:72px;border:1px dashed #999;border-radius:6px;display:flex;align-items:center;justify-content:center;color:var(--acc);cursor:pointer;font-size:12px}
.hbs textarea{width:100%;box-sizing:border-box;font:inherit;min-height:48px;border:1px solid var(--line2);border-radius:6px;padding:4px 6px}.hbs .fr{display:flex;gap:6px;margin:3px 0}.hbs .fr input{font:inherit;padding:2px 6px;border:1px solid var(--line2);border-radius:6px}.hbs .fr input:first-child{flex:2}.hbs .fr input:nth-child(2){flex:1}
.hbs .lb2{font-size:12px;color:var(--sub);margin:6px 0 2px;display:flex;gap:8px;align-items:center}.hbexp{border-top:2px solid var(--line);margin-top:14px;padding-top:8px;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}.hbexp b{width:100%}
#hb_out{width:100%;white-space:pre-wrap;font-size:12px;color:var(--ink2);margin:4px 0 0}
.bls{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0}.bls .k{border:1px solid var(--line);border-radius:8px;padding:6px 12px;background:var(--paper)}.bls .k b{display:block;font-size:18px}
.blbar{height:8px;background:var(--acc);border-radius:4px}.bltab{width:100%;border-collapse:collapse;font-size:13px}.bltab td,.bltab th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}.bltab tr.ex{color:var(--sub)}.bltab select{font:inherit;font-size:12px}
.lgday{margin:8px 0;padding:6px 8px;border:1px solid var(--line);border-radius:8px}.lgstop{margin:3px 0 0 6px;font-size:13px}
.st{display:inline-block;font-size:11px;padding:0 6px;border-radius:10px;color:#fff}.st.ok{background:#3a9d5d}.st.skip{background:#888}.st.chg{background:#d98e04}.st.no{background:#c2410c}
#pane_log textarea{width:100%;height:110px;font:inherit;font-size:13px;box-sizing:border-box;margin-top:6px}
#pane_tools .tbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}#pane_tools .tbar input{flex:1;min-width:200px;font:inherit;padding:6px 9px;border:1px solid var(--line2);border-radius:8px}
#pane_tools .chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 2px}.tchip{font:inherit;font-size:12.5px;padding:2px 10px;border:1px solid var(--line);border-radius:999px;background:var(--paper);color:var(--ink2);cursor:pointer}.tchip.on{background:var(--acc);border-color:var(--acc);color:#fff}.tchip i{font-style:normal;opacity:.65;margin-left:3px}
.tlg{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px;margin-top:10px}
.tcard{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--bg);display:flex;flex-direction:column;gap:5px;font-size:13px}.tcard:hover{border-color:#b9c6e8;background:var(--paper)}
.tcard .hd{display:flex;align-items:center;gap:6px;justify-content:space-between}.tcard code{font-weight:700;font-size:13px;word-break:break-all}.tcard .sm2{color:var(--ink2);line-height:1.45;flex:1}
.tcard a{color:var(--acc);text-decoration:none;font-size:12.5px;background:var(--acc-soft);border-radius:6px;padding:3px 8px;display:block}
.tlpro{margin-top:14px;border-top:1px solid var(--line);padding-top:8px;font-size:13px;color:var(--ink2)}.tlpro summary{cursor:pointer;font-weight:700;color:#333}
.tlnote{color:var(--sub);font-size:12.5px}
.kd{font-size:11px;padding:0 6px;border-radius:10px;border:1px solid;white-space:nowrap}.kd.read{color:#2e7d32;border-color:#2e7d32}.kd.export{color:#1565c0;border-color:#1565c0}.kd.change{color:#b45309;border-color:#b45309}
#lb{position:fixed;inset:0;background:#000d;z-index:4000;display:none;align-items:center;justify-content:center;flex-direction:column}#lb.on{display:flex}
#lb img{max-width:92vw;max-height:80vh;border-radius:6px;background:#222}#lb_cap{color:var(--line);font-size:13px;margin-top:10px;max-width:90vw;text-align:center}
#lb button{position:absolute;background:#fff2;color:#fff;border:0;border-radius:50%;width:40px;height:40px;font-size:22px;cursor:pointer}#lb button:hover{background:#fff4}
#lb_x{top:16px;right:16px}#lb_prev{left:16px;top:50%}#lb_next{right:16px;top:50%}.pht img,.lgph img{cursor:zoom-in}
.lgph{display:flex;gap:4px;margin:3px 0 0 4px;flex-wrap:wrap}.lgph img{width:56px;height:56px;object-fit:cover;border-radius:4px}
.phr{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;align-items:center}.pht{position:relative;display:inline-block}
.pht img{width:44px;height:44px;object-fit:cover;border-radius:4px;display:block}.pht button{position:absolute;top:-5px;right:-5px;width:16px;height:16px;line-height:12px;padding:0;border-radius:50%;font-size:11px}
.addph{font-size:12px;border:1px dashed #999;border-radius:4px;padding:2px 8px;cursor:pointer;color:var(--acc)}

/* ---- 主题：和手册同一套暖色（浅色），整体更舒展 ---- */
:root{--bg:#f6f1e7;--paper:#fffdf8;--ink:#33302b;--ink2:#5a554c;--sub:#8a8374;--acc:#c4553a;--acc-soft:#fbeee8;--acc-soft2:#f6dcd2;--line:#e3dac8;--line2:#cfc4ad;--tape:#f0d98a;--r:12px;--serif:"Noto Serif SC","Songti SC","Source Han Serif SC",serif;--shadow:0 6px 24px rgba(80,60,30,.14)}
html,body{background:var(--bg);color:var(--ink);line-height:1.55}
#side{border-right:1px solid var(--line)}header{padding:16px 20px;background:var(--paper)}header b,.sec h3,#mo .top b,.dt .t,#nt h3,#ap h3{font-family:var(--serif);letter-spacing:.02em}
#trip{padding:6px 10px;border-radius:10px;background:var(--bg);font-family:var(--serif)}
button{border-radius:10px;padding:6px 14px;transition:background .15s,border-color .15s,transform .08s,box-shadow .15s}
button:hover:not(:disabled){background:var(--acc-soft);border-color:var(--acc)}button:active:not(:disabled){transform:translateY(1px)}
button.pri{box-shadow:0 2px 8px rgba(196,85,58,.28)}button.pri:hover:not(:disabled){background:#b04a31;border-color:#b04a31}
input,select,textarea{border-color:var(--line2);border-radius:8px;background:var(--paper);color:var(--ink)}input:focus,select:focus,textarea:focus{outline:2px solid rgba(196,85,58,.35);outline-offset:1px;border-color:var(--acc)}
#msg{padding:6px 20px}
.sec{padding:14px 20px}.dh{padding:14px 20px}.it{padding:12px 20px}.leg{padding:6px 20px 6px 70px}.mealgap,.dayiss{padding:8px 20px}
.day{border-radius:var(--r);margin:10px 8px 16px;background:var(--paper);box-shadow:0 1px 3px rgba(80,60,30,.08);overflow:hidden}
.db{border-radius:10px;background:var(--bg)}.db b{color:var(--ink)}
.chip{background:var(--bg);color:var(--ink2)}.cat{background:var(--bg);color:var(--ink2)}
.it:hover{background:var(--acc-soft)}.it.stop{border-left-width:4px}
#tabs{padding:10px 14px;background:var(--paper)}
#chat{background:var(--paper)}#chead{padding:12px 16px}#cmsgs{padding:12px 14px}.m{border-radius:12px;padding:8px 12px}.m.a{background:var(--bg)}
#cin{padding:12px}#chips{padding:6px 12px}
#nt form,#ap .box{border-radius:16px;padding:22px 24px;box-shadow:var(--shadow);background:var(--paper)}
#mo{backdrop-filter:blur(2px)}
#mo .box{width:min(1120px,96vw);height:min(90vh,860px);border-radius:18px;box-shadow:var(--shadow);background:var(--paper)}
#mo .top{padding:14px 20px;gap:10px}#mo .tabs{gap:6px}
#mo .tabs button{border-radius:999px;padding:6px 16px;border-color:var(--line)}#mo .tabs button.on{background:var(--acc);border-color:var(--acc);color:#fff}
#mo .pane{padding:20px 26px}
.hbimp,.hbs,.bls .k,.tcard,.lgday{border-radius:var(--r);padding:14px 16px;border-color:var(--line);background:var(--paper)}.hbimp{background:var(--bg)}
.hbs.flash{box-shadow:0 0 0 3px var(--acc)!important;transition:box-shadow .3s}.hbs{margin:12px 0;box-shadow:0 1px 3px rgba(80,60,30,.06)}.hbimp{margin:12px 0;gap:10px 12px}
.hbexp{border-top:2px solid var(--line);margin-top:20px;padding-top:14px;gap:10px 18px}
.tcard:hover{border-color:var(--acc);box-shadow:var(--shadow)}.tcard code{font-family:ui-monospace,Menlo,monospace}
#sh_frame{border-radius:16px;border-color:var(--line)}.warn{border-radius:10px}
#prev{background:var(--acc-soft);border-top-color:var(--acc)}
.tchip.on{background:var(--acc);border-color:var(--acc);color:#fff}
.seg button.on{background:var(--acc);border-color:var(--acc)}
.hbp .c{cursor:grab;transition:transform .15s,opacity .15s}.hbp .c.drag{opacity:.35}.hbp .c.over{transform:scale(1.06)}.hbp .c.over img{outline:2px dashed var(--acc)}.hbp .c.off img{opacity:.35;filter:grayscale(1)}
.hbp .bt{justify-content:center;gap:4px}.hbp::after{content:"可以直接拖动照片调整顺序，第一张是封面";font-size:12px;color:var(--sub);align-self:center;margin-left:6px}
#lb_act{position:absolute;bottom:18px;left:50%;transform:translateX(-50%);display:flex;gap:8px;align-items:center;background:rgba(0,0,0,.55);padding:6px 10px;border-radius:99px;color:#fff;font-size:12px}#lb_act button{background:var(--paper);color:var(--ink);border:0}#lb_cap{bottom:62px}

.seg{display:inline-flex;background:var(--bg);border:1px solid var(--line);border-radius:99px;padding:3px}.seg button{white-space:nowrap;border:0;background:transparent;border-radius:99px;padding:5px 14px}.seg button.on{background:var(--acc);color:#fff}#modesw button{flex:1}

#home .hbox{text-align:center;max-width:720px;padding:20px}#home h2{font-family:var(--serif);font-size:30px;margin:0 0 6px}#home p{color:var(--sub);margin:0 0 26px}
.hcards{display:flex;gap:20px;flex-wrap:wrap;justify-content:center}.hcard{width:300px;padding:28px 24px;border-radius:18px;background:var(--paper);border:1px solid var(--line);box-shadow:var(--shadow);text-align:left;display:flex;flex-direction:column;gap:10px;transition:transform .15s,box-shadow .15s}
.hcard:hover{transform:translateY(-4px);box-shadow:0 12px 32px rgba(80,60,30,.2);border-color:var(--acc)}.hcard b{font-size:20px;font-family:var(--serif)}.hcard span{color:var(--ink2);font-size:14px;line-height:1.6;font-weight:400}
#rp .rtop{display:flex;align-items:center;gap:20px;padding:10px 28px;background:var(--paper);border-bottom:1px solid var(--line)}#rp .rtop b{font-family:var(--serif);font-size:18px}
#rp .steps{flex:1;display:flex;gap:6px;align-items:center;justify-content:center;flex-wrap:wrap}#rp .steps span{display:flex;align-items:center;gap:6px;padding:6px 14px;border-radius:99px;color:var(--sub);font-size:14px;transition:all .15s}
#rp .steps span i{font-style:normal;width:22px;height:22px;border-radius:50%;background:var(--line);color:var(--ink2);display:inline-flex;align-items:center;justify-content:center;font-size:12px}
#rp .steps span.on{background:var(--acc-soft2);color:var(--acc);font-weight:600}#rp .steps span.on i{background:var(--acc);color:#fff}#rp .steps span.done i{background:#7a9a5b;color:#fff}#rp .steps span.done{cursor:pointer;color:var(--ink2)}
#rp .hbtop{display:none}
#rp.on{flex-direction:row}#rp_side{position:relative}#rp_gate{display:none;position:absolute;inset:0;z-index:5;background:var(--paper);align-items:center;justify-content:center;text-align:center;padding:30px}#rp_gate.on{display:flex}#rp_gate b{font-size:18px}#rp_gate p{color:var(--sub);font-size:14px;line-height:1.6;margin:10px 0 18px}
#nr{position:fixed;inset:0;background:#0006;z-index:3000;display:none;align-items:center;justify-content:center}#nr.on{display:flex}#nr form{background:var(--paper);border-radius:16px;padding:22px 24px;width:min(400px,92vw);box-shadow:var(--shadow);font-size:14px}#nr form input{width:100%;margin-top:4px;height:38px;padding:0 12px;border:1px solid var(--line);border-radius:10px;box-sizing:border-box}#nr .bt{display:flex;justify-content:flex-end;gap:10px;margin-top:16px}#nr .err{color:#a63d2a;margin-top:6px;min-height:18px}#rp_side{width:430px;flex:none;display:flex;flex-direction:column;min-height:0;background:var(--paper);border-right:1px solid var(--line);box-shadow:2px 0 18px rgba(80,60,30,.05);z-index:2}
#rp_auto{display:flex;align-items:center;gap:8px;margin-bottom:10px;font-size:14px}#rp_auto small{color:var(--sub);flex:1}#rp_auto.on b{color:var(--acc)}#rp .sw{position:relative;width:38px;height:22px;flex:none}#rp .sw input{opacity:0;position:absolute;inset:0;margin:0;cursor:pointer;z-index:1}#rp .sw span{position:absolute;inset:0;border-radius:99px;background:var(--line);transition:.15s}#rp .sw span::after{content:"";position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:.15s}#rp .sw input:checked+span{background:var(--acc)}#rp .sw input:checked+span::after{left:19px}
#rp .rtop{display:block;padding:16px 20px 6px;background:transparent;border:0}#rp .steps{justify-content:flex-start;flex-wrap:nowrap;gap:4px}
#rp .steps span{padding:4px 10px 4px 4px;font-size:13px;gap:6px}#rp .steps span:not(.on){font-size:0;gap:0;padding:4px}#rp .steps span:not(.on) i{font-size:12px}
#rp_body.pgbody{padding:8px 20px 18px}#rp .rfoot{padding:12px 20px;border-top:1px solid var(--line);background:var(--paper)}#rp .rfoot .tlnote{flex:1;text-align:center;font-size:12px;line-height:1.35}
#rp_main{flex:1;position:relative;min-width:0;padding:14px}
#rmap{position:absolute;inset:14px;border-radius:20px;overflow:hidden;box-shadow:0 10px 34px rgba(80,60,30,.16);background:#ede5d4;border:1px solid var(--line)}
#rmap_chip{position:absolute;left:30px;top:30px;z-index:1100;background:rgba(255,253,248,.95);border:1px solid var(--line);border-radius:99px;padding:6px 14px;font-size:13px;box-shadow:0 4px 14px rgba(60,45,20,.15);max-width:calc(100% - 140px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}#rmap_chip.pv{background:#fff4ec;border-color:#e7b4ae;color:var(--acc)}#rmap_empty{position:absolute;inset:14px;display:flex;align-items:center;justify-content:center;color:var(--sub);font-size:14px;pointer-events:none;z-index:500}#rmap_empty.hide{display:none}
#rp_act{position:absolute;left:30px;bottom:30px;width:min(390px,calc(100% - 60px));z-index:1100;background:rgba(255,253,248,.95);backdrop-filter:blur(8px);border:1px solid var(--line);border-radius:16px;box-shadow:0 8px 28px rgba(60,45,20,.2);padding:10px 14px}
#rp_act .ah{display:flex;align-items:center;gap:8px;font-size:13px}#rp_act .ah .tlnote{flex:1}#rp_act .ah button{border:0;background:transparent;padding:0 4px;cursor:pointer;color:var(--sub)}
#rp_act .dot{width:9px;height:9px;border-radius:50%;background:#b8b0a0}#rp_act .dot.run{background:var(--acc);animation:pulse 1s infinite}#rp_act .dot.ok{background:#7a9a5b}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(196,85,58,.5)}50%{box-shadow:0 0 0 6px rgba(196,85,58,0)}}
#act_list{margin-top:8px;max-height:210px;overflow:auto;display:flex;flex-direction:column;gap:2px}#rp_act.fold #act_list{display:none}
#act_list .ev{display:flex;gap:8px;align-items:flex-start;padding:5px 2px;font-size:13px;line-height:1.35;border-radius:8px}#act_list .ev i{font-style:normal;width:18px;text-align:center;flex:none}
#act_list .ev .l{flex:1;min-width:0}#act_list .ev .l small{display:block;color:var(--sub);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}#act_list .ev.err .l b{color:#a63d2a}#act_list .ev.run .l b{color:var(--acc)}
#act_list .none{color:var(--sub);font-size:12.5px;line-height:1.5;padding:4px 2px}
#rp_ctog{position:absolute;right:30px;top:30px;z-index:1100;border-radius:99px;width:40px;height:40px;padding:0;font-size:18px;background:var(--paper);box-shadow:0 4px 14px rgba(60,45,20,.2)}
#rp_chat{width:350px;flex:none;display:flex;min-height:0;border-left:1px solid var(--line);background:var(--paper)}#rp_chat #chat{width:100%;border-left:0;display:flex!important}#rp.nochat #rp_chat{display:none}
#rp .pvmap{display:none}.rpin{width:30px;height:30px;border-radius:50% 50% 50% 4px;transform:rotate(-45deg);background:var(--acc);border:2.5px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center}.rpin b{transform:rotate(45deg);color:#fff;font-size:12px}.rpin.sel{background:#2f6f8f;transform:rotate(-45deg) scale(1.2)}
@media (max-width:1180px){#rp_chat{display:none}#rp_ctog{display:none}}
#rp .rfoot{display:flex;align-items:center;justify-content:space-between;padding:12px 28px;background:var(--paper);border-top:1px solid var(--line);gap:12px}
#rp_body[data-s="1"] #hb_pvo,#rp_body[data-s="1"] #hb_merge,#rp_body[data-s="1"] #hb_list,#rp_body[data-s="1"] .hbexp,#rp_body[data-s="1"] #hb_pv,#rp_body[data-s="1"] #hb_go{display:none!important}
#rp_body[data-s="2"] #hb_merge,#rp_body[data-s="2"] #hb_list,#rp_body[data-s="2"] .hbexp,#rp_body[data-s="2"] #hb_go{display:none!important}
#rp_body[data-s="3"] #hb_import,#rp_body[data-s="3"] #hb_merge,#rp_body[data-s="3"] .hbexp{display:none!important}
#rp_body[data-s="4"] #hb_import,#rp_body[data-s="4"] .hbexp,#rp_body[data-s="5"] #hb_import,#rp_body[data-s="5"] #hb_merge,#rp_body[data-s="5"] #hb_list{display:none!important}
#rp_body[data-s="3"] .hbexp{display:none!important}
.pvmap{position:relative;border-radius:14px;overflow:hidden;box-shadow:var(--shadow);max-width:760px;background:#eef3e8}.pvmap svg{display:block;width:100%;height:auto}.pvmap circle{cursor:pointer;transition:r .12s,fill .12s}.pvmap circle:hover{fill:#c4553a99}.pvmap circle.sel{stroke-width:4;fill:#c4553acc}
.pvd{margin-top:12px;padding:12px 16px;background:var(--paper);border:1px solid var(--line);border-radius:12px;max-width:760px;min-height:48px}.pvd img{width:96px;height:72px;object-fit:cover;border-radius:6px;margin:6px 6px 0 0}
.hbexp #hb_pvw{width:100%;margin:6px 0 14px}.pvt{display:flex;gap:8px;align-items:center;margin-bottom:8px}.pvt button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.pvf{border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#fff;box-shadow:var(--shadow)}#hb_pvf{width:100%;height:520px;border:0;display:block}#hb_pvc{display:none;height:520px;overflow:hidden;position:relative;background:#e9e4d8}#hb_pvcf{width:1080px;height:1440px;border:0;transform-origin:0 0;transform:scale(.36);position:absolute;left:50%;margin-left:-194px;top:0}

#topnav{position:fixed;top:0;left:0;right:0;height:48px;z-index:3500;display:flex;align-items:center;gap:6px;padding:0 18px;background:var(--paper);border-bottom:1px solid var(--line)}
#topnav b{font-family:var(--serif);font-size:17px;margin-right:18px;color:var(--acc);letter-spacing:.05em}#topnav button{border:0;background:transparent;border-radius:99px;padding:7px 16px;font-size:14px;color:var(--ink2);transition:all .15s}#topnav button:hover{background:var(--acc-soft)}#topnav button.on{background:var(--acc);color:#fff}
#home,.pg{position:fixed;left:0;right:0;top:48px;bottom:0;z-index:3000;background:var(--bg);display:none}.pg.on{display:flex;flex-direction:column}#home.on{display:flex;align-items:center;justify-content:center}
.pgbody{flex:1;overflow:auto;padding:26px max(28px,calc((100vw - 1040px)/2))}.pg .pane{display:block!important;padding:0!important}
#mo .hbtop .seg{display:none}

#topnav .nsp{flex:1}.tripsel{font-size:13px;color:var(--sub);display:flex;align-items:center;gap:6px}#topnav select{max-width:240px;border-radius:99px;padding:5px 12px;background:var(--bg)}
#askmask{position:fixed;inset:0;z-index:6000;background:rgba(40,32,20,.38);display:flex;align-items:center;justify-content:center}.askbox{width:min(420px,90vw);background:var(--paper);border-radius:16px;padding:22px 24px;box-shadow:0 18px 50px rgba(0,0,0,.3)}.askmsg{white-space:pre-line;font-size:15px;line-height:1.6;color:var(--ink)}.askbt{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}
#toast{position:fixed;left:50%;bottom:36px;transform:translate(-50%,20px);opacity:0;pointer-events:none;z-index:5000;background:#33302b;color:#fffdf8;padding:10px 20px;border-radius:99px;font-size:14px;box-shadow:0 8px 24px rgba(0,0,0,.25);transition:all .25s;max-width:80vw}#toast.on{opacity:1;transform:translate(-50%,0)}#toast.err{background:#a63d2a}
@keyframes pgin{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}.pg.on .pgbody,.pg.on .rtop{animation:pgin .25s ease-out}#rp_body>.pane>*{animation:pgin .3s ease-out}
#rp_body input:not([type=checkbox]):not([type=file]),#rp_body select{font:inherit;font-size:14px;height:36px;padding:0 12px;border:1px solid var(--line);border-radius:10px;background:#fff;box-sizing:border-box;color:inherit}
#rp_body input:focus,#rp_body select:focus,#rp_body textarea:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px rgba(196,85,58,.15)}
#rp_body textarea{font:inherit;font-size:14px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:#fff}
#rp_body label{font-size:14px;color:#5a5347;display:inline-flex;align-items:center;gap:6px}#rp_body input[type=checkbox]{width:16px;height:16px;accent-color:var(--acc)}
#rp_body #hb_import{padding:22px 24px;gap:14px 12px}#rp_body #hb_import>b{flex-basis:100%;font-size:18px;margin-bottom:2px}#rp_body #hb_track{flex:1;min-width:300px}
#rp_body #hb_merge{padding:12px 16px}#rp_body #hb_mname{width:220px}#rp_body .dayt{margin:22px 4px 6px}#rp_body .dayt b{font-size:18px;letter-spacing:.04em}#rp_body .dayt input{height:38px}
#rp_body .hbs .h{gap:10px}#rp_body .hbs input.nm{font-size:16px;font-weight:600;height:40px}#rp_body .hbs .dy{font-size:12px}
.hbs,.tcard,.hbimp,.hbexp,.bls .k,.day{transition:box-shadow .15s,transform .15s,border-color .15s}.hbs:hover,.tcard:hover{box-shadow:0 8px 22px rgba(80,60,30,.14);border-color:var(--line2)}.hbp .c:hover img{filter:brightness(1.05)}
#rp .steps span.done:hover{background:var(--acc-soft)}#ptip{position:fixed;z-index:5000;background:#33302b;color:#fff;font-size:12px;padding:6px 10px;border-radius:8px;pointer-events:none;opacity:0;transition:opacity .1s;white-space:nowrap}#ptip.on{opacity:1}
.msgbox{display:none;width:100%;padding:10px 14px;border-radius:10px;background:var(--acc-soft);border:1px solid var(--acc-soft2);color:var(--ink);white-space:pre-wrap;font-size:13px;line-height:1.6}.msgbox.on{display:block}.msgbox.err{background:#fdecea;border-color:#f3c0b8;color:#8a2a1c}.pk{font-size:12px;padding:5px 10px;white-space:nowrap}
.seg input[type=date]{margin:0 4px}#bl_mode{margin:12px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}.rep{margin:12px 0;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--paper)}.rh{font-weight:600;margin-bottom:8px;font-family:var(--serif)}.rep .why{margin:8px 0;padding:10px 12px;background:#fdecea;border:1px solid #f3c0b8;border-radius:8px;color:#8a2a1c;font-size:13px;line-height:1.6}
.bgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin:12px 0}.bcard{padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--paper)}.brow{display:flex;align-items:center;gap:10px;font-size:13px;margin:6px 0}.brow span{width:84px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.brow .bt{flex:1;background:var(--bg);border-radius:4px}.brow b{min-width:44px;text-align:right}.brow i{font-style:normal;color:var(--sub);min-width:34px;text-align:right}
.nbtn{font-size:13px!important;padding:5px 12px!important;border:1px solid var(--line)!important}#bin{position:absolute;right:16px;top:50px;width:340px;max-height:60vh;overflow:auto;background:var(--paper);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);padding:10px;display:none}#bin.on{display:block}#bin .br{display:flex;align-items:center;gap:8px;padding:6px 4px;border-bottom:1px dotted var(--line);font-size:13px}#bin .br span{flex:1}
</style></head><body>
<div id="toast"></div><div id="ptip"></div>
<nav id="topnav"><b>TripSight</b><button data-pg="plan" class="on">计划行程</button><button data-pg="restore">恢复行程</button><button data-pg="bill">花费</button><button data-pg="fp">足迹</button><button data-pg="vid">视频</button><span class="nsp"></span><label class="tripsel">当前行程 <select id="trip" title="切换行程"></select></label><button id="trip_del" class="nbtn" title="删除当前行程（移到回收区，可恢复）">🗑 删除</button><button id="trip_bin" class="nbtn" title="看看删除过的行程，可以恢复">回收区</button><div id="bin"></div></nav>
<div id="app"><div id="side">
<header><span id="rev" style="font-size:12px;color:#777"></span><button id="ctoggle">💬 助手</button><button id="edit">编辑</button><button id="more" title="分享长图、写游记、查看全部能力">更多</button></header>
<div id="msg"></div>
<div class="editonly sec"><button id="undo">撤销</button> <button id="refine" title="给还没查过的路段查真实路线">更新路线</button></div>
<div id="tabs"></div>
<div id="scroll"><details class="editonly sec" id="datedet"><summary>日期：<span id="dstate"></span></summary>
<div id="cal"></div><div id="calinfo"></div>
<button id="dapply" class="pri" disabled>应用日期</button> <button id="dclear">清除日期</button></details><div id="list"></div></div>
<div id="prev"><b>预览（还没有改动）</b><ul id="chg"></ul><div id="iss"></div><button id="ok" class="pri">确认</button> <button id="cancel">取消</button></div>
</div><div class="sp" id="sp1" title="拖动调整宽度，双击恢复"></div><div id="map" style="position:relative"></div><div class="sp" id="sp2" title="拖动调整宽度，双击恢复"></div>
<div id="chat"><div id="chead"><b>助手</b><span id="cstat"></span><button id="cclose" title="收起">×</button></div>
<div id="cmsgs"></div>
<div id="chips"><button data-t="我想把【景点名】加进行程，查一下位置给我确认；我确认后请直接排进某一天并更新路线。">加景点</button><button data-t="帮我在【区域】附近找几家酒店，给我对比；我选定后请直接设为住宿并更新路线。">找酒店</button><button data-t="帮我查【日期】从【出发地】到【目的地】的火车票/机票。">查车票机票</button><button data-t="帮我在第【几】天的景点附近找午餐，给我几家对比；我选定后请直接加进行程。">找午餐</button><button data-t="帮我在第【几】天的景点附近找晚餐，给我几家对比；我选定后请直接加进行程。">找晚餐</button><button data-t="查一下行程这几天的天气。">查天气</button></div>
<div id="cin"><textarea id="ctext" rows="2" placeholder="对助手说点什么…（Enter 发送，Shift+Enter 换行）"></textarea><button id="csend" class="pri">发送</button></div></div></div>
<div id="note"></div>
<div id="home"><div class="hbox"><h2>今天想做什么？</h2><p>两种用法，随时可以在顶部切换。</p>
<div class="hcards"><button class="hcard" id="home_plan"><b>🗺️ 计划行程</b><span>选景点、排每天的路线，查营业时间、天气和交通。</span><i style="display:block;font-style:normal;color:var(--acc);font-size:13px;margin-top:8px"></i></button>
<button class="hcard" id="home_restore"><b>📷 恢复行程</b><span>把拍过的照片还原成走过的路线，配上文字，做成手册和笔记。</span><i style="display:block;font-style:normal;color:var(--acc);font-size:13px;margin-top:8px"></i></button></div></div></div>
<div class="pg" id="rp"><aside id="rp_side"><div id="rp_gate"><div><b>先新建一个恢复行程</b><p>恢复的照片会读进这个行程里，不会改动你现有的行程。</p><button class="pri" id="rp_gate_btn">＋ 恢复新的行程</button></div></div><div class="rtop"><div id="rp_auto"><label class="sw"><input type="checkbox" id="rp_autoc"><span></span></label><b>自动执行</b><small id="rp_autot">逐步确认：助手每做一步改动前先问你</small></div><div class="steps" id="rp_steps"></div></div>
<div id="rp_body" class="pgbody" data-s="1"></div><div class="rfoot"><button id="rp_prev">上一步</button><span class="tlnote" id="rp_msg"></span><button id="rp_next" class="pri">下一步</button></div></aside>
<section id="rp_main"><div id="rmap"></div><div id="rmap_chip"></div><div id="rmap_empty">照片恢复出来的地点会出现在这里</div>
<div id="rp_act"><div class="ah"><span class="dot" id="act_dot"></span><b id="act_title">助手</b><span class="tlnote" id="act_sub">空闲</span><button id="act_fold" title="收起/展开">▾</button></div><div id="act_list"></div></div>
<button id="rp_ctog" title="显示/隐藏助手对话">💬</button></section>
<aside id="rp_chat"></aside></div>
<div class="pg" id="pg_bill"><div class="pgbody" id="pgb_bill"></div></div><div class="pg" id="pg_fp"><div class="pgbody" id="pgb_fp"></div></div><div class="pg" id="pg_vid"><div class="pgbody" id="pgb_vid"></div></div>
<div id="mo"><div class="box"><div class="top"><div class="tabs"><button data-t="share" class="on">分享</button><button data-t="hb">手册</button><button data-t="tools">能力</button></div><button id="mo_close">关闭</button></div>
<div class="pane on" id="pane_share"><div class="ctl"><b>可分享的行程图</b>
<label>风格 <select id="sh_t"></select></label><div class="sm">只换配色和字体，都是浅色底</div><label><input type="checkbox" id="sh_b"> 路线图用高德底图（联网）</label><div class="sm" id="sh_bn">默认关闭。打开后会用你自己的高德 key 联网取底图，只发地图中心、缩放和图片大小，不发景点名和路线；底图范围内的酒店名可能出现在地图上。</div><label><input type="checkbox" id="sh_l"> 公开酒店</label><div class="sm">默认不公开酒店名和从酒店出发的路段</div>
<label><input type="checkbox" id="sh_c"> 公开花费</label><div class="sm">门票、餐饮人均、住宿估价</div>
<label><input type="checkbox" id="sh_p"> 带上照片</label><div class="sm" id="sh_pn"></div>
<button id="sh_html">下载网页</button><button id="sh_png">下载长图</button><button id="sh_gif">下载路线动画</button><button id="sh_cal" title="生成 .ics 日历文件，你自己双击导入；不连你的账号">导出日历（.ics）</button><div id="sh_err"></div>
<div class="sm" style="margin-left:0">不含航班/车次号，不含任何 key；这是此刻的快照，行程改了要重新下载。</div></div>
<div class="ph"><iframe id="sh_frame" sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" title="分享预览"></iframe></div></div>
<div class="pane" id="pane_hb">
<div class="hbtop"><div class="seg"><button data-m="restore" class="on">恢复行程</button><button data-m="plan">计划行程</button></div>
<span class="tlnote" id="hb_hint"></span></div>
<div id="hb_import" class="hbimp"><b>从相册文件夹恢复</b>
<label>来源 <select id="hb_src"><option value="folder">文件夹</option><option value="album">照片 App 相册（Mac）</option></select></label><select id="hb_album" style="display:none"><option value="">先点“读取相册列表”</option></select><button id="hb_al" style="display:none">读取相册列表</button><input id="hb_folder" placeholder="照片文件夹的完整路径，例如 /Users/你/Desktop/台州（照片要带位置信息）"><button class="pk" data-pick="folder" data-to="hb_folder">选文件夹</button>
<label title="不在行程目录里存照片副本，省磁盘；导出时才从原文件缩小并去掉定位。原文件被移走或删除后图会缺失"><input type="checkbox" id="hb_link"> 只引用照片（不复制）</label>
<input id="hb_track" placeholder="可选：轨迹文件（.gpx/.kml）或其文件夹的完整路径，用来给没有位置的照片补位置"><button class="pk" data-pick="file" data-to="hb_track">选文件</button><button class="pk" data-pick="folder" data-to="hb_track">选文件夹</button>
<label title="可选：只恢复这一段；不填就是全部照片（跨几年也行）">只恢复这段日期 <input type="date" id="hb_d1"> – <input type="date" id="hb_d2"></label>
<label>景点大小 <select id="hb_r"><option value="300">普通（300 米内算一处）</option><option value="1500">大景区（1500 米内算一处）</option></select></label>
<label title="预览地图加高德底图：只把地图中心点、缩放级别发给高德，不发照片和每个点的位置"><input type="checkbox" id="hb_pvbm" checked> 预览地图带底图（联网）</label><button id="hb_pv">先预览</button><button id="hb_go" class="pri">读取照片</button><div id="hb_pvo" style="width:100%"></div><div class="tlnote">只读取这台电脑上的这个文件夹，不联网；照片会读进当前这个恢复行程，其他行程不受影响。</div></div>
<div id="hb_merge" class="hbimp" style="display:none"><b>合并所选</b> <input id="hb_mname" placeholder="合并后的名字（可不填）" style="width:200px"><button id="hb_mgo">合并</button><span class="tlnote">只能合并同一天的</span> <button id="hb_an" title="名字还是“停留点”或“区县 · 时间”的点，用高德（你自己的 key，只发坐标）重新查地名；你手动改过的不动">重新起名</button> <button id="hb_rg" title="把各点坐标发给高德（你自己的 key）查所在城市/区，手册用来分章">标注城市/区</button></div>
<div id="hb_list"></div>
<div class="hbexp"><b>确定最终版并导出</b> <span class="hbimp" id="hb_dir" style="display:inline-flex"><span>保存到：<code id="hb_dirp">…</code></span><button class="pk" id="hb_dirpick">选择文件夹</button><button class="pk" id="hb_dirdef" style="display:none">恢复默认</button></span> <span class="hbimp" id="hb_vidline" style="display:none"><span id="hb_vidn"></span><button id="hb_tovid">去生成粗剪</button></span> <label>风格 <select id="hb_style"><option>手账</option><option>杂志</option><option>清新</option><option>胶片</option><option>海边</option></select></label>
<div id="hb_pvw"><div class="pvt"><button data-k="page" class="on">网页手册</button><button data-k="card">小红书卡片（第 1 天）</button><span class="tlnote" id="hb_pvn"></span></div><div class="pvf"><iframe id="hb_pvf" sandbox="allow-scripts" title="手册预览"></iframe><div id="hb_pvc"><iframe id="hb_pvcf" sandbox="" title="卡片预览"></iframe></div></div><div class="tlnote">预览用你现在选的风格和照片生成，不含高德底图；导出出来的就是这个样子。网页手册预览里可以直接改：点每天的标题或“我的话”改文字，拖照片右下角的红点调大小，改完自动保存。</div></div>
<label><input type="checkbox" class="hbf" value="html" checked> 网页文件夹</label><label><input type="checkbox" class="hbf" value="cards" checked> 小红书卡片图</label>
<label><input type="checkbox" class="hbf" value="pdf"> PDF</label><label><input type="checkbox" class="hbf" value="obsidian"> Obsidian 笔记</label>
<label><input type="checkbox" id="hb_ph" checked> 带照片（含人像）</label><label title="每张小红书卡片图放几张照片，轮流取这一天各站的照片">卡片放 <select id="hb_cp"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select> 张照片</label><label><input type="checkbox" id="hb_bm"> 路线图用高德底图（联网）</label><label title="路线图上有照片的点用圆形缩略图代替数字圆点"><input type="checkbox" id="hb_pin"> 缩略图当图钉</label>
<label><input type="checkbox" id="hb_sp"> 最后加一页“花费”（只有总额和各类别，没有商户）</label><span id="hb_spc" style="display:none"><label><input type="checkbox" class="hbsc" value="门票" checked> 门票</label><label><input type="checkbox" class="hbsc" value="餐饮" checked> 餐饮</label><label><input type="checkbox" class="hbsc" value="交通" checked> 交通</label><label><input type="checkbox" class="hbsc" value="住宿" checked> 住宿</label><label><input type="checkbox" class="hbsc" value="购物" checked> 购物</label><label><input type="checkbox" class="hbsc" value="其他" checked> 其他</label></span><button id="hb_exp" class="pri">导出</button> <button id="hb_open" title="导出的东西都在 ~/Documents/TripSight/ 下，每个行程一个文件夹">打开导出文件夹</button><pre id="hb_out"></pre></div></div>
<div class="pane" id="pane_bill">
<div class="hbimp"><b>导入账单</b><input id="bl_path" placeholder="微信/支付宝账单文件或文件夹的完整路径（不填就看“下载”文件夹）" style="flex:1;min-width:260px"><button class="pk" data-pick="file" data-to="bl_path">选文件</button><button class="pk" data-pick="folder" data-to="bl_path">选文件夹</button><button id="bl_go" class="pri">导入</button>
<div class="tlnote">只在这台电脑上解析，账单内容不会发给助手或模型；只记行程日期范围内的消费。支付宝账单也可以是 .numbers，微信是 .xlsx / .csv。</div><div id="bl_msg" class="msgbox"></div></div>
<details class="hbimp" id="bl_auto"><summary><b>自动导入</b> <span class="tlnote" id="bl_watchn"></span></summary>
<div style="width:100%"><div class="tlnote">盯着这些文件夹（每行一个），里面新出现的微信/支付宝账单和 Apple Pay 记录会自动记进账本。推荐：iPhone 把账单存进 iCloud 云盘的“TripSight账单”文件夹。只读，不会移动或删除里面的文件。</div>
<textarea id="bl_watch" rows="3" style="width:100%;box-sizing:border-box;font:inherit" placeholder="例如 ~/Library/Mobile Documents/com~apple~CloudDocs/TripSight账单"></textarea>
<button id="bl_wsave">保存</button> <button id="bl_scan" class="pri">立即扫描</button> <span class="tlnote" id="bl_wmsg"></span>
<details style="margin-top:6px"><summary>iPhone 快捷指令（记 Apple Pay 付款）怎么设</summary><ol id="bl_steps" class="tlnote"></ol></details></div></details>
<div id="bl_rep"></div><div id="bl_mode"></div><div id="bl_sum"></div><div id="bl_list"></div></div>
<div class="pane" id="pane_vid">
<div class="hbimp"><b>视频素材整理 + 粗剪</b><input id="vd_path" placeholder="视频文件夹的完整路径（.mov / .mp4 / .m4v，不含子文件夹）" style="flex:1;min-width:260px"><button class="pk" data-pick="folder" data-to="vd_path">选文件夹</button><button id="vd_scan">整理归类</button>
<div class="tlnote" style="width:100%">只读视频的拍摄时间、位置和时长，按时间和位置归到行程里的各个景点；不看画面内容，不上传。需要本机装好 ffmpeg（Mac：brew install ffmpeg）。</div></div>
<pre id="vd_msg" class="tlnote" style="white-space:pre-wrap;margin:8px 0"></pre>
<div class="hbimp"><b>粗剪</b><label>目标时长（秒，0 = 不限）<input id="vd_t" type="number" value="60" min="0" style="width:70px"></label><label>每段最长（秒）<input id="vd_m" type="number" value="8" min="2" max="30" style="width:60px"></label>
<label><input type="checkbox" id="vd_c" checked> 每天前加“第N天”和路线卡片</label>
<input id="vd_jy" placeholder="可选：剪映草稿文件夹的完整路径（给了就同时生成剪映草稿）" style="flex:1;min-width:260px"><button class="pk" data-pick="folder" data-to="vd_jy">选文件夹</button><button id="vd_cut" class="pri">生成粗剪</button>
<div class="tlnote" style="width:100%">输出到 ~/Documents/TripSight/粗剪/（成片、字幕、片段清单）。不带音乐、不加特效，创意部分在剪映里做。素材多时要跑一会儿，请等它完成。含人脸或路人的视频发布前请自己确认。</div></div>
<pre id="vd_out" class="tlnote" style="white-space:pre-wrap;margin:8px 0"></pre></div>
<div class="pane" id="pane_fp">
<div class="hbimp"><b>我的足迹</b><label title="联网向高德取街道底图，只发地图中心、缩放和图片大小；仅国内，需要你自己的高德 key"><input type="checkbox" id="fp_bm"> 地图加高德底图（联网）</label><button id="fp_go" class="pri">刷新</button>
<div class="tlnote" style="width:100%">只算“去过”的：从照片还原的行程，和复盘里标了“去了”的景点；纯计划不算。公里数是直线距离累加，只是下限。城市来自“标城市”，没标的不猜。</div></div>
<pre id="fp_msg" class="tlnote" style="white-space:pre-wrap;margin:8px 0"></pre>
<div class="ph" style="height:480px"><iframe id="fp_frame" sandbox="allow-scripts" title="足迹地图" style="width:100%;height:100%;border:0;background:#fff"></iframe></div></div>
<div class="pane" id="pane_tools"><div class="tbar"><input id="tl_q" placeholder="搜索能力，例如：酒店、导出、天气"><span class="tlnote" id="tl_n"></span></div><div class="chips" id="tl_kind"></div><div class="chips" id="tl_cat"></div><div id="tl_out">加载中…</div></div>
</div></div>
<div id="ap"><div class="box"><h3>加景点</h3>
<div class="q"><input id="ap_q" maxlength="60" placeholder="景点名称，例如：大雁塔"><button id="ap_go" class="pri">查找</button></div>
<div id="ap_list"></div><div class="w" id="ap_warn"></div>
<div class="btns"><span style="flex:1;font-size:13px;color:#555">停留 <input id="ap_dur" class="dur" type="number" min="10" max="720" step="15" value="90"> 分钟</span>
<button id="ap_cancel">取消</button><button id="ap_ok" class="pri" disabled>加入行程</button></div><div class="err" id="ap_err"></div></div></div>
<div id="nr"><form id="nrf" autocomplete="off"><h3>恢复新的行程</h3><div class="tlnote" style="margin-bottom:8px">先建一个空的恢复行程，再选照片文件夹或相册读进来。现有的行程都还在。</div>
<label>行程名称（可不填）</label><input id="nr_name" maxlength="40" placeholder="例如：台州周末；不填就用“恢复行程 月.日 时:分”"><div id="nr_err" class="err"></div>
<div class="bt"><button type="button" id="nr_cancel">取消</button><button type="submit" class="pri" id="nr_ok">新建并开始</button></div></form></div>
<div id="nt"><form id="ntf" autocomplete="off"><h3>新建行程</h3>
<label>行程名称（必填）</label><input id="nt_name" maxlength="40" placeholder="例如：东京5日">
<label>目的地城市（选填，之后查坐标会限定在这个城市附近）</label><input id="nt_city" maxlength="40" placeholder="例如：东京">
<div class="row"><div><label>天数（1–30）</label><input id="nt_days" type="number" min="1" max="30" value="3"></div><div><label>出行人数</label><input id="nt_tv" type="number" min="1" max="50" value="1"></div></div>
<div class="row"><div><label>出发日（选填）</label><input id="nt_sd" type="date"></div><div><label>结束日（选填）</label><input id="nt_ed" type="date"></div></div>
<label>节奏</label><select id="nt_pace"><option value="">沿用我的长期偏好</option><option value="relaxed">悠闲</option><option value="normal">正常</option><option value="packed">紧凑</option></select>
<div class="err" id="nt_err"></div>
<div class="btns"><button type="button" id="nt_cancel">取消</button><button type="submit" class="pri" id="nt_ok">创建</button></div></form></div>
<script>__JS__</script>
<div id="lb"><img id="lb_img" alt=""><div id="lb_cap"></div><button id="lb_prev" title="上一张">‹</button><button id="lb_next" title="下一张">›</button><div id="lb_act"><button data-e="preview" title="用“预览”打开，改完保存即可（只引用的照片会先转成一份去掉定位的副本，不动原图）">用预览修改</button><button data-e="finder" title="在访达里显示这张照片的文件">在访达中显示</button><span id="lb_msg"></span></div><button id="lb_x" title="关闭">×</button></div><script>
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = id => document.getElementById(id);
let S = null, selDay = 0, edit = false, pending = null, drag = null, picks = [], calMonth = null;
const map = L.map('map'); let layer = null, tileLayer = null, tileUrl = null;
const pin = (txt, color) => L.divIcon({className:'', html:'<div class="pin" style="background:'+color+'">'+esc(txt)+'</div>', iconSize:[26,26], iconAnchor:[13,13]});
const emo = e => L.divIcon({className:'', html:'<div class="emo">'+e+'</div>', iconSize:[26,26], iconAnchor:[13,13]});
const popup = (name, lines) => '<b>'+esc(name)+'</b>'+(lines.length?'<br>':'')+lines.map(esc).join('<br>');

let toastT = null;
function toast(t, err) { const e = $('toast'); if (!t) return; e.textContent = t.length > 90 ? t.slice(0, 90) + '…' : t; e.className = 'on' + (err ? ' err' : ''); clearTimeout(toastT); toastT = setTimeout(() => e.className = '', err ? 5000 : 3200); }
function say(t, err) { const m = $('msg'); m.textContent = t || ''; m.className = err ? 'err' : ''; if (t) toast(t, err); }
async function api(path, body) {
  const r = await fetch('api/' + path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({error: '服务没有响应'}));
  if (!r.ok) { const e = new Error(j.error || ('出错了 ' + r.status)); e.status = r.status; throw e; }
  return j;
}
async function load() {
  try { S = await api('state'); } catch (e) { say(e.message, true); return; }
  $('rev').textContent = '版本 ' + S.revision; $('undo').disabled = !S.can_undo;
  if (S.map.tiles && (!tileLayer || tileUrl !== S.map.tiles.url)) { if (tileLayer) map.removeLayer(tileLayer); tileUrl = S.map.tiles.url; tileLayer = L.tileLayer(tileUrl, {subdomains: S.map.tiles.sub, maxZoom: 18, minZoom: 3, attribution: S.map.tiles.attr}).addTo(map); $('note').textContent = S.map.tiles.note; }
  await loadTrips();
  if (selDay >= S.map.days.length) selDay = 0;
  renderAll();
  syncChat();
}
// 页内确认框：不用浏览器自带的 confirm（内置浏览器/WebView 里它可能被屏蔽，点了没反应）
function ask(msg, okText) {
  return new Promise(res => {
    const w = document.createElement('div'); w.id = 'askmask';
    w.innerHTML = '<div class="askbox"><div class="askmsg"></div><div class="askbt"><button class="ano">取消</button><button class="ayes pri"></button></div></div>';
    w.querySelector('.askmsg').textContent = msg; w.querySelector('.ayes').textContent = okText || '确定';
    const done = v => { w.remove(); document.removeEventListener('keydown', kd, true); res(v); };
    const kd = e => { if (e.key === 'Escape') { e.preventDefault(); done(false); } else if (e.key === 'Enter') { e.preventDefault(); done(true); } };
    w.querySelector('.ano').onclick = () => done(false); w.querySelector('.ayes').onclick = () => done(true);
    w.onclick = e => { if (e.target === w) done(false); };
    document.addEventListener('keydown', kd, true); document.body.appendChild(w); w.querySelector('.ayes').focus();
  });
}
function rpGate() { const r = TRIPS_R; const cur = r && !r.single ? r.trips.find(t => t.slug === r.current) : null; $('rp_gate').classList.toggle('on', !!(r && !r.single && PGCUR === 'restore' && !(cur && cur.kind === 'restore'))); }
function nrOpen() { $('nr_err').textContent = ''; $('nr_name').value = ''; $('nr').classList.add('on'); $('nr_name').focus(); }
function nrClose() { $('nr').classList.remove('on'); }
$('nr_cancel').onclick = nrClose; $('nr').onclick = e => { if (e.target === $('nr')) nrClose(); };
$('rp_gate_btn').onclick = nrOpen;
$('nrf').onsubmit = async e => {
  e.preventDefault(); $('nr_ok').disabled = true; $('nr_err').textContent = '';
  try {
    const r = await api('trip_new_restore', {name: $('nr_name').value}); nrClose(); toast(r.message);
    HB.sel.clear(); $('hb_folder').value = ''; $('hb_pvo').innerHTML = ''; try { ACT.since = Date.now() / 1000 - 1; ACT.evs.clear(); actRender(); } catch (x) {}
    await load(); await pgShow('restore', 1);
    $('rp_msg').textContent = '新的恢复行程已建好。选照片文件夹或相册，先预览，再恢复。';
  } catch (er) { $('nr_err').textContent = er.message; } finally { $('nr_ok').disabled = false; }
};
let TRIPS_R = null;
$('trip_del').onclick = async () => {
  const r = TRIPS_R; if (!r || r.single) return toast('单文件模式不能删除行程。', true);
  const cur = r.trips.find(t => t.slug === r.current); if (!cur) return;
  if (!(await ask('删除「' + cur.name + '」？\n它会被移到回收区，文件不会真正删掉，之后可以在“回收区”里恢复。'))) return;
  try { const x = await api('trip_delete', {slug: cur.slug}); toast(x.message); await load(); if (PGCUR !== 'plan') pgShow(PGCUR); } catch (e) { toast(e.message, true); }
};
$('trip_bin').onclick = e => { e.stopPropagation(); const b = $('bin'); if (b.classList.contains('on')) return b.classList.remove('on'); binRender(); b.classList.add('on'); };
document.addEventListener('click', e => { if (!e.target.closest('#bin')) $('bin').classList.remove('on'); });
function binRender() {
  const a = (TRIPS_R && TRIPS_R.archived) || [];
  $('bin').innerHTML = '<div class="rh">回收区</div>' + (a.length ? a.map(t => '<div class="br"><span>' + (t.kind === 'restore' ? '📷 ' : '') + esc(t.name) + '</span><button data-s="' + esc(t.slug) + '">恢复</button></div>').join('') : '<div class="tlnote">这里还没有删除过的行程。</div>');
  $('bin').querySelectorAll('button').forEach(b => b.onclick = async () => { try { const x = await api('trip_restore', {slug: b.dataset.s}); toast(x.message); await loadTrips(); binRender(); } catch (er) { toast(er.message, true); } });
}
const needKind = () => PGCUR === 'plan' ? 'plan' : (PGCUR === 'bill' ? '' : 'restore');
const lastKey = k => 'tsLast_' + k;
function rememberTrip(r) { try { const c = r.trips.find(t => t.slug === r.current); if (c) localStorage.setItem(lastKey(c.kind), c.slug); } catch (e) {} }
function lastTrip(r, k) { let v = ''; try { v = localStorage.getItem(lastKey(k)) || ''; } catch (e) {} return r.trips.find(t => t.kind === k && t.slug === v) || r.trips.filter(t => t.kind === k).slice(-1)[0]; }
async function loadTrips() { try { TRIPS_R = await api('trips'); curTrip = TRIPS_R.current; rememberTrip(TRIPS_R); fillTripSel(); rpGate(); } catch (e) {} }
function fillTripSel() {
  const r = TRIPS_R; if (!r) return; const sel = $('trip'), k = needKind(); sel.innerHTML = '';
  const list = r.trips.filter(t => !k || r.single || t.kind === k);
  list.forEach(t => { const o = document.createElement('option'); o.value = t.slug; o.textContent = (t.kind === 'restore' ? '📷 ' : '') + t.name + (t.num_days ? '（' + t.num_days + '天）' : ''); o.selected = t.slug === r.current || r.single; sel.appendChild(o); });
  if (!list.length) { const o = document.createElement('option'); o.value = ''; o.disabled = true; o.selected = true; o.textContent = k === 'restore' ? '（还没有恢复过的行程）' : '（还没有计划行程）'; sel.appendChild(o); }
  if (!r.single && k !== 'restore') { const o = document.createElement('option'); o.value = '__new__'; o.textContent = '＋ 新建行程…'; sel.appendChild(o); }
  if (!r.single && k === 'restore') { const o = document.createElement('option'); o.value = '__newrestore__'; o.textContent = '＋ 恢复新的行程…'; sel.appendChild(o); }
  sel.disabled = r.single; sel.title = r.single ? '单文件模式不能切换或新建' : (k === 'restore' ? '这里只列恢复过的行程' : '切换行程 / 新建行程');
}
async function ensureKind(name) {
  const k = name === 'plan' ? 'plan' : (name === 'bill' ? '' : 'restore'), r = TRIPS_R; if (!k || !r || r.single) return;
  const cur = r.trips.find(t => t.slug === r.current); if (cur && cur.kind === k) return;
  const pick = lastTrip(r, k); if (!pick) return;
  try { await api('switch', {slug: pick.slug}); await load(); } catch (e) {}
}
let curTrip = null, apPicked = null;
function apOpen() { $('ap_q').value = ''; $('ap_list').innerHTML = ''; $('ap_warn').textContent = ''; $('ap_err').textContent = ''; $('ap_dur').value = 90; apPicked = null; $('ap_ok').disabled = true; $('ap').classList.add('on'); $('ap_q').focus(); }
function apClose() { $('ap').classList.remove('on'); }
$('ap_cancel').onclick = apClose; $('ap').onclick = e => { if (e.target === $('ap')) apClose(); };
async function apSearch() {
  const q = $('ap_q').value.trim(); if (!q) return; $('ap_err').textContent = ''; $('ap_go').disabled = true; $('ap_list').innerHTML = '<div class="empty">查询中…</div>'; apPicked = null; $('ap_ok').disabled = true;
  try {
    const r = await api('lookup', {query: q}); $('ap_warn').textContent = r.warning || '';
    if (!r.candidates.length) { $('ap_list').innerHTML = '<div class="empty">' + esc(r.message || '没有找到') + '</div>'; }
    else { $('ap_list').innerHTML = r.candidates.map((c, i) => '<label class="cand"><input type="radio" name="apc" value="' + esc(c.cid) + '"><b>' + esc(c.name) + '</b>' + (c.rating ? ' ⭐' + esc(c.rating) : '') + '<div class="a">' + esc(c.address) + (c.category ? ' · ' + esc(c.category) : '') + (c.opentime_today ? '<br>今日营业：' + esc(c.opentime_today) : '') + '</div></label>').join('');
      $('ap_list').querySelectorAll('input').forEach(i => i.onchange = () => { apPicked = i.value; $('ap_ok').disabled = false; }); }
  } catch (e) { $('ap_list').innerHTML = ''; $('ap_err').textContent = e.message; }
  $('ap_go').disabled = false;
}
$('ap_go').onclick = apSearch; $('ap_q').onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); apSearch(); } };
$('ap_ok').onclick = async () => {
  if (!apPicked) return; $('ap_ok').disabled = true;
  try {
    const r = await api('add_place', {base_revision: S.revision, cid: apPicked, duration_min: Number($('ap_dur').value)});
    apClose(); say(r.message); await load(); }
  catch (e) { $('ap_err').textContent = e.message; $('ap_ok').disabled = false; if (e.status === 409) { apClose(); load(); } }
};
function ntOpen() { $('nt_err').textContent = ''; $('nt').classList.add('on'); $('nt_name').focus(); }
function ntClose() { $('nt').classList.remove('on'); }
$('nt_cancel').onclick = ntClose; $('nt').onclick = e => { if (e.target === $('nt')) ntClose(); };
$('nt_sd').onchange = () => { const a = $('nt_sd').value, b = $('nt_ed').value; if (a && (!b || b < a)) $('nt_ed').value = a; if (a && $('nt_ed').value) $('nt_days').value = Math.round((parse($('nt_ed').value) - parse(a)) / 864e5) + 1; };
$('nt_ed').onchange = () => { const a = $('nt_sd').value, b = $('nt_ed').value; if (a && b) $('nt_days').value = Math.round((parse(b) - parse(a)) / 864e5) + 1; };
$('ntf').onsubmit = async e => {
  e.preventDefault(); const sd = $('nt_sd').value, ed = $('nt_ed').value;
  const body = {name: $('nt_name').value, city: $('nt_city').value, num_days: Number($('nt_days').value), travelers: Number($('nt_tv').value), start: sd || null, end: ed || null, pace: $('nt_pace').value || null};
  $('nt_ok').disabled = true;
  try { const r = await api('new_trip', body); ntClose(); closePrev(); picks = []; calMonth = null; selDay = 0; $('ntf').reset(); say(r.message + ' 现在可以在右侧助手里说想去哪、想看什么。'); await load(); if ($('chat').classList.contains('hide')) $('chat').classList.remove('hide'), syncSp2(), fit(); $('ctext').focus(); }
  catch (er) { $('nt_err').textContent = er.message; }
  $('nt_ok').disabled = false;
};
$('trip').onchange = async () => {
  const sel = $('trip'), want = sel.value;
  if (want === '__new__') { await loadTrips(); ntOpen(); return; }
  if (want === '__newrestore__') { await loadTrips(); nrOpen(); return; }
  if (pending && !(await ask('有一个还没确认的修改预览，切换行程会放弃它。继续吗？'))) { await loadTrips(); return; }
  try { const r = await api('switch', {slug: want}); closePrev(); picks = []; calMonth = null; selDay = 0; say('已切换到「' + r.title + '」。助手之后也针对这个行程。'); await load(); if (PGCUR !== 'plan') pgShow(PGCUR); }
  catch (e) { say(e.message, true); await loadTrips(); }
};
function renderAll() { renderDates(); renderTabs(); renderList(); }
$('edit').onclick = () => { edit = !edit; $('app').classList.toggle('edit', edit); $('edit').textContent = edit ? '完成编辑' : '编辑'; $('edit').className = edit ? 'pri' : ''; closePrev(); if (edit) loadPhotos().then(() => { if (S) renderAll(); }); else if (S) renderAll(); };
// ---- 日期 ----
const iso = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
const parse = s => { const [y,m,d] = s.split('-').map(Number); return new Date(y, m-1, d); };
function renderDates() {
  if (!edit) return;
  const cur = S.dates;
  $('dstate').textContent = cur.start ? cur.start + ' 至 ' + cur.end + '（共 ' + cur.num_days + ' 天）' : '还没有设置（点开选择）';
  if (!picks.length && cur.start) picks = [cur.start, cur.end];
  const base = calMonth || parse(cur.start || iso(new Date())); calMonth = new Date(base.getFullYear(), base.getMonth(), 1);
  const y = calMonth.getFullYear(), m = calMonth.getMonth(), first = (new Date(y, m, 1).getDay() + 6) % 7, n = new Date(y, m+1, 0).getDate();
  const today = new Date(); today.setHours(0,0,0,0); const fcEnd = new Date(today); fcEnd.setDate(fcEnd.getDate() + 15);
  let h = '<div class="nav"><button id="pm">‹</button><b>' + y + ' 年 ' + (m+1) + ' 月</b><button id="nm">›</button></div><table><tr>' + '一二三四五六日'.split('').map(x => '<th>' + x + '</th>').join('') + '</tr><tr>';
  for (let i = 0; i < first; i++) h += '<td></td>';
  for (let d = 1; d <= n; d++) {
    const dt = new Date(y, m, d), k = iso(dt); if ((first + d - 1) % 7 === 0 && d > 1) h += '</tr><tr>';
    const a = picks[0], b = picks[1] || picks[0]; const cls = [];
    if (dt >= today && dt <= fcEnd) cls.push('fc');
    if (a && k >= a && k <= b) cls.push('in'); if (k === a || k === b) cls.push('edge');
    h += '<td class="' + cls.join(' ') + '"><button data-d="' + k + '">' + d + '</button></td>';
  }
  $('cal').innerHTML = h + '</tr></table>';
  $('pm').onclick = () => { calMonth = new Date(y, m-1, 1); renderDates(); }; $('nm').onclick = () => { calMonth = new Date(y, m+1, 1); renderDates(); };
  $('cal').querySelectorAll('td button').forEach(b => b.onclick = () => {
    const k = b.dataset.d; if (picks.length !== 1) picks = [k]; else picks = k < picks[0] ? [k, picks[0]] : [picks[0], k]; renderDates(); });
  const full = picks.length === 2, days = full ? Math.round((parse(picks[1]) - parse(picks[0])) / 864e5) + 1 : 0;
  $('calinfo').textContent = !picks.length ? '先点出发日，再点结束日。绿色底是天气预报能覆盖的范围（约未来 16 天）。' : (full ? '已选 ' + picks[0] + ' 至 ' + picks[1] + '，共 ' + days + ' 天' + (days > 30 ? '（最多 30 天）' : '') : '已选出发日 ' + picks[0] + '，再点结束日');
  if (full && S.days.length && days !== S.dates.num_days) $('calinfo').textContent += '。应用后天数会从 ' + S.dates.num_days + ' 天变成 ' + days + ' 天，并自动重新分天（已锁定且仍在范围内的景点保持原位）。';
  $('dapply').disabled = !full || days > 30 || (cur.start === picks[0] && cur.end === picks[1]);
}
$('dapply').onclick = async () => { try { const r = await api('dates', {base_revision: S.revision, start: picks[0], end: picks[1]}); say(r.message); await load(); } catch (e) { say(e.message, true); if (e.status === 409) load(); } };
$('dclear').onclick = async () => { if (!S.dates.start) return; try { const r = await api('dates', {base_revision: S.revision, start: null, end: null}); picks = []; say(r.message); await load(); } catch (e) { say(e.message, true); } };
// ---- 标签页（查看模式）----
function renderTabs() {
  const tabs = $('tabs'); tabs.innerHTML = '';
  S.map.days.forEach((d, i) => { const b = document.createElement('button'); b.textContent = d.label; b.className = i === selDay ? 'on' : ''; b.style.background = i === selDay ? d.color : '#fff'; b.onclick = () => { selDay = i; renderAll(); }; tabs.appendChild(b); });
}
// ---- 地图：画某一天，返回每个条目对应的标记/线 ----
function drawMap(di) {
  if (layer) map.removeLayer(layer); layer = L.featureGroup().addTo(map); const ctx = {m: {}, l: {}};
  const d = S.map.days[di]; if (!d) { map.setView([35, 105], 4); return ctx; }
  d.timeline.forEach((e, idx) => {
    if (e.type === 'leg') {
      const pts = e.path.length ? e.path : [e.a, e.b];
      const pl = L.polyline(pts, {color: d.color, weight: e.real ? 5 : 3, opacity: .85, dashArray: e.real ? null : '6 8'}).addTo(layer);
      pl.bindTooltip(esc(e.mode) + ' 约' + e.minutes + '分钟' + (e.real ? '' : '（估算）'), {sticky: true}); ctx.l[idx] = pl;
    } else if (e.type !== 'conn' && !(e.type === 'hotel' && e.role === '返回')) {
      let icon, title;
      if (e.type === 'hotel') { icon = emo('🏨'); title = e.name; }
      else if (e.type === 'term') { icon = emo(e.icon); title = e.role + '：' + e.name; }
      else if (e.type === 'meal') { icon = emo('🍜'); title = '用餐：' + e.name; }
      else { icon = pin(e.n, d.color); title = e.n + '. ' + e.name; }
      ctx.m[idx] = L.marker(e.show || e.pos, {icon}).bindPopup(popup(d.label + ' · ' + title, e.type === 'hotel' ? [] : (e.lines || []))).addTo(layer);
      if (e.route) {
        e.route.paths.forEach(p => L.polyline(p.path, {color: d.color, weight: 4, opacity: .9, dashArray: p.real ? null : '4 6'}).bindTooltip('步行约' + p.minutes + '分钟' + (p.real ? '' : '（估算）'), {sticky: true}).addTo(layer));
        e.route.points.forEach((w, k) => L.circleMarker(w.pos, {radius: 6, color: d.color, fillColor: '#fff', fillOpacity: 1, weight: 3}).bindTooltip((k+1) + '. ' + w.name).addTo(layer));
      }
    }
  });
  try { const b = layer.getBounds(); if (b.isValid()) map.fitBounds(b.pad(0.15)); } catch (e) {}
  return ctx;
}
// ---- 列表：一行 = 酒店/景点/通勤/用餐/航班车次 ----
function lockedOf(pid) { for (const d of S.days) for (const it of d.items) if (it.place_id === pid) return it.locked; return false; }
const linkHtml = (kw, kind, label) => {
  const city = S.city || '', q0 = [city && kw.indexOf(city) < 0 ? city : '', kw].filter(Boolean).join(' '), suf = kind === 'food' ? '美食' : kind === 'hotel' ? '酒店' : '攻略', q = q0.indexOf(suf) < 0 ? q0 + ' ' + suf : q0;
  return '<span class="lk">' + label + (S.link_sites || []).filter(x => x.kinds.indexOf(kind) >= 0 && x.id !== 'google').map(x => '<a href="' + esc(x.tpl.replace('{q}', encodeURIComponent((q + ' ' + (x.suffix || '')).trim()))) + '" target="_blank" rel="noopener noreferrer">' + esc(x.name) + '</a>').join('') + '</span>';
};
const issueHtml = arr => arr.map(x => '<div class="is ' + x.sev + '">' + (x.sev === 'error' ? '⛔ ' : '⚠ ') + esc(x.text) + '</div>').join('');
function fmtMin(m) { const h = Math.floor(m / 60), r = m % 60; return h ? h + '小时' + (r ? r + '分' : '') : r + '分钟'; }
function dayHead(d) {
  const st = (S.day_stats || {})[String(d.index)] || {};
  const block = st.date ? '<small>' + esc(st.weekday) + '</small><b>' + Number(st.date.slice(8, 10)) + '</b><small>' + Number(st.date.slice(5, 7)) + '月</small>' : '<small>第</small><b>' + (d.index + 1) + '</b><small>天</small>';
  const chips = [];
  if (st.places !== undefined) {
    chips.push('<span class="chip">📍 ' + st.places + ' 个景点</span>');
    chips.push('<span class="chip" title="' + (st.km_estimated ? '含估算路段，点“更新路线”后更准' : '真实路线') + '">🚶 ' + (st.km_estimated ? '约 ' : '') + st.km + ' km</span>');
    chips.push(st.cost_known ? '<span class="chip" title="门票 + 已选餐厅人均，按人数；不含交通和未选的餐食">💰 ¥' + st.cost + '</span>' : '<span class="chip mute" title="还没有门票或餐厅价格">💰 待核实</span>');
    chips.push('<span class="chip' + (st.over ? ' warn' : '') + '" title="游玩 + 路上的总时间' + (st.over ? '，超过了这个节奏的上限' : '') + '">⏱ ' + fmtMin(st.minutes) + '</span>');
    if (st.errors) chips.push('<span class="chip err" title="必须处理的问题">● ' + st.errors + ' 个问题</span>');
  }
  const title = esc(d.label.replace(/ ?\d{4}-\d{2}-\d{2}$/, ''));
  return '<div class="db" style="border-top-color:' + d.color + '">' + block + '</div><div class="dt"><div class="t">' + title + '</div><div class="chips">' + chips.join('') + '</div></div>';
}
function tagsHtml(pid) {
  const x = (S.stop_info || {})[pid]; if (!x) return '';
  const txt = {ok: '营业 ' + x.hours, warn: '注意营业时间 ' + x.hours, bad: '营业时间对不上 ' + x.hours, unknown: '营业时间待核实'}[x.state];
  return '<div class="tags"><span class="hrs ' + x.state + '" title="营业时间来自地图服务，请以现场为准">' + esc(txt) + '</span>' + (x.cat ? '<span class="cat">' + esc(x.cat) + '</span>' : '') + '</div>';
}
function introHtml(pid) {
  const x = (S.intros || {})[pid]; if (!x) return '';
  return '<details class="intro"><summary>游记里怎么说' + (x.day ? '（游记第' + x.day + '天）' : '') + '</summary><div class="tx">' + esc(x.text) + '</div><small>' + esc(x.source || '他人说法，未核实') + '。价格、时间等请以官方为准。</small></details>';
}
function rowEl(d, e, idx, di, ctx, stopIdx, nStops) {
  const row = document.createElement('div'), mk = ctx && ctx.m[idx], pl = ctx && ctx.l[idx];
  const sel = () => { if (di !== selDay) { selDay = di; renderAll(); return true; } return false; };
  if (e.type === 'conn') { row.className = 'leg'; row.style.cursor = 'default'; row.textContent = '⏱ ' + e.text; return row; }
  if (e.type === 'leg') {
    row.className = 'leg';
    row.innerHTML = '↓ ' + esc(e.mode) + ' 约' + e.minutes + '分钟 · ' + e.km + ' km · ' + (e.real ? '真实路线' : '<span class="est">估算</span>') + (e.note ? '<br>' + esc(e.note) : '') + '<a href="' + esc(e.link) + '" target="_blank" rel="noopener noreferrer">导航</a>';
    row.onclick = ev => { if (ev.target.tagName === 'A' || sel()) return; if (pl) { map.fitBounds(pl.getBounds().pad(0.4)); pl.setStyle({weight: 8}); setTimeout(() => pl.setStyle({weight: e.real ? 5 : 3}), 1500); } };
    return row;
  }
  row.className = 'it';
  const lines = (e.lines || []).map(esc).join('<br>');
  if (e.type === 'hotel') row.innerHTML = '<div class="h"><span class="tm">' + e.time + '</span><span class="nm">🏨 ' + esc(e.role) + '：' + esc(e.name) + '</span></div>' + (e.role === '返回' ? '' : '<div class="sub">' + linkHtml(e.name, 'hotel', '看酒店价格：') + '</div>');
  else if (e.type === 'term') row.innerHTML = '<div class="h"><span class="tm">' + e.time + '</span><span class="nm">' + e.icon + ' ' + esc(e.role) + '：' + esc(e.name) + '</span></div><div class="sub">' + lines + '</div>';
  else if (e.type === 'meal') row.innerHTML = '<div class="h"><span class="tm"></span><span class="nm">🍜 ' + esc(e.name) + '</span></div><div class="sub">' + lines + (e.web ? '<br><a href="' + esc(e.web) + '" target="_blank" rel="noopener noreferrer" style="color:#1a6fe8">地图</a>' : '') + '</div>';
  else {
    row.classList.add('stop'); row.style.borderLeftColor = d.color;
    row.innerHTML = '<div class="h"><span class="tm">' + e.arrive + '</span><span class="nm">' + e.n + '. ' + esc(e.name) + (edit && lockedOf(e.pid) ? ' 🔒' : '') + '</span>' + (edit ? '<span class="mv"><button data-a="up" title="上移">▲</button><button data-a="dn" title="下移">▼</button></span>' : '') + '</div><div class="sub">停留 ' + (edit ? '<input class="dur" type="number" min="10" max="720" step="15" value="' + e.stay + '"> ' : e.stay + ' ') + '分钟，约 ' + e.leave + ' 离开<br>' + lines + '</div>';
    row.querySelector('.sub').insertAdjacentHTML('afterbegin', tagsHtml(e.pid));
    const pi = S.issues.places[e.pid]; if (pi) row.querySelector('.sub').insertAdjacentHTML('beforeend', issueHtml(pi));
    row.querySelector('.sub').insertAdjacentHTML('beforeend', '<div>' + linkHtml(e.name, 'guide', '看攻略：') + '</div>');
    row.querySelector('.sub').insertAdjacentHTML('beforeend', introHtml(e.pid));
    if (edit) {
      wireDur(row, e.pid, e.stay); photoRow(row, e.pid);
      row.dataset.pid = e.pid; row.draggable = true;
      row.querySelector('[data-a=up]').onclick = ev => { ev.stopPropagation(); move(e.pid, d.index, Math.max(stopIdx - 1, 0)); };
      row.querySelector('[data-a=dn]').onclick = ev => { ev.stopPropagation(); move(e.pid, d.index, Math.min(stopIdx + 1, nStops - 1)); };
      row.ondragstart = ev => { drag = e.pid; row.classList.add('drag'); ev.dataTransfer.setData('text/plain', e.pid); ev.dataTransfer.effectAllowed = 'move'; };
      row.ondragend = () => { drag = null; document.querySelectorAll('.drag,.over').forEach(x => x.classList.remove('drag', 'over')); document.querySelectorAll('.ins').forEach(x => x.remove()); };
    }
  }
  row.onclick = ev => { if (ev && ev.target.closest && ev.target.closest('.intro')) return; if (sel()) return; if (mk) { map.setView(mk.getLatLng(), Math.max(map.getZoom(), 15)); mk.openPopup(); } };
  return row;
}
function renderList() {
  const list = $('list'); list.innerHTML = '';
  if (!S.map.days.length) { list.innerHTML = '<div class="empty">还没有分天的行程。先对 agent 说“安排行程”，或者在右侧助手里说。</div>'; drawMap(-1); renderUnscheduled(list); return; }
  const ctx = drawMap(selDay);
  const days = edit ? S.map.days.map((d, i) => i) : [selDay];
  days.forEach(di => {
    const d = S.map.days[di], box = edit ? document.createElement('div') : list; if (edit) { box.className = 'day'; box.dataset.day = d.index; list.appendChild(box); }
    if (edit) { const h = document.createElement('div'); h.className = 'dh' + (di === selDay ? ' cur' : ''); h.innerHTML = dayHead(d); h.onclick = () => { selDay = di; renderAll(); }; box.appendChild(h); }
    if (!edit) { const hd = document.createElement('div'); hd.className = 'dh view'; hd.innerHTML = dayHead(d); box.appendChild(hd); }
    if (!d.closed_loop) { const w = document.createElement('div'); w.className = 'leg'; w.style.cursor = 'default'; w.textContent = d.timeline.some(e => e.type === 'stop') ? (S.map.has_lodging ? '这一天没有从酒店出发再回到酒店的闭环。' : '还没有选定住宿，所以不是从酒店出发的闭环。') : '这一天没有景点。'; const fs = d.timeline.find(e => e.type === 'stop'); if (fs && !S.map.has_lodging) w.insertAdjacentHTML('beforeend', '<div>' + linkHtml(fs.name + ' 附近', 'hotel', '看酒店价格：') + '</div>'); box.appendChild(w); }
    const dayI = S.issues.days[String(d.index)]; if (dayI) { const w2 = document.createElement('div'); w2.className = 'dayiss'; w2.innerHTML = issueHtml(dayI); box.appendChild(w2); }
    const mg = (S.meal_gaps || {})[String(d.index)]; if (mg) { const w3 = document.createElement('div'); w3.className = 'mealgap'; w3.innerHTML = '🍜 还没安排' + mg.join('、') + ' ' + mg.map(m => '<button data-m="' + m + '">找' + m + '</button>').join('') + linkHtml('', 'food', ' 看点评：'); w3.querySelectorAll('button').forEach(b => b.onclick = ev => { ev.stopPropagation(); $('chat').classList.remove('hide'); syncSp2(); fit(); $('ctext').value = '帮我在第' + (d.index + 1) + '天的景点附近找' + b.dataset.m + '，给我几家对比；我选定后请直接加进行程。'; $('ctext').focus(); }); box.appendChild(w3); }
    const nStops = d.timeline.filter(e => e.type === 'stop').length; let si = 0;
    d.timeline.forEach((e, idx) => box.appendChild(rowEl(d, e, idx, di, di === selDay ? ctx : null, e.type === 'stop' ? si++ : 0, nStops)));
    if (edit && !nStops) box.insertAdjacentHTML('beforeend', '<div class="empty">把景点拖到这里</div>');
    if (edit) wire(box, () => ({kind: 'day', day: d.index}));
  });
  renderUnscheduled(list);
}
function wireDur(el, pid, cur) {
  const inp = el.querySelector('.dur'); if (!inp) return;
  ['click', 'dblclick'].forEach(t => inp.addEventListener(t, ev => ev.stopPropagation()));
  inp.addEventListener('focus', () => { el.draggable = false; }); inp.addEventListener('blur', () => { el.draggable = true; });
  const commit = () => { const v = Number(inp.value); if (!Number.isInteger(v) || v < 10 || v > 720) { say('停留时间要在 10 到 720 分钟之间。', true); inp.value = cur; return; } if (v !== cur) propose([{kind: 'set_duration', place_id: pid, minutes: v}]); };
  inp.addEventListener('change', commit); inp.addEventListener('keydown', ev => { ev.stopPropagation(); if (ev.key === 'Enter') { ev.preventDefault(); inp.blur(); } });
}
function renderUnscheduled(list) {
  if (!S.unscheduled.length && !(S.orphan_meals || []).length && !edit) return;
  const u = document.createElement('div'); u.className = 'day'; u.innerHTML = '<div class="dh">未安排' + (edit ? '（拖到这里表示移出行程）' : '') + (edit ? '<button id="addp" style="margin-left:auto">＋ 加景点</button>' : '') + '</div>';
  if (edit) u.querySelector('#addp').onclick = apOpen;
  S.unscheduled.forEach(it => { const c = document.createElement('div'); c.className = 'it'; c.dataset.pid = it.place_id; c.style.cursor = edit ? 'grab' : 'default';
    c.innerHTML = '<div class="h"><span class="nm">' + esc(it.name) + '</span><span class="tm" style="min-width:0">' + esc(it.reason || '') + '</span></div>' + (edit ? '<div class="sub">停留 <input class="dur" type="number" min="10" max="720" step="15" value="' + it.duration_min + '"> 分钟</div>' : '') + introHtml(it.place_id);
    if (edit) wireDur(c, it.place_id, it.duration_min);
    if (edit) { c.draggable = true; c.ondragstart = e => { drag = it.place_id; c.classList.add('drag'); e.dataTransfer.setData('text/plain', it.place_id); }; c.ondragend = () => { drag = null; }; } u.appendChild(c); });
  (S.orphan_meals || []).forEach(m => u.insertAdjacentHTML('beforeend', '<div class="it" style="cursor:default"><div class="h"><span class="nm">🍜 ' + esc(m.name) + '</span></div><div class="sub">原来挂在「' + esc(m.after) + '」之后，该景点现在不在行程里（用餐点没有删除）</div></div>'));
  if (edit) wire(u, () => ({kind: 'none'}));
  list.appendChild(u);
}
function wire(zone, info) {
  zone.ondragover = e => { if (!drag) return; e.preventDefault(); zone.classList.add('over'); zone.querySelectorAll('.ins').forEach(x => x.remove());
    const cards = [...zone.querySelectorAll('.it[data-pid]')].filter(c => c.dataset.pid !== drag); let idx = cards.findIndex(c => e.clientY < c.getBoundingClientRect().top + c.getBoundingClientRect().height / 2); if (idx < 0) idx = cards.length;
    zone.dataset.idx = idx; const bar = document.createElement('div'); bar.className = 'ins'; if (cards[idx]) zone.insertBefore(bar, cards[idx]); else zone.appendChild(bar); };
  zone.ondragleave = e => { if (!zone.contains(e.relatedTarget)) { zone.classList.remove('over'); zone.querySelectorAll('.ins').forEach(x => x.remove()); } };
  zone.ondrop = e => { e.preventDefault(); const pid = drag || e.dataTransfer.getData('text/plain'); const t = info(); zone.classList.remove('over'); zone.querySelectorAll('.ins').forEach(x => x.remove());
    if (t.kind === 'day') move(pid, t.day, Number(zone.dataset.idx || 0)); else if (t.kind === 'none') propose([{kind: 'remove', place_id: pid}]); };
}
function move(pid, day, pos) {
  const ops = []; if (lockedOf(pid)) ops.push({kind: 'lock', place_id: pid, locked: false});
  ops.push({kind: 'move', place_id: pid, to_day: day, to_position: pos}); propose(ops);
}
async function propose(ops) {
  let r; try { r = await api('preview', {base_revision: S.revision, ops}); } catch (e) { say(e.message, true); if (e.status === 409) load(); return; }
  showPrev(r);
}
function showPrev(r) {
  pending = r;
  $('chg').innerHTML = pending.changes.map(x => '<li>' + esc(x) + '</li>').join('');
  $('iss').innerHTML = pending.new_issues.length ? '<div class="w">改完后新增的问题：</div><ul>' + pending.new_issues.map(i => '<li class="w">' + esc(i) + '</li>').join('') + '</ul>' : '<div style="color:#15803d">没有新增问题。</div>';
  $('prev').style.display = 'block'; say('');
}
$('ok').onclick = async () => {
  if (!pending) return; const days = pending.affected_days || [];
  try { await api('apply', {base_revision: S.revision, proposal_id: pending.proposal_id}); say('已套用。'); } catch (e) { say(e.message, true); closePrev(); load(); return; }
  closePrev(); await load();
  for (const dn of days) await refineRoutes(dn);
};
async function refineRoutes(day) {
  say(day ? '正在查询第' + day + '天的真实路线…' : '正在查询真实路线…');
  try { const r = await api('refine', {base_revision: S.revision, day: day || null}); say(r.ok ? r.message + (r.more ? '。还有部分路段没查，请再点“更新路线”。' : '') : r.message + '（路线仍是估算）', false); } catch (e) { say(e.message, true); }
  await load();
}
$('refine').onclick = () => refineRoutes(null);
$('cancel').onclick = closePrev; function closePrev() { pending = null; $('prev').style.display = 'none'; }
$('undo').onclick = async () => { try { await api('undo', {base_revision: S.revision}); say('已撤销。'); } catch (e) { say(e.message, true); } closePrev(); load(); };
// ---- 聊天 + 自动刷新 ----
const msgs = $('cmsgs'); let busy = false;
// 助手回复里的 Markdown：先整体转义，再只渲染加粗、行内代码、列表、表格、引用、分隔线；图片和链接不渲染（不会向外部地址发请求）
function mdInline(t) { return esc(t).replace(/!\[[^\]]*\]\([^)]*\)/g, '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>'); }
function md(src) {
  const L = String(src).replace(/\r/g, '').split('\n'), out = []; let i = 0;
  const isRow = l => /^\s*\|.*\|\s*$/.test(l), isUl = l => /^\s*[-*]\s+/.test(l), isOl = l => /^\s*\d+[.)]\s+/.test(l);
  const cells = l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
  while (i < L.length) {
    const l = L[i];
    if (isRow(l) && i + 1 < L.length && /^\s*\|?\s*:?-{2,}/.test(L[i + 1])) {
      const head = cells(l), rows = []; i += 2; while (i < L.length && isRow(L[i])) { rows.push(cells(L[i])); i++; }
      out.push('<table><thead><tr>' + head.map(c => '<th>' + mdInline(c) + '</th>').join('') + '</tr></thead><tbody>' + rows.map(r => '<tr>' + r.map(c => '<td>' + mdInline(c) + '</td>').join('') + '</tr>').join('') + '</tbody></table>'); continue; }
    if (isUl(l) || isOl(l)) { const ord = isOl(l), test = ord ? isOl : isUl, items = [];
      while (i < L.length && test(L[i])) { items.push(L[i].replace(ord ? /^\s*\d+[.)]\s+/ : /^\s*[-*]\s+/, '')); i++; }
      out.push((ord ? '<ol>' : '<ul>') + items.map(x => '<li>' + mdInline(x) + '</li>').join('') + (ord ? '</ol>' : '</ul>')); continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) { out.push('<hr>'); i++; continue; }
    if (/^\s*>/.test(l)) { const q = []; while (i < L.length && /^\s*>/.test(L[i])) { q.push(L[i].replace(/^\s*>\s?/, '')); i++; } out.push('<blockquote>' + q.map(mdInline).join('<br>') + '</blockquote>'); continue; }
    const h = l.match(/^\s*#{1,4}\s+(.*)$/); if (h) { out.push('<p><b>' + mdInline(h[1]) + '</b></p>'); i++; continue; }
    if (!l.trim()) { i++; continue; }
    const p = [];
    while (i < L.length && L[i].trim() && !isRow(L[i]) && !isUl(L[i]) && !isOl(L[i]) && !/^\s*(-{3,}|\*{3,}|>|#{1,4}\s)/.test(L[i])) { p.push(L[i]); i++; }
    if (!p.length) { p.push(L[i]); i++; }
    out.push('<p>' + p.map(mdInline).join('<br>') + '</p>');
  }
  return out.join('');
}
function setMsg(el, text) { if (el.classList.contains('a')) { el.classList.add('md'); el.innerHTML = md(text); } else el.textContent = text; }
function bubble(cls, text) { const d = document.createElement('div'); d.className = 'm ' + cls; setMsg(d, text); msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight; return d; }
let chatUp = null, chatTrip;            // chatTrip：聊天栏现在显示的是哪个行程的记录（undefined = 还没加载）
async function syncChat() {
  if (busy || !S || chatTrip === (S.trip || null)) return;
  const want = S.trip || null; chatTrip = want;
  try {
    const r = await api('chat_history'); if (busy || (S.trip || null) !== want) { chatTrip = undefined; return; }
    msgs.innerHTML = '';
    r.messages.forEach(m => { bubble(m.role === 'user' ? 'u' : 'a', m.text); if (m.partial) bubble('e', '（这条回复当时可能不完整）'); });
    chatUp = null; chatStatus();
  } catch (e) { chatTrip = undefined; }
}
function chatMark(up, msg) {
  const el = $('cstat'); el.textContent = up ? '● 已连接' : '● 未连接'; el.className = up ? 'ok' : '';
  if (!up && msg && chatUp !== false) bubble('e', msg);
  chatUp = up;
}
async function chatStatus() { try { const r = await api('chat_status'); chatMark(r.connected, r.message); return r.connected; } catch (e) { chatMark(false, '没连上工作台服务。'); return false; } }
async function send() {
  const text = $('ctext').value.trim(); if (!text || busy) return;
  busy = true; $('csend').disabled = true; $('trip').disabled = true; const rev0 = S ? S.revision : null, trip0 = S ? S.trip : null; $('ctext').value = ''; bubble('u', text); const out = bubble('a', '…'); let got = '', done = false;
  try {
    const r = await fetch('api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: text, ctx: PGCUR === 'restore' ? 'restore' : ''})});
    if (!r.ok) { const j = await r.json().catch(() => ({})); out.className = 'm e'; out.textContent = j.error || ('出错了 ' + r.status); if (r.status >= 500) chatMark(false); }
    else {
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
      for (;;) { const {value, done: end} = await rd.read(); if (end) break; buf += dec.decode(value, {stream: true}); let i;
        while ((i = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
          if (!line.startsWith('data:')) continue; const d = line.slice(5).trim(); if (d === '[DONE]') { done = true; continue; }
          try { const t = (JSON.parse(d).choices || [{}])[0].delta; if (t && t.content) { got += t.content; setMsg(out, got); msgs.scrollTop = msgs.scrollHeight; } } catch (e) {} } }
      if (!got) out.textContent = '（没有收到回复）';
      if (!done) { const w = document.createElement('div'); w.className = 'm e'; w.textContent = '没有收到助手的结束信号（这一步耗时很长，或连接中断/超时）。已经做完的操作不会撤销；看右下角“助手”卡片：还在转就是还在做，等它结束再决定。'; msgs.appendChild(w); }
    }
  } catch (e) { out.className = 'm e'; out.textContent = '请求失败：' + e.message; }
  busy = false; $('csend').disabled = false; $('trip').disabled = false; await load();
  if (S && S.days.length && S.trip === trip0 && S.revision !== rev0) await refineRoutes(null);      // 助手改了行程：自动补查还没有真实路线的路段（已查过的不会重查）
}
$('csend').onclick = send; $('ctext').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } };
document.querySelectorAll('#chips button').forEach(b => b.onclick = () => { $('ctext').value = b.dataset.t; $('ctext').focus(); });
const fit = () => setTimeout(() => map.invalidateSize(), 50); window.addEventListener('resize', fit);
$('ctoggle').onclick = () => { $('chat').classList.toggle('hide'); syncSp2(); fit(); }; $('cclose').onclick = () => { $('chat').classList.add('hide'); syncSp2(); fit(); };
setInterval(async () => {
  if (document.hidden || !S || drag) return;
  try { const r = await api('rev'); if (r.revision !== S.revision || (r.trip || null) !== (S.trip || null)) { if (pending) { closePrev(); say('行程在别处被修改了，刚才的预览已取消。'); } await load(); } } catch (e) {}
}, 2000);
chatStatus(); setInterval(() => { if (!document.hidden && !$('chat').classList.contains('hide')) chatStatus(); }, 10000);
// ---- 三栏宽度可拖动（记住上次的宽度；双击分隔条恢复默认）----
const WK = {sw: ['--sw', 400, 240, 0.6], cw: ['--cw', 340, 260, 0.5]};
function wget(k) { try { return Number(localStorage.getItem('tsw_' + k)) || 0; } catch (e) { return 0; } }
function wset(k, v) { try { v === null ? localStorage.removeItem('tsw_' + k) : localStorage.setItem('tsw_' + k, String(v)); } catch (e) {} }
function clampW(k, v) { const [, , min, frac] = WK[k]; const other = k === 'sw' ? ($('chat').classList.contains('hide') ? 0 : $('chat').offsetWidth) : $('side').offsetWidth; return Math.max(min, Math.min(v, Math.min(innerWidth * frac, innerWidth - other - 280))); }
function applyW(k, v) { document.documentElement.style.setProperty(WK[k][0], v === null ? WK[k][1] + 'px' : clampW(k, v) + 'px'); fit(); }
function splitter(id, k, dir) {
  const el = $(id);
  el.onpointerdown = e => { e.preventDefault(); el.setPointerCapture(e.pointerId); el.classList.add('on'); document.body.classList.add('resizing'); const x0 = e.clientX, w0 = (k === 'sw' ? $('side') : $('chat')).offsetWidth; let last = null;
    el.onpointermove = m => { last = clampW(k, w0 + dir * (m.clientX - x0)); applyW(k, last); };
    el.onpointerup = () => { el.onpointermove = el.onpointerup = null; el.classList.remove('on'); document.body.classList.remove('resizing'); if (last !== null) wset(k, Math.round(last)); fit(); }; };
  el.ondblclick = () => { wset(k, null); applyW(k, null); };
}
splitter('sp1', 'sw', 1); splitter('sp2', 'cw', -1);
for (const k of ['sw', 'cw']) { const v = wget(k); if (v) applyW(k, v); }
window.addEventListener('resize', () => { for (const k of ['sw', 'cw']) { const v = wget(k); if (v) applyW(k, v); } });
function syncSp2() { $('sp2').style.display = $('chat').classList.contains('hide') ? 'none' : ''; }
syncSp2();
// ---- 更多：分享 / 游记 / 能力 ----
let moTab = 'share', shareHtml = '', toolsData = null, PH = {};
function openChatWith(t) { $('chat').classList.remove('hide'); syncSp2(); fit(); $('ctext').value = t; $('ctext').focus(); }
function moOpen(tab) { $('mo').classList.add('on'); moShow(tab || moTab); }
function moClose() { $('mo').classList.remove('on'); }
function moShow(tab) {
  moTab = tab;
  document.querySelectorAll('#mo .tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === tab));
  document.querySelectorAll('#mo .pane').forEach(p => p.classList.toggle('on', p.id === 'pane_' + tab));
  if (tab === 'share') shareRefresh(); else if (tab === 'hb') { HB.mode = 'plan'; hbLoad().then(hbPvSoon); } else if (tab === 'bill') blLoad(); else if (tab === 'vid') {} else if (tab === 'fp') fpLoad(false); else toolsLoad();
}
const shareOpts = () => ({lodging: $('sh_l').checked, costs: $('sh_c').checked, photos: $('sh_p').checked, theme: $('sh_t').value, basemap: $('sh_b').checked});
let shareSeq = 0;
async function shareRefresh() {
  const my = ++shareSeq;
  $('sh_err').textContent = '';
  try {
    const r = await api('share_preview', shareOpts()); if (my !== shareSeq) return; shareHtml = r.html; $('sh_frame').srcdoc = r.html;
    if (r.themes && !$('sh_t').options.length) r.themes.forEach(t => { const o = document.createElement('option'); o.value = t.id; o.textContent = t.label; $('sh_t').appendChild(o); });
    $('sh_b').disabled = !r.key_ok; if (!r.key_ok) $('sh_b').checked = false;
    $('sh_bn').textContent = !r.key_ok ? '没有检测到 AMAP_KEY：在你自己的终端里设置后重启工作台，这个选项才能用。' : (r.bm_note ? '部分底图没取到：' + r.bm_note + '（对应的图已退回无底图）' : '默认关闭。打开后会用你自己的高德 key 联网取底图，只发地图中心、缩放和图片大小，不发景点名和路线；底图范围内的酒店名可能出现在地图上。');
    $('sh_gif').disabled = !r.gif_ok; $('sh_gif').title = r.gif_ok ? '把路线图按天画出来的过程录成 GIF' : '需要先安装 Playwright 和 Pillow';
    $('sh_png').disabled = !r.png_ok; $('sh_png').title = r.png_ok ? '' : '需要先安装 Playwright：pip install playwright，再 python -m playwright install chromium';
    $('sh_p').disabled = !r.photo_count; if (!r.photo_count) $('sh_p').checked = false;
    $('sh_pn').textContent = r.photo_count ? '已有 ' + r.photo_count + ' 张，放在对应景点下面' : '还没有照片：在“编辑”模式下给景点添加';
  } catch (e) { if (my !== shareSeq) return; shareHtml = ''; $('sh_frame').srcdoc = ''; $('sh_err').textContent = e.message; }
}
function dl(href, name) { const a = document.createElement('a'); a.href = href; a.download = name; document.body.appendChild(a); a.click(); a.remove(); }
let LB = {list: [], i: 0}, PHID = {};
async function lbShow() {
  const p = LB.list[LB.i]; if (!p) return; $('lb').classList.add('on'); $('lb_img').src = p.thumb || '';
  $('lb_cap').textContent = (LB.list.length > 1 ? (LB.i + 1) + '/' + LB.list.length + ' ' : '') + (p.caption || '');
  $('lb_prev').style.display = $('lb_next').style.display = LB.list.length > 1 ? '' : 'none';
  try { const r = await api('photo_full', {id: p.id}); if (LB.list[LB.i] === p && r.uri) $('lb_img').src = r.uri; } catch (e) {}
}
function lbOpen(list, i) { LB = {list: list, i: i, edited: false}; lbShow(); }
document.querySelectorAll('#lb_act button').forEach(b => b.onclick = async ev => { ev.stopPropagation(); const p = LB.list[LB.i]; if (!p || !p.id) return;
  try { await api('photo_edit', {id: p.id, app: b.dataset.e}); LB.edited = b.dataset.e === 'preview'; $('lb_msg').textContent = LB.edited ? '已在“预览”打开；改完保存，关掉这里就会刷新' : '已在访达中显示'; } catch (e) { $('lb_msg').textContent = e.message; } });
function lbClose() { $('lb').classList.remove('on'); $('lb_img').src = ''; $('lb_msg').textContent = ''; if (LB && LB.edited) { LB.edited = false; try { hbLoad(); } catch (e) {} } }
$('lb_x').onclick = lbClose; $('lb_prev').onclick = () => { LB.i = (LB.i + LB.list.length - 1) % LB.list.length; lbShow(); }; $('lb_next').onclick = () => { LB.i = (LB.i + 1) % LB.list.length; lbShow(); };
$('lb').onclick = e => { if (e.target === $('lb')) lbClose(); };
document.addEventListener('keydown', e => { if (!$('lb').classList.contains('on')) return; if (e.key === 'Escape') { e.stopPropagation(); lbClose(); } else if (e.key === 'ArrowLeft') $('lb_prev').click(); else if (e.key === 'ArrowRight') $('lb_next').click(); }, true);
async function toolsLoad() {
  if (!toolsData) { try { toolsData = await api('tools'); } catch (e) { $('tl_out').textContent = e.message; return; } }
  renderTools();
}
let tlCat = '', tlKind = '';
function renderTools() {
  const q = $('tl_q').value.trim().toLowerCase();
  const match = t => !q || (t.name + t.summary + t.example).toLowerCase().includes(q);
  const kinds = [['', '全部'], ['read', '只读'], ['export', '导出'], ['change', '会改行程/数据']];
  const pool = toolsData.blocks.map(b => ({category: b.category, tools: b.tools.filter(t => match(t) && (!tlKind || t.kind === tlKind))}));
  const all = pool.reduce((n, b) => n + b.tools.length, 0);
  $('tl_n').textContent = '共 ' + toolsData.total + ' 个工具' + (all !== toolsData.total ? '，当前显示 ' + all : '');
  $('tl_kind').innerHTML = kinds.map(k => '<button class="tchip' + (tlKind === k[0] ? ' on' : '') + '" data-k="' + k[0] + '">' + k[1] + '</button>').join('');
  $('tl_cat').innerHTML = '<button class="tchip' + (tlCat === '' ? ' on' : '') + '" data-c="">全部类别<i>' + all + '</i></button>' + pool.filter(b => b.tools.length).map(b => '<button class="tchip' + (tlCat === b.category ? ' on' : '') + '" data-c="' + esc(b.category) + '">' + esc(b.category) + '<i>' + b.tools.length + '</i></button>').join('');
  let h = '<div class="tlg">';
  pool.forEach(b => { if (tlCat && b.category !== tlCat) return; b.tools.forEach(t => { h += '<div class="tcard"><div class="hd"><code>' + esc(t.name) + '</code><span class="kd ' + esc(t.kind) + '">' + esc(t.kind_text) + '</span></div><div class="sm2">' + esc(t.summary) + '</div><a href="#" data-ex="' + esc(t.example) + '" title="放进聊天输入框，由你确认后发送">“' + esc(t.example) + '”</a></div>'; }); });
  h += '</div>';
  if (all === 0) h = '<div class="tlnote" style="margin-top:14px">没有匹配的能力，换个词试试。</div>';
  h += '<details class="tlpro"><summary>承诺（' + toolsData.promises.length + ' 条）</summary><ul>' + toolsData.promises.map(p => '<li>' + esc(p) + '</li>').join('') + '</ul></details>';
  $('tl_out').innerHTML = h;
  $('tl_out').querySelectorAll('a[data-ex]').forEach(a => a.onclick = ev => { ev.preventDefault(); moClose(); openChatWith(a.dataset.ex); });
  $('tl_kind').querySelectorAll('button').forEach(bt => bt.onclick = () => { tlKind = bt.dataset.k; renderTools(); });
  $('tl_cat').querySelectorAll('button').forEach(bt => bt.onclick = () => { tlCat = bt.dataset.c; renderTools(); });
}
async function loadPhotos() {
  try { const r = await api('photos'); PH = {}; PHID = {}; r.photos.forEach(p => { PHID[p.id] = p; if (p.place_id) (PH[p.place_id] = PH[p.place_id] || []).push(p); }); } catch (e) { PH = {}; }
}
function photoRow(row, pid) {
  const wrap = document.createElement('div'); wrap.className = 'phr';
  (PH[pid] || []).forEach(p => {
    const i = document.createElement('span'); i.className = 'pht'; i.title = p.caption || '';
    i.innerHTML = (p.thumb ? '<img src="' + esc(p.thumb) + '" alt="">' : '📷') + '<button title="删除这张照片">×</button>';
    i.querySelector('button').onclick = async ev => { ev.stopPropagation(); try { await api('photo_remove', {id: p.id}); await loadPhotos(); renderAll(); } catch (e) { say(e.message, true); } };
    i.querySelector('img') && (i.querySelector('img').onclick = ev => { ev.stopPropagation(); lbOpen(PH[pid], PH[pid].indexOf(p)); });
    wrap.appendChild(i);
  });
  const lab = document.createElement('label'); lab.className = 'addph'; lab.textContent = '＋照片'; lab.title = '添加你自己拍的照片（保存时会去掉定位信息）';
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp'; inp.hidden = true; lab.appendChild(inp); lab.onclick = ev => ev.stopPropagation();
  inp.onchange = () => {
    const f = inp.files[0]; if (!f) return;
    if (f.size > 20 * 1024 * 1024) { say('照片太大（最多 20MB）', true); return; }
    const rd = new FileReader();
    rd.onload = async () => { say('正在保存照片…'); try { await api('photo_add', {place_id: pid, caption: '', name: f.name, data: String(rd.result).split(',')[1] || ''}); say('已保存，并去掉了定位信息。'); await loadPhotos(); renderAll(); } catch (e) { say(e.message, true); } };
    rd.readAsDataURL(f);
  };
  wrap.appendChild(lab); row.querySelector('.sub').appendChild(wrap);
}

// ---- 导出前预览 ----
let pvSeq = 0, pvTimer = null;
async function hbStylePreview() {
  const my = ++pvSeq; $('hb_pvn').textContent = '正在生成预览…';
  try { const r = await api('hb_style_preview', {style: $('hb_style').value, photos: $('hb_ph').checked, card_photos: +$('hb_cp').value, edit: true}); if (my !== pvSeq) return; $('hb_pvf').srcdoc = r.page; $('hb_pvcf').srcdoc = r.card || '<p style="padding:40px">没有可预览的卡片</p>'; $('hb_pvn').textContent = ''; }
  catch (e) { if (my === pvSeq) $('hb_pvn').textContent = e.message; }
}
const hbPvSoon = () => { clearTimeout(pvTimer); if ($('rp_body').dataset.s === '5' || $('mo').classList.contains('on')) pvTimer = setTimeout(hbStylePreview, 250); };
$('hb_style').onchange = hbPvSoon; $('hb_cp').onchange = hbPvSoon; $('hb_ph').addEventListener('change', hbPvSoon);
document.querySelectorAll('.pvt button').forEach(b => b.onclick = () => { document.querySelectorAll('.pvt button').forEach(x => x.classList.toggle('on', x === b)); $('hb_pvf').style.display = b.dataset.k === 'page' ? '' : 'none'; $('hb_pvc').style.display = b.dataset.k === 'card' ? 'block' : 'none'; });

document.addEventListener('mouseover', e => { const t = e.target.closest && e.target.closest('[data-tip]'); if (!t) return; const r = t.getBoundingClientRect(), p = $('ptip'); p.textContent = t.dataset.tip; p.style.left = Math.max(8, r.left + r.width / 2 - p.offsetWidth / 2) + 'px'; p.style.top = (r.top - 34) + 'px'; p.className = 'on'; });
document.addEventListener('mouseout', e => { if (e.target.closest && e.target.closest('[data-tip]')) $('ptip').className = ''; });
// ---- 恢复行程：整页流程 ----
const RS = {step: 1, ok: false};
const RS_NAMES = ['选来源', '预览调整', '恢复', '编辑', '导出'];
function rsGo(n) {
  RS.step = n; $('rp_body').dataset.s = n;
  $('rp_steps').innerHTML = RS_NAMES.map((t, i) => '<span class="' + (i + 1 === n ? 'on' : i + 1 < n ? 'done' : '') + '" data-n="' + (i + 1) + '"><i>' + (i + 1 < n ? '✓' : i + 1) + '</i>' + t + '</span>').join('');
  $('rp_steps').querySelectorAll('.done').forEach(x => x.onclick = () => { if (RS.step !== 3) rsGo(+x.dataset.n); });
  $('rp_prev').style.visibility = n === 1 || n === 3 ? 'hidden' : '';
  $('rp_next').style.display = n === 3 ? 'none' : '';
  $('rp_next').textContent = n === 1 ? '下一步：预览' : n === 2 ? '恢复行程' : n === 4 ? '下一步：导出' : '导出在下面，完成后可返回';
  $('rp_next').style.display = n === 5 || n === 3 ? 'none' : '';
  $('rp_msg').textContent = n === 1 ? '填相册文件夹（或照片 App 相册），照片要带位置信息。' : n === 2 ? '先看看会得到几处；太碎就换“大景区”。' : n === 4 ? '改名字、调照片顺序、写几句话；选两处以上可合并。' : '';
  if (n === 3) { $('hb_list').textContent = ''; }
  $('rp_body').scrollTop = 0; if (n === 5) hbStylePreview();
  if ((n === 4 || n === 5) && PGCUR === 'restore') rmapFromHb();
}
function rsPreviewing(on, r, err) { if (RS.step === 1 && !on && r) rsGo(2); else if (RS.step === 1 && !on && err) $('rp_msg').textContent = err; $('rp_next').disabled = on; }
function rsDone(ok, err) { if (ok) rsGo(4); else { rsGo(2); $('rp_msg').textContent = err || ''; } }
var PGCUR = 'plan';
const CHAT_HOME = $('chat').parentNode, CHAT_NEXT = $('chat').nextSibling;
const CHIPS_PLAN = $('chips').innerHTML;
const CHIPS_RESTORE = '<button data-t="帮我把【照片文件夹路径】里的照片恢复成行程，先告诉我聚成了几个点，我确认后再继续。">恢复行程</button><button data-t="给这些点起名字：先看缩略图和候选地名，给我选，我确认后再改。">起地名</button><button data-t="给每一天起几个有意思的标题，我来选。">起标题</button><button data-t="帮我看看哪些点应该合并，列出来我确认。">合并建议</button><button data-t="把手册导出，风格用【手账】，带照片。">导出手册</button>';
function chatWire() { document.querySelectorAll('#chips button').forEach(b => b.onclick = () => { $('ctext').value = b.dataset.t; $('ctext').focus(); }); }
function chatPlace(where) {
  if (where === 'restore') { $('rp_chat').appendChild($('chat')); $('chat').classList.remove('hide'); $('chips').innerHTML = CHIPS_RESTORE; }
  else if ($('chat').parentNode !== CHAT_HOME) { CHAT_HOME.insertBefore($('chat'), CHAT_NEXT && CHAT_NEXT.parentNode === CHAT_HOME ? CHAT_NEXT : null); $('chips').innerHTML = CHIPS_PLAN; }
  chatWire();
}
// ---- 恢复页地图
let RMAP = null, RLAY = null, RTILE = null, RSEL = null;
const rpin = (n, sel) => L.divIcon({className: '', html: '<div class="rpin' + (sel ? ' sel' : '') + '"><b>' + n + '</b></div>', iconSize: [30, 30], iconAnchor: [4, 30]});
function rmapInit() {
  if (!RMAP) { RMAP = L.map('rmap', {zoomControl: false, attributionControl: true}); L.control.zoom({position: 'bottomright'}).addTo(RMAP); RMAP.setView([30, 110], 4); }
  if (S && S.map && S.map.tiles && (!RTILE || RTILE._url !== S.map.tiles.url)) { if (RTILE) RMAP.removeLayer(RTILE); RTILE = L.tileLayer(S.map.tiles.url, {subdomains: S.map.tiles.sub, maxZoom: 18, minZoom: 3, attribution: S.map.tiles.attr}).addTo(RMAP); }
  setTimeout(() => { try { RMAP.invalidateSize(); } catch (e) {} }, 60);
}
const DAYC = ['#c4553a', '#2f6f8f', '#7a9a5b', '#b0813a', '#8a5a9a', '#3a8a7a'];
function rmapDraw(pts, onclick) {
  rmapInit(); if (RLAY) RMAP.removeLayer(RLAY); RLAY = L.layerGroup().addTo(RMAP); RSEL = null;
  $('rmap_empty').classList.toggle('hide', pts.length > 0); if (!pts.length) return;
  const byDay = {}; pts.forEach(p => (byDay[p.day] = byDay[p.day] || []).push(p));
  Object.keys(byDay).forEach(d => { const c = DAYC[(+d - 1 + DAYC.length) % DAYC.length]; if (byDay[d].length > 1) L.polyline(byDay[d].map(p => p.pos), {color: c, weight: 3, opacity: .75, dashArray: '7 6'}).addTo(RLAY); });
  pts.forEach(p => { const m = L.marker(p.pos, {icon: rpin(p.n)}).addTo(RLAY); m._p = p; if (p.tip) m.bindTooltip(p.tip, {direction: 'top', offset: [10, -26]});
    m.on('click', () => { rmapSelect(m); if (onclick) onclick(p); }); p._m = m; });
  RMAP.fitBounds(L.latLngBounds(pts.map(p => p.pos)), {padding: [60, 60], maxZoom: 16});
}
function rmapSelect(m) { if (RSEL) RSEL.setIcon(rpin(RSEL._p.n)); RSEL = m; m.setIcon(rpin(m._p.n, true)); }
function rmapFromHb() {
  if (!HB.data || HB.mode !== 'restore') return;
  const pts = HB.data.stops.filter(x => x.restored && x.pos).map((x, i) => ({pos: x.pos, n: i + 1, day: x.day, id: x.id, tip: x.name}));
  $('rmap_chip').className = ''; $('rmap_chip').textContent = $('rp_gate').classList.contains('on') ? '' : '当前行程：' + HB.data.name + '（' + pts.length + ' 处）'; $('rmap_chip').style.display = $('rmap_chip').textContent ? '' : 'none';
  rmapDraw(pts, p => { const el = $('hb_' + p.id); if (el && RS.step === 4) { el.scrollIntoView({behavior: 'smooth', block: 'center'}); el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1400); } });
}
// ---- 助手运行过程（轮询 activity）
let ACT = {since: 0, evs: new Map(), timer: null, refreshT: null, boot: Date.now() / 1000};
const ACT_CHANGES = new Set(['import_photo_trip', 'merge_stops', 'delete_stop', 'autoname_stops', 'update_place', 'tag_regions', 'save_stop_story', 'set_day_title', 'new_trip', 'switch_trip', 'undo', 'remove_place', 'add_place', 'add_photo', 'remove_photo']);
function actRender() {
  const list = [...ACT.evs.values()].sort((a, b) => a.t0 - b.t0).slice(-14).reverse();
  const running = list.some(e => e.state === 'run');
  $('act_dot').className = 'dot ' + (running ? 'run' : list.length ? 'ok' : '');
  $('act_sub').textContent = running ? '正在做：' + list.find(e => e.state === 'run').label : list.length ? '刚刚完成 ' + list.length + ' 个动作' : '空闲';
  $('act_list').innerHTML = list.length ? list.map(e => '<div class="ev ' + e.state + '"><i>' + (e.state === 'run' ? '⏳' : e.state === 'ok' ? '✓' : '⚠') + '</i><div class="l"><b>' + esc(e.label || e.name) + '</b>' +
    (e.state === 'run' ? (e.args ? '<small>' + esc(e.args) + '</small>' : '') : '<small>' + esc(e.summary || e.args || '') + (e.ms >= 1000 ? ' · ' + (e.ms / 1000).toFixed(1) + ' 秒' : '') + '</small>') + '</div></div>').join('')
    : '<div class="none">助手还没有动作。可以在右边对话，或者在你用的 agent 里直接说“帮我恢复行程”，它每调用一次工具，这里就会出现一行。</div>';
}
async function actPoll() {
  if (PGCUR !== 'restore' || document.hidden) return;
  try {
    const r = await api('activity', {since: ACT.since}); let changed = false;
    r.events.forEach(e => { const old = ACT.evs.get(e.id); if (e.ts >= ACT.boot && (!old || old.state !== e.state)) actFollow(e); ACT.evs.set(e.id, e); ACT.since = Math.max(ACT.since, e.ts); if (e.state !== 'run' && (!old || old.state === 'run') && ACT_CHANGES.has(e.name) && e.state === 'ok') changed = true; });
    if (r.events.length) actRender();
    if (changed) { clearTimeout(ACT.refreshT); ACT.refreshT = setTimeout(async () => { try { await load(); await hbLoad(); } catch (e) {} }, 400); }
  } catch (e) {}
}
// 助手操作时，左侧跟着走：工具 → 第几步，并把来源、半径填进去
const ACT_STEP = {list_photo_albums: 1, restore_status: 1, new_restore_trip: 1, import_photo_trip: 3, export_handbook: 5, export_notes: 5, export_calendar: 5, scan_videos: 5, export_rough_cut: 5,
  view_stop: 4, autoname_stops: 4, tag_regions: 4, merge_stops: 4, delete_stop: 4, update_place: 4, save_stop_story: 4, set_day_title: 4, suggest_day_titles: 4};
function actFollow(e) {
  const n = ACT_STEP[e.name]; if (!n || PGCUR !== 'restore' || $('rp_gate').classList.contains('on')) return;
  if (e.state === 'run') {
    if (e.name === 'import_photo_trip' && e.args) {
      const g = k => { const m = e.args.match(new RegExp(k + '=([^，]*)')); return m ? m[1] : ''; };
      const al = g('album'), fo = g('folder'), rd = g('radius_m');
      if (al) { $('hb_src').value = 'album'; hbSrcUi(); if (![...$('hb_album').options].some(o => o.value === al)) $('hb_album').innerHTML = '<option value="' + esc(al) + '">' + esc(al) + '</option>'; $('hb_album').value = al; }
      else if (fo) { $('hb_src').value = 'folder'; hbSrcUi(); $('hb_folder').value = fo; }
      if (rd && [...$('hb_r').options].some(o => o.value === rd)) $('hb_r').value = rd;
    }
    if (RS.step !== n && !(n === 4 && RS.step === 5)) rsGo(n);
    $('rp_msg').textContent = '助手正在：' + (e.label || e.name);
  } else if (e.state === 'ok' && e.name === 'import_photo_trip') { rsGo(4); }
}
function actStart() { if (ACT.timer) return; ACT.since = ACT.since || (Date.now() / 1000 - 600); actRender(); actPoll(); ACT.timer = setInterval(actPoll, 1500); }
function actStop() { clearInterval(ACT.timer); ACT.timer = null; }
$('act_fold').onclick = () => $('rp_act').classList.toggle('fold');
$('rp_ctog').onclick = () => $('rp').classList.toggle('nochat');
function autoUi(on) { $('rp_autoc').checked = on; $('rp_auto').classList.toggle('on', on); $('rp_autot').textContent = on ? '自动：助手会把整个流程走完（含删除），到导出前停下等你点' : '逐步确认：助手每做一步改动前先问你'; }
async function autoLoad() { try { autoUi((await api('restore_mode', {})).auto); } catch (e) {} }
$('rp_autoc').onchange = async () => { const on = $('rp_autoc').checked; autoUi(on); try { await api('restore_mode', {auto: on}); toast(on ? '已打开自动执行：助手会直接做完，导出前停下' : '已改回逐步确认'); } catch (e) { autoUi(!on); toast(e.message, true); } };
window.addEventListener('resize', () => { if (PGCUR === 'restore' && RMAP) RMAP.invalidateSize(); });
const PG_MAP = {restore: ['rp_body', 'hb'], bill: ['pgb_bill', 'bill'], fp: ['pgb_fp', 'fp'], vid: ['pgb_vid', 'vid']};
async function pgShow(name, step) {
  PGCUR = name; await ensureKind(name); fillTripSel(); moClose(); $('home').classList.remove('on');
  chatPlace(name === 'restore' ? 'restore' : 'plan'); if (name === 'restore') { actStart(); autoLoad(); } else actStop(); rpGate();
  document.querySelectorAll('.pg').forEach(x => x.classList.remove('on'));
  ['hb', 'bill', 'fp', 'vid'].forEach(k => { const pn = $('pane_' + k); pn.classList.remove('on'); $('mo').querySelector('.box').appendChild(pn); });
  document.querySelectorAll('#topnav button[data-pg]').forEach(b => b.classList.toggle('on', b.dataset.pg === name));
  HB.mode = name === 'restore' ? 'restore' : 'plan';
  if (name === 'plan') { setTimeout(() => { try { map.invalidateSize(); } catch (e) {} }, 50); return; }
  const m = PG_MAP[name], pn = $('pane_' + m[1]);
  $(m[0]).appendChild(pn); pn.classList.add('on');
  $(name === 'restore' ? 'rp' : 'pg_' + name).classList.add('on');
  if (name === 'restore') return hbLoad().then(() => { rmapInit(); rmapFromHb(); return rsGo(step || (HB.data && HB.data.restored ? 4 : 1)); });
  if (name === 'bill') blLoad(); else if (name === 'fp') fpLoad(false);
}
const rsOpen = step => pgShow('restore', step);
$('rp_prev').onclick = () => rsGo(Math.max(1, RS.step - 1));
$('rp_next').onclick = () => {
  if (RS.step === 1) { $('rp_msg').textContent = ''; $('hb_pv').click(); }
  else if (RS.step === 2) { rsGo(3); $('hb_list').textContent = '正在读取照片并还原，几十秒内…'; $('hb_go').click(); }
  else if (RS.step === 4) rsGo(5);
};
document.querySelectorAll('#topnav button[data-pg]').forEach(b => b.onclick = () => pgShow(b.dataset.pg));
function homeMaybe() {
  try { if (sessionStorage.getItem('tsHome')) return; } catch (e) {}
  const r = TRIPS_R;                                                    // 每次新打开页面都先选“计划”还是“恢复”，并写出各自会接着哪个行程
  const hint = (id, k, empty) => { const t = r && !r.single ? lastTrip(r, k) : null; const el = $(id).querySelector('i'); if (el) el.textContent = t ? '接着上次：「' + t.name + '」' : empty; };
  hint('home_plan', 'plan', '新建一个行程开始'); hint('home_restore', 'restore', '从照片还原走过的路线');
  $('home').classList.add('on');
}
function homeDone() { try { sessionStorage.setItem('tsHome', '1'); } catch (e) {} $('home').classList.remove('on'); }
$('home_plan').onclick = () => { homeDone(); pgShow('plan'); }; $('home_restore').onclick = () => { homeDone(); pgShow('restore'); };
$('more').onclick = () => moOpen(); $('mo_close').onclick = moClose; $('mo').onclick = e => { if (e.target === $('mo')) moClose(); };
$('sh_cal').onclick = async () => { $('sh_err').textContent = '正在生成…'; try { const r = await api('cal_export', {}); $('sh_err').textContent = r.message; } catch (e) { $('sh_err').textContent = e.message; } };
let VD_ALBUM = '';
const vdSrc = () => VD_ALBUM ? {album: VD_ALBUM} : {folder: $('vd_path').value};
$('vd_path').oninput = () => { VD_ALBUM = ''; };
$('vd_scan').onclick = async () => { $('vd_msg').textContent = '正在读取视频信息…'; try { const r = await api('video_scan', vdSrc()); $('vd_msg').textContent = r.message; } catch (e) { $('vd_msg').textContent = e.message; } };
$('vd_cut').onclick = async () => {
  $('vd_out').textContent = '正在粗剪，素材多时要几分钟，请不要关闭页面…'; $('vd_cut').disabled = true;
  try { const r = await api('video_cut', {...vdSrc(), target_seconds: +$('vd_t').value, clip_max: +$('vd_m').value, cards: $('vd_c').checked, jianying_dir: $('vd_jy').value}); $('vd_out').textContent = r.message; }
  catch (e) { $('vd_out').textContent = e.message; } finally { $('vd_cut').disabled = false; }
};
async function fpLoad(withBm) {
  $('fp_msg').textContent = '正在汇总…';
  try { const r = withBm ? await api('fp_build', {basemap: true}) : await api('fp_state'); $('fp_msg').textContent = r.message; $('fp_frame').srcdoc = r.html || ''; }
  catch (e) { $('fp_msg').textContent = e.message; $('fp_frame').srcdoc = ''; }
}
$('fp_go').onclick = () => fpLoad($('fp_bm').checked);
document.querySelectorAll('#mo .tabs button').forEach(b => b.onclick = () => moShow(b.dataset.t));
['sh_l', 'sh_c', 'sh_p', 'sh_t', 'sh_b'].forEach(id => $(id).onchange = shareRefresh);
$('sh_html').onclick = () => { if (!shareHtml) return; const u = URL.createObjectURL(new Blob([shareHtml], {type: 'text/html'})); dl(u, '行程分享.html'); setTimeout(() => URL.revokeObjectURL(u), 2000); };
$('sh_gif').onclick = async () => { $('sh_err').textContent = '正在录制路线动画（几秒钟）…'; $('sh_gif').disabled = true; try { const r = await api('share_gif', shareOpts()); dl(r.gif, '路线动画.gif'); $('sh_err').textContent = ''; } catch (e) { $('sh_err').textContent = e.message; } $('sh_gif').disabled = false; };
$('sh_png').onclick = async () => { $('sh_err').textContent = '正在生成长图…'; $('sh_png').disabled = true; try { const r = await api('share_image', shareOpts()); dl(r.png, '行程分享.png'); $('sh_err').textContent = ''; } catch (e) { $('sh_err').textContent = e.message; } $('sh_png').disabled = false; };

let HB = {mode: 'restore', data: null, sel: new Set()};
async function hbLoad() {
  try { HB.data = await api('hb_state'); } catch (e) { $('hb_list').textContent = e.message; return; }
  hbRender(); if (PGCUR === 'restore' && !(RS.step === 2)) rmapFromHb();
}
function hbRender() {
  const d = HB.data, restore = HB.mode === 'restore';
  document.querySelectorAll('.seg button').forEach(b => b.classList.toggle('on', b.dataset.m === HB.mode));
  $('hb_vidline').style.display = restore && d.videos ? 'inline-flex' : 'none'; $('hb_vidn').textContent = (d.album_videos ? '照片 App 相册里有 ' : '照片文件夹里有 ') + d.videos + ' 段视频，可以做粗剪（只用于粗剪）';
  $('hb_import').style.display = restore ? '' : 'none'; $('hb_merge').style.display = restore && d.restored ? '' : 'none';
  $('hb_hint').textContent = restore ? '把拍过的照片还原成走过的行程，边看边改，满意了再导出。' : '给计划里的每个景点配照片和文字，做成可以带着走、也可以分享的手册。';
  const rows = d.stops.filter(s => !restore || s.restored);
  if (!rows.length) { $('hb_list').innerHTML = '<div class="tlnote">' + (restore ? '还没有恢复过的行程：在上面填相册文件夹，点“读取照片”。' : '这个行程还没有排好的景点。') + '</div>'; return; }
  let lastDay = 0;
  $('hb_list').innerHTML = rows.map(s => { let h = ''; if (s.day !== lastDay) { lastDay = s.day; h = '<div class="dayt"><b>第 ' + s.day + ' 天</b><input class="dti" data-day="' + s.day + '" maxlength="20" placeholder="给这一天起个标题（可不填，默认“第 ' + s.day + ' 天”）" value="' + esc((d.day_titles || {})[s.day] || '') + '"></div>'; } return h + hbCard(s, restore); }).join('');
  document.querySelectorAll('.dti').forEach(i => i.onchange = async () => { try { const r = await api('hb_day_title', {day: +i.dataset.day, title: i.value}); toast(r.message); hbPvSoon(); } catch (e) { toast(e.message, true); } });
  rows.forEach(s => hbWire(s));
  $('hb_exp').disabled = false;
}
function hbCard(s, restore) {
  const st = s.story || {}, facts = (st.facts || []).concat([{text: '', source: ''}]);
  const ph = s.photos.map((p, i) => '<div class="c' + (i === 0 ? ' cover' : '') + (p.hide ? ' off' : '') + '" draggable="true" data-p="' + esc(p.id) + '"><img src="' + esc(p.thumb) + '" alt="" draggable="false">' +
    '<div class="bt">' + (i ? '<button data-a="front" title="设为封面">★</button>' : '<span class="tm" title="当前封面">★</span>') + '<button data-a="hide" title="' + (p.hide ? '现在不放进手册，点一下放进去' : '放进手册（点一下改为不放）') + '">' + (p.hide ? '🚫' : '👁') + '</button><button data-a="del" title="删除这张">✕</button></div></div>').join('');
  const add = s.photos.length < HB.data.max_photos ? '<label class="add" data-a="add">＋照片<input type="file" accept="image/jpeg,image/png,image/webp" hidden></label>' : '';
  return '<div class="hbs" id="hb_' + esc(s.id) + '"><div class="h">' + (restore ? '<input type="checkbox" class="sel" ' + (HB.sel.has(s.id) ? 'checked' : '') + ' title="选中后可合并">' : '') +
    '<span class="dy">第 ' + s.day + ' 天</span>' + (s.region ? '<span class="dy">' + esc(s.region) + '</span>' : '') + '<input class="nm" value="' + esc(s.name) + '" maxlength="40">' + (s.start ? '<span class="tm">' + esc(s.start) + '–' + esc(s.end) + '</span>' : '') + (restore ? '<button data-a="delstop" class="dels" title="删除这个地点（连同它的照片和文字，原照片不动）">🗑 删除地点</button>' : '') + '</div>' +
    '<div class="hbp">' + ph + add + '</div>' +
    '<div class="lb2">我的话 <button data-a="ai"' + (HB.data.vision ? '' : ' disabled title="还没有配置能读图的模型（DASHSCOPE_API_KEY、TRIPSIGHT_VISION_MODEL），先留空或自己写"') + '>用 AI 看图起草</button><span class="tlnote">草稿不会自动保存，改完点“保存”</span></div>' +
    '<textarea class="imp" maxlength="300" placeholder="写几句这里的光线、天气、心情（300 字内）">' + esc(st.impression || '') + '</textarea>' +
    '<div class="lb2">地点介绍（每条要有来源，没有来源的不要写）</div>' +
    facts.map(f => '<div class="fr"><input class="ft" placeholder="一句话介绍" value="' + esc(f.text) + '"><input class="fs" placeholder="来源网址或“高德地图”" value="' + esc(f.source) + '"></div>').join('') +
    '<div style="margin-top:6px"><button data-a="save" class="pri">保存</button> <span class="tlnote hbm"></span></div></div>';
}
function hbWire(s) {
  const box = $('hb_' + s.id), m = box.querySelector('.hbm');
  const note = (t, err) => { m.textContent = t; m.style.color = err ? '#b91c1c' : '#555'; if (t) toast(t, err); };
  const sel = box.querySelector('.sel'); if (sel) sel.onchange = () => { sel.checked ? HB.sel.add(s.id) : HB.sel.delete(s.id); };
  const lbList = s.photos.map(p => ({id: p.id, thumb: p.thumb, caption: ''}));
  let dragId = null;
  box.querySelectorAll('.hbp .c').forEach((c, i) => {
    c.ondragstart = ev => { dragId = c.dataset.p; c.classList.add('drag'); ev.dataTransfer.effectAllowed = 'move'; ev.dataTransfer.setData('text/plain', dragId); };
    c.ondragend = () => { c.classList.remove('drag'); box.querySelectorAll('.hbp .over').forEach(x => x.classList.remove('over')); };
    c.ondragover = ev => { if (dragId && dragId !== c.dataset.p) { ev.preventDefault(); c.classList.add('over'); } };
    c.ondragleave = () => c.classList.remove('over');
    c.ondrop = async ev => { ev.preventDefault(); if (!dragId || dragId === c.dataset.p) return;
      try { await api('hb_photo_move', {id: dragId, to: 'place', before: c.dataset.p}); await hbLoad(); } catch (e) { note(e.message, true); } };
    c.querySelector('img').onclick = () => lbOpen(lbList, i);
    c.querySelectorAll('button').forEach(b => b.onclick = async () => {
      try {
        if (b.dataset.a === 'del') { if (!(await ask('从「' + s.name + '」删掉第 ' + (i + 1) + ' 张照片？\n只删手册里的这一份，你的原图不动。'))) return; await api('photo_remove', {id: c.dataset.p}); toast('已从「' + s.name + '」删除第 ' + (i + 1) + ' 张照片'); }
        else await api('hb_photo_move', {id: c.dataset.p, to: b.dataset.a});
        await hbLoad();
      } catch (e) { note(e.message, true); }
    });
  });
  const ds = box.querySelector('.dels');
  if (ds) ds.onclick = async () => {
    if (!(await ask('删除地点「' + s.name + '」（第 ' + s.day + ' 天）？\n它的 ' + s.photos.length + ' 张照片副本和文字都会一起去掉；你相册里的原照片不动。'))) return;
    try { const r = await api('hb_stop_delete', {place_id: s.id}); HB.sel.delete(s.id); toast(r.message); await load(); await hbLoad(); hbPvSoon && hbPvSoon(); } catch (e) { note(e.message, true); }
  };
  const inp = box.querySelector('.add input');
  if (inp) inp.onchange = () => {
    const f = inp.files[0]; if (!f) return;
    if (f.size > 20 * 1024 * 1024) { note('照片太大（最多 20MB）', true); return; }
    const rd = new FileReader();
    rd.onload = async () => { try { note('正在保存照片…'); await api('photo_add', {place_id: s.id, caption: '', data: String(rd.result).split(',')[1] || ''}); await hbLoad(); } catch (e) { note(e.message, true); } };
    rd.readAsDataURL(f);
  };
  const ai = box.querySelector('[data-a=ai]');
  ai.onclick = async () => {
    ai.disabled = true; note('正在请模型看图（只发一张缩小的拼图）…');
    try { const r = await api('hb_describe', {place_id: s.id}); box.querySelector('.imp').value = r.draft; note('已放进文本框，是草稿，请自己读一遍再保存。'); } catch (e) { note(e.message, true); }
    ai.disabled = !HB.data.vision;
  };
  box.querySelector('[data-a=save]').onclick = async () => {
    const facts = [...box.querySelectorAll('.fr')].map(r => ({text: r.querySelector('.ft').value.trim(), source: r.querySelector('.fs').value.trim()})).filter(f => f.text || f.source);
    try {
      await api('hb_edit', {place_id: s.id, name: box.querySelector('.nm').value, impression: box.querySelector('.imp').value, facts: facts});
      note('已保存'); try { await load(); } catch (e) {}
    } catch (e) { note(e.message, true); }
  };
}
document.querySelectorAll('.seg button').forEach(b => b.onclick = () => { HB.mode = b.dataset.m; if (HB.data) hbRender(); });
$('hb_go').onclick = async () => {
  $('hb_go').disabled = true; $('hb_list').textContent = '正在读取照片，几十秒内…';
  try { const r = await api('hb_import', hbSrc({radius_m: +$('hb_r').value, track: $('hb_track').value, link_photos: $('hb_link').checked, start_date: $('hb_d1').value, end_date: $('hb_d2').value})); say(r.message.split('\n')[0]); await load(); await hbLoad(); if (window.rsDone) rsDone(true); } catch (e) { $('hb_list').textContent = e.message; if (window.rsDone) rsDone(false, e.message); }
  $('hb_go').disabled = false;
};

const hbSrc = o => Object.assign(o, $('hb_src').value === 'album' ? {album: $('hb_album').value} : {folder: $('hb_folder').value});
function hbSrcUi() { const a = $('hb_src').value === 'album'; $('hb_folder').style.display = a ? 'none' : ''; document.querySelectorAll('[data-to=hb_folder]').forEach(x => x.style.display = a ? 'none' : ''); $('hb_album').style.display = a ? '' : 'none'; $('hb_al').style.display = a ? '' : 'none'; }
$('hb_src').onchange = hbSrcUi;
$('hb_al').onclick = async () => {
  try { const r = await api('hb_albums', {}); $('hb_album').innerHTML = r.albums.map(a => '<option value="' + esc(a.name) + '">' + esc(a.name) + '（' + a.count + ' 张）</option>').join('') || '<option value="">没有相册</option>'; }
  catch (e) { $('hb_pvo').textContent = e.message; }
};
const bmOn = () => { try { return localStorage.getItem('tsRpBm') !== '0'; } catch (e) { return true; } };
$('hb_pvbm').checked = bmOn(); $('hb_pvbm').onchange = () => { try { localStorage.setItem('tsRpBm', $('hb_pvbm').checked ? '1' : '0'); } catch (e) {} if ($('hb_pvo').innerHTML) $('hb_pv').click(); };
$('hb_pv').onclick = async () => {
  $('hb_pvo').textContent = '正在预览…'; if (window.rsDone) rsPreviewing(true);
  try {
    const r = await api('hb_preview', hbSrc({radius_m: +$('hb_r').value, basemap: $('hb_pvbm').checked, start_date: $('hb_d1').value, end_date: $('hb_d2').value}));
    const W = r.basemap ? r.bm_w : 760, H = r.basemap ? r.bm_h : 420; let pts;
    if (r.basemap) pts = r.xy.map(a => ({x: a[0], y: a[1]}));
    else { const la = r.stops.map(s => s.lat), lo = r.stops.map(s => s.lon), k = Math.cos((Math.min(...la) + Math.max(...la)) / 2 * Math.PI / 180), dx = (Math.max(...lo) - Math.min(...lo)) * k || 1e-6, dy = (Math.max(...la) - Math.min(...la)) || 1e-6, sc = Math.min((W - 80) / dx, (H - 80) / dy);
      pts = r.stops.map(s => ({x: 40 + (s.lon - Math.min(...lo)) * k * sc, y: H - 40 - (s.lat - Math.min(...la)) * sc})); }
    const svg = '<div class="pvmap"><svg viewBox="0 0 ' + W + ' ' + H + '">' + (r.basemap ? '<image href="' + r.basemap + '" width="' + W + '" height="' + H + '"/>' : '') +
      r.stops.map((s, i) => '<circle data-i="' + i + '" cx="' + pts[i].x.toFixed(0) + '" cy="' + pts[i].y.toFixed(0) + '" r="' + (6 + Math.min(14, Math.sqrt(s.n) * 1.6)).toFixed(0) + '" fill="#c4553a77" stroke="#c4553a" stroke-width="2.5" data-tip="' + esc(s.day + ' ' + s.start + '–' + s.end + ' · ' + s.n + ' 张') + '"></circle>').join('') + '</svg></div>';
    $('hb_pvo').innerHTML = '<div class="tlnote">按这个大小会得到 <b>' + r.kept + '</b> 处（另有 ' + r.dropped + ' 个照片太少的路过点不放进行程）；读到 ' + r.photos + ' 张带位置的照片' + (r.untagged ? '，' + r.untagged + ' 张没有定位' + (r.guessed ? '（其中 ' + r.guessed + ' 张可按拍摄时间推测挂靠）' : '') : '') + '。点一个圆看那里的照片；觉得太碎就换“大景区”再预览。' + (r.basemap_note ? ' <b>' + esc(r.basemap_note) + '</b>' : '') + '</div>' + svg +
      (r.span_days > 30 ? '<div class="tlnote">这些照片从 ' + esc(r.first) + ' 到 ' + esc(r.last) + '，跨了 ' + r.span_days + ' 天：会按拍摄日期分成一天天，没照片的日子不显示。只想恢复其中一段？在上面选“只恢复这段日期”，或点照片多的月份：' +
        r.months.slice().sort((a, b) => b.n - a.n).slice(0, 12).map(m => '<button class="pk hbm" data-m="' + m.m + '">' + m.m + '（' + m.n + '）</button>').join(' ') + '</div>' : '') +
      (r.videos ? '<div class="tlnote">同时在' + ($('hb_src').value === 'album' ? '这个相册' : '这个文件夹（只看这一层）') + '里发现 <b>' + r.videos + '</b> 段视频：恢复行程后可以直接生成粗剪；视频只用于粗剪，不会放进手册。</div>' : '') +
      '<div class="pvd" id="hb_pvd"><span class="tlnote">点右边地图上的图钉，这里会显示那处的时间和照片。</span></div>';
    $('hb_pvo').querySelectorAll('.hbm').forEach(b => b.onclick = () => { const [y, m] = b.dataset.m.split('-'); $('hb_d1').value = b.dataset.m + '-01'; $('hb_d2').value = b.dataset.m + '-' + String(new Date(+y, +m, 0).getDate()).padStart(2, '0'); $('hb_pv').click(); });
    $('hb_pvo').querySelectorAll('circle').forEach(c => c.onclick = () => { const s = r.stops[+c.dataset.i]; $('hb_pvo').querySelectorAll('circle').forEach(x => x.classList.toggle('sel', x === c));
      $('hb_pvd').innerHTML = '<b>' + esc(s.day) + ' ' + esc(s.start) + '–' + esc(s.end) + '</b> · ' + s.n + ' 张照片<br>' + (s.thumbs.length ? s.thumbs.map(u => '<img src="' + esc(u) + '" alt="">').join('') : '<span class="tlnote">（这处没有可预览的缩略图）</span>'); });
    $('rmap_chip').className = 'pv'; $('rmap_chip').textContent = '预览：' + r.kept + ' 处，还没有恢复成行程（现有行程不受影响）';
    { const days = [...new Set(r.stops.map(x => x.day))].sort();
      rmapDraw(r.stops.filter(x => x.pos).map((x, i) => ({pos: x.pos, n: i + 1, day: days.indexOf(x.day) + 1, tip: x.day + ' ' + x.start + '–' + x.end + ' · ' + x.n + ' 张', _s: x})), p => { const s = p._s;
        $('hb_pvd').innerHTML = '<b>' + esc(s.day) + ' ' + esc(s.start) + '–' + esc(s.end) + '</b> · ' + s.n + ' 张照片<br>' + (s.thumbs.length ? s.thumbs.map(u => '<img src="' + esc(u) + '" alt="">').join('') : '<span class="tlnote">（这处没有可预览的缩略图）</span>'); }); }
    if (window.rsDone) rsPreviewing(false, r);
  } catch (e) { $('hb_pvo').textContent = e.message; if (window.rsDone) rsPreviewing(false, null, e.message); }
};
$('hb_r').onchange = () => { if ($('hb_pvo').innerHTML && $('hb_folder').value) $('hb_pv').click(); };
window.addEventListener('message', async ev => {
  const m = ev.data; if (!m || !m.tripsight || ev.source !== $('hb_pvf').contentWindow) return;
  try {
    if (m.k === 'title') { const r = await api('hb_day_title', {day: +m.id, title: m.text}); toast(r.message); }
    else if (m.k === 'imp') { const t = m.text.replace(/^[“"]|[”"]$/g, ''); await api('hb_edit', {place_id: m.id, impression: t}); toast(t ? '已保存“我的话”' : '已清除这段话'); }
    else if (m.k === 'scale') { await api('hb_photo_scale', {id: m.id, scale: m.scale}); toast('照片大小已保存（' + m.scale + '%）'); }
    hbLoad();
  } catch (e) { toast(e.message, true); hbPvSoon(); }
});
$('hb_tovid').onclick = async () => { const d = HB.data; await pgShow('vid'); if (!d) return; if (d.album) { VD_ALBUM = d.album; $('vd_path').value = '照片 App 相册：' + d.album; $('vd_scan').click(); } else if (d.folder) { VD_ALBUM = ''; $('vd_path').value = d.folder; $('vd_scan').click(); } };
$('hb_an').onclick = async () => { if (!(await ask('把名字还是“停留点”或“区县 · 时间”的点重新查一次地名？\n会把这些点的坐标发给高德（用你自己的 key）；你手动改过的名字不会动。'))) return;
  try { say('正在查地名…'); const r = await api('hb_autoname', {}); say(r.message); toast(r.message); await load(); await hbLoad(); } catch (e) { say(e.message, true); } };
async function dirLoad(body) { try { const r = await api('export_dir', body || {}); $('hb_dirp').textContent = r.path; $('hb_dirdef').style.display = r.custom && !r.locked ? '' : 'none'; $('hb_dirpick').disabled = r.locked; return r; } catch (e) { toast(e.message, true); } }
$('hb_dirpick').onclick = async () => { try { const r = await api('pick_path', {kind: 'folder', prompt: '请选择导出文件夹'}); if (r.path) { const d = await dirLoad({path: r.path}); if (d) toast('导出文件夹已改为 ' + d.path); } } catch (e) { toast(e.message, true); } };
$('hb_dirdef').onclick = async () => { const d = await dirLoad({path: ''}); if (d) toast('已恢复默认导出文件夹：' + d.path); };
dirLoad();
$('hb_rg').onclick = async () => { try { say('正在查城市/区…'); const r = await api('hb_regions', {}); say(r.message); await hbLoad(); } catch (e) { say(e.message, true); } };
$('hb_mgo').onclick = async () => {
  try { const r = await api('hb_merge', {place_ids: [...HB.sel], name: $('hb_mname').value}); say(r.message); HB.sel.clear(); $('hb_mname').value = ''; await load(); await hbLoad(); } catch (e) { say(e.message, true); }
};
$('hb_sp').onchange = () => { $('hb_spc').style.display = $('hb_sp').checked ? '' : 'none'; };
$('hb_open').onclick = async () => { try { const r = await api('reveal_exports', {}); $('hb_out').textContent = '已打开：' + r.path; } catch (e) { $('hb_out').textContent = e.message; } };
$('hb_exp').onclick = async () => {
  const formats = [...document.querySelectorAll('.hbf:checked')].map(x => x.value);
  $('hb_exp').disabled = true; $('hb_out').textContent = '正在生成…（卡片图和 PDF 需要几十秒）';
  try { const r = await api('hb_export', {formats: formats, style: $('hb_style').value, photos: $('hb_ph').checked, card_photos: +$('hb_cp').value, basemap: $('hb_bm').checked, thumb_pins: $('hb_pin').checked, spending: $('hb_sp').checked, spending_cats: [...document.querySelectorAll('.hbsc:checked')].map(x => x.value)}); $('hb_out').textContent = r.message; toast('已导出，文件在 ' + $('hb_dirp').textContent + ' 下'); } catch (e) { $('hb_out').textContent = e.message; toast(e.message, true); }
  $('hb_exp').disabled = false;
};

let BL = null;
async function blLoad() {
  try { BL = await api('bills_state'); } catch (e) { $('bl_list').textContent = e.message; return; }
  $('bl_watch').value = BL.watch.join('\n'); $('bl_watchn').textContent = BL.watch.length ? '（正在盯 ' + BL.watch.length + ' 个文件夹）' : '（还没设置）';
  $('bl_steps').innerHTML = BL.shortcut.map(x => '<li>' + esc(x) + '</li>').join('');
  blRender();
}
function blReport() {
  const r = BL.report; if (!r) { $('bl_rep').innerHTML = ''; return; }
  const f = r.files || [], first = f.map(x => x.first).filter(Boolean).sort()[0], last = f.map(x => x.last).filter(Boolean).sort().slice(-1)[0];
  let why = '';
  if (!r.trip_start) why = '这个行程还没有具体日期，所以没有记进行程账本。下面选“全部账单”或“自选日期”就能看统计。';
  else if (r.added === 0 && r.outside > 0 && !r.duplicate) why = '<b>没有一笔记进账本：</b>账单里的消费日期是 ' + esc(first || '?') + '～' + esc(last || '?') + '，而这个行程的日期是 ' + esc(r.trip_start) + '～' + esc(r.trip_end) + '，两段时间没有重合。检查是不是导了别的月份的账单，或者行程日期设得不对（恢复行程的日期来自照片拍摄时间）。想单独看这段账单的花销，点下面的“全部账单”。';
  else if (r.added === 0 && r.duplicate > 0) why = '这些消费之前已经导入过了，没有新增。';
  $('bl_rep').innerHTML = '<div class="rep"><div class="rh">上次导入 · ' + esc(r.at || '') + '</div><div class="bls"><div class="k"><span class="tlnote">新记</span><b>' + r.added + '</b>笔</div><div class="k"><span class="tlnote">行程期间之外</span><b>' + r.outside + '</b>笔</div><div class="k"><span class="tlnote">重复</span><b>' + r.duplicate + '</b>笔</div>' +
    '<div class="k"><span class="tlnote">账单覆盖</span><b style="font-size:14px">' + esc(first || '—') + '～' + esc(last || '—') + '</b></div><div class="k"><span class="tlnote">行程期间</span><b style="font-size:14px">' + (r.trip_start ? esc(r.trip_start) + '～' + esc(r.trip_end) : '未设日期') + '</b></div></div>' +
    (why ? '<div class="why">' + why + '</div>' : '') + f.map(x => '<div class="tlnote">' + esc(x.name) + '：' + esc(x.source) + '账单，读到 ' + x.rows + ' 笔</div>').join('') + '</div>';
}
let BL_MODE = 'trip', BL_RANGE = {start: '', end: ''};
async function blView() { const r = await api('bills_range', BL_MODE === 'all' ? {} : BL_RANGE); BL.view = r; return r; }
function blModeUi() {
  const pl = BL.pool || {count: 0}, ms = [['trip', '行程期间'], ['all', '全部账单' + (pl.count ? '（' + pl.first.slice(5) + '～' + pl.last.slice(5) + '）' : '')], ['custom', '自选日期']];
  $('bl_mode').innerHTML = '<div class="seg">' + ms.map(m => '<button data-m="' + m[0] + '"' + (BL_MODE === m[0] ? ' class="on"' : '') + '>' + esc(m[1]) + '</button>').join('') + '</div>' +
    (BL_MODE === 'custom' ? ' <input type="date" id="bl_a" value="' + BL_RANGE.start + '"> ～ <input type="date" id="bl_b" value="' + BL_RANGE.end + '">' : '') +
    (BL_MODE !== 'trip' && !pl.count ? ' <span class="tlnote">还没有账单：先导入一个微信/支付宝账单。</span>' : '') +
    (BL_MODE === 'trip' ? ' <span class="tlnote">只统计这个行程日期内的消费，可以改类别、对应到景点。</span>' : ' <span class="tlnote">不受行程日期限制，看账单里所有消费。</span>');
  $('bl_mode').querySelectorAll('button').forEach(b => b.onclick = () => { BL_MODE = b.dataset.m; if (BL_MODE === 'custom' && !BL_RANGE.start && pl.count) { BL_RANGE = {start: pl.first, end: pl.last}; } blRender(); });
  if ($('bl_a')) { $('bl_a').onchange = () => { BL_RANGE.start = $('bl_a').value; blRender(); }; $('bl_b').onchange = () => { BL_RANGE.end = $('bl_b').value; blRender(); }; }
}
async function blRender() {
  blReport(); blModeUi();
  const ro = BL_MODE !== 'trip', V = ro ? await blView() : BL, s = V.summary;
  if (!V.rows.length) { $('bl_sum').innerHTML = ''; $('bl_list').innerHTML = '<div class="tlnote">' + (ro ? '这段日期里没有消费记录。换一段日期，或选“全部账单”。' : BL.has_dates ? (BL.report ? '账本里还没有这个行程期间的消费，分析需要先有消费记录。' : '还没有导入账单。选一个微信/支付宝账单文件，点“导入”。') : '这个行程还没有设具体日期，没法筛出旅行期间的消费：先在助手里设置日期。') + '</div>'; return; }
  const max = Math.max(...Object.values(s.by_category), 1), days = Object.keys(s.by_day), maxd = Math.max(...Object.values(s.by_day), 1);
  const byPlace = {}; V.rows.filter(r => !r.excluded && r.place_id).forEach(r => { byPlace[r.place_id] = (byPlace[r.place_id] || 0) + r.amount; });
  const pname = id => (V.places.find(p => p.id === id) || {}).name || id;
  const top = V.rows.filter(r => !r.excluded).sort((a, b) => b.amount - a.amount).slice(0, 5);
  $('bl_sum').innerHTML = '<div class="bls"><div class="k"><span class="tlnote">合计</span><b>' + s.total + ' 元</b>' + s.count + ' 笔</div>' +
    '<div class="k"><span class="tlnote">日均</span><b>' + (s.total / Math.max(days.length, 1)).toFixed(0) + ' 元</b>' + days.length + ' 天有消费</div>' +
    '<div class="k"><span class="tlnote">单笔平均</span><b>' + (s.total / Math.max(s.count, 1)).toFixed(0) + ' 元</b></div>' +
    (s.excluded_count ? '<div class="k"><span class="tlnote">不计入</span><b>' + s.excluded_count + ' 笔</b>转账/群收款 ' + s.excluded_total + ' 元</div>' : '') + '</div>' +
    '<div class="bgrid"><div class="bcard"><div class="rh">按类别</div>' + Object.entries(s.by_category).sort((a, b) => b[1] - a[1]).map(([k, v]) => '<div class="brow"><span>' + esc(k) + '</span><div class="bt"><div class="blbar" style="width:' + Math.round(v / max * 100) + '%"></div></div><b>' + v + '</b><i>' + Math.round(v / s.total * 100) + '%</i></div>').join('') + '</div>' +
    '<div class="bcard"><div class="rh">按天</div>' + Object.entries(s.by_day).map(([k, v]) => '<div class="brow"><span>' + esc(k.slice(5)) + '</span><div class="bt"><div class="blbar" style="width:' + Math.round(v / maxd * 100) + '%"></div></div><b>' + v + '</b></div>').join('') + '</div>' +
    (ro ? '' : '<div class="bcard"><div class="rh">花在哪些地方</div>' + (Object.keys(byPlace).length ? Object.entries(byPlace).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k, v]) => '<div class="brow"><span>' + esc(pname(k)) + '</span><div class="bt"><div class="blbar" style="width:' + Math.round(v / Math.max(...Object.values(byPlace)) * 100) + '%"></div></div><b>' + Math.round(v) + '</b></div>').join('') : '<div class="tlnote">还没有消费对应到景点；在下面的明细里给消费选“对应景点”。</div>') + '</div>') +
    '<div class="bcard"><div class="rh">最大的 5 笔</div>' + top.map(r => '<div class="brow"><span>' + esc(r.merchant) + '</span><b>' + r.amount + '</b><i>' + esc(r.date.slice(5)) + '</i></div>').join('') + '</div></div>' +
    (ro ? '<div class="tlnote">这是账单里这段日期的全部消费，只用来看统计；要改类别，请在“行程期间”里改。</div>' : '<div class="tlnote">改某一笔的类别时，同一商户的其他消费会一起改，以后导入也沿用（已记住 ' + BL.rules + ' 家）。</div>');
  const opt = (list, cur, fn) => list.map(x => '<option value="' + esc(fn(x)[0]) + '"' + (fn(x)[0] === cur ? ' selected' : '') + '>' + esc(fn(x)[1]) + '</option>').join('');
  $('bl_list').innerHTML = '<table class="bltab"><tr><th>时间</th><th>商户</th><th>金额</th><th>类别</th><th>对应景点</th><th>不计入</th></tr>' + V.rows.map(r =>
    ro ? '<tr class="' + (r.excluded ? 'ex' : '') + '"><td>' + esc(r.date.slice(5) + ' ' + r.time) + '</td><td>' + esc(r.merchant) + '</td><td>' + r.amount + '</td><td>' + esc(r.category) + '</td><td>' + esc(r.source === 'wechat' ? '微信' : r.source === 'alipay' ? '支付宝' : r.source) + '</td><td></td></tr>' :
    '<tr class="' + (r.excluded ? 'ex' : '') + '" data-id="' + esc(r.id) + '"><td>' + esc(r.date.slice(5) + ' ' + r.time) + '</td><td>' + esc(r.merchant) + '</td><td>' + r.amount + '</td>' +
    '<td><select class="c">' + opt(BL.categories, r.category, x => [x, x]) + '</select></td>' +
    '<td><select class="p"><option value="">—</option>' + opt(BL.places, r.place_id || '', x => [x.id, x.name]) + '</select></td>' +
    '<td><input type="checkbox" class="x"' + (r.excluded ? ' checked' : '') + '></td></tr>').join('') + '</table>';
  if (!ro) $('bl_list').querySelectorAll('tr[data-id]').forEach(tr => {
    const id = tr.dataset.id, send = async o => { try { await api('bills_edit', Object.assign({id: id}, o)); await blLoad(); } catch (e) { blSay(e.message, true); } };
    tr.querySelector('.c').onchange = e => send({category: e.target.value, remember: true});
    tr.querySelector('.p').onchange = e => send({place_id: e.target.value});
    tr.querySelector('.x').onchange = e => send({excluded: e.target.checked});
  });
}
$('bl_wsave').onclick = async () => { try { const r = await api('bills_watch', {folders: $('bl_watch').value.split('\n')}); $('bl_wmsg').textContent = r.message; await blLoad(); } catch (e) { $('bl_wmsg').textContent = e.message; } };
$('bl_scan').onclick = async () => { $('bl_wmsg').textContent = '正在扫描…'; try { const r = await api('bills_scan', {}); $('bl_wmsg').textContent = r.message; await blLoad(); } catch (e) { $('bl_wmsg').textContent = e.message; } };
function blSay(t, err) { const m = $('bl_msg'); m.textContent = t || ''; m.className = 'msgbox' + (t ? ' on' : '') + (err ? ' err' : ''); if (t) toast(t.split('\n')[0], err); }
$('bl_go').onclick = async () => {
  $('bl_go').disabled = true; blSay('正在导入…');
  try { const r = await api('bills_import', {path: $('bl_path').value}); blSay(r.message || '导入完成，但没有返回内容。'); await blLoad(); } catch (e) { blSay(e && e.message ? e.message : '导入失败（没有返回原因）。', true); }
  $('bl_go').disabled = false;
};
document.querySelectorAll('button[data-pick]').forEach(b => b.onclick = async () => {
  try { const r = await api('pick_path', {kind: b.dataset.pick, prompt: b.dataset.pick === 'folder' ? '请选择文件夹' : '请选择文件'}); if (r.path) { $(b.dataset.to).value = r.path; $(b.dataset.to).dispatchEvent(new Event('change')); if (b.dataset.to === 'vd_path') $('vd_scan').click(); } }
  catch (e) { toast(e.message, true); }
});
$('tl_q').oninput = () => { if (toolsData) renderTools(); };
load().then(homeMaybe);
</script></body></html>
"""


def page_html() -> str:
    return (TEMPLATE
            .replace("__CSS__", (_ASSETS / "leaflet.css").read_text(encoding="utf-8"))
            .replace("__JS__", (_ASSETS / "leaflet.js").read_text(encoding="utf-8").replace("</script", "<\\/script")))
