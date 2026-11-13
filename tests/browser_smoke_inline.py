"""In-memory Chromium test when test environment forbids navigation to local URLs."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
html=(Path(__file__).resolve().parents[1]/'site/index.html').read_text()
PICKS={'top':['122','39','54','2','68'],'jungle':['64','254','234','56','876'],'middle':['84','105','246','163','157'],'bottom':['222','145','81','51','498'],'support':['412','111','497','117','267']}

def mkdata(role,patch,kind):
    obj={'lane':role,'schema_version':2,'tierlist':{i:{'games':4000,'wr':51,'pr':3} for i in PICKS[role]},'matchups':{str(i):{} for i in range(70,140)}}
    if kind=='recent':obj.update(patch=patch,scraped_at='2026-11-13T02:00:00Z')
    else:obj.update(source_patches=[patch]+[f'16.{i}' for i in range(21,2,-1)],generated_at='2026-11-13T02:00:00Z')
    return obj

# Keep all test data independent of real upstream so nothing is falsely claimed.
with sync_playwright() as p:
    b=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    page=b.new_page(viewport={'width':1200,'height':800})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.evaluate('''() => {
      window.__testPatch='16.22';window.__testLive='16.22';window.__testRev='a';
      const state={};
      Object.defineProperty(window, 'localStorage', {configurable:true, value:{
        getItem:k=>state[k]||null,setItem:(k,v)=>{state[k]=v},removeItem:k=>delete state[k]
      }});
      window.fetch=async function(url){
        const str=String(url);
        const m=['top','jungle','middle','bottom','support'];
        const patch=window.__testPatch;
        if(str.includes('/manifest.json')){
          const manifest={format:'rift-draft-manifest',schema_version:1,riot_patch:window.__testLive,
            source_patch:patch,source_fresh:patch===window.__testLive,assets_version:patch+'.1',
            recent:Object.fromEntries(m.map(r=>[r,{available:true,sha256:window.__testRev.repeat(64)}])),
            history:Object.fromEntries(m.map(r=>[r,{available:true,sha256:window.__testRev.repeat(64)}]))};
          return new Response(JSON.stringify(manifest),{status:200,headers:{'Content-Type':'application/json'}});
        }
        const match=str.match(/data\/(recent|history)\/(top|jungle|middle|bottom|support)\.json/);
        if(match){
          const pick={top:['122','39','54','2','68'],jungle:['64','254','234','56','876'],middle:['84','105','246','163','157'],bottom:['222','145','81','51','498'],support:['412','111','497','117','267']};
          const tierlist=Object.fromEntries(pick[match[2]].map(id=>[id,{games:4000,wr:51,pr:3}]));
          const matchups=Object.fromEntries(Array.from({length:60},(_,i)=>[String(i+70),{}]));
          const obj={lane:match[2],schema_version:2,tierlist,matchups};
          if(match[1]==='recent'){obj.patch=patch;obj.scraped_at='2026-11-13T02:00:00Z';}
          else {obj.source_patches=[patch,...Array.from({length:19},(_,i)=>'16.'+(21-i))];obj.generated_at='2026-11-13T02:00:00Z';}
          return new Response(JSON.stringify(obj),{status:200,headers:{'Content-Type':'application/json'}});
        }
        throw new Error('Blocked unexpected request '+url);
      }
    }''')
    page.set_content(html,wait_until='domcontentloaded')
    page.wait_for_function("typeof liveManifest!=='undefined' && liveManifest?.source_patch==='16.22' && !!data.top",timeout=30000)
    assert page.locator('#dataHealth').inner_text().count('Loaded')>=1
    for role in ('jungle','middle','bottom','support','top'):
        page.locator(f'[data-lane="{role}"]').click()
        page.wait_for_function(f"!!data.{role}",timeout=10000)
    page.evaluate("window.__testRev='b'")
    page.locator('#refresh').click()
    page.wait_for_function("manifestFingerprint.includes('bbbbbb') && !!data.top",timeout=15000)
    page.evaluate("window.__testPatch='16.23';window.__testLive='16.23';window.__testRev='c'")
    page.locator('#refresh').click()
    page.wait_for_function("REQUIRED_PATCH==='16.23' && !!data.top",timeout=15000)
    assert '26.23' in page.locator('header p').inner_text()
    page.evaluate("window.__testLive='16.24';window.__testRev='d'")
    page.locator('#refresh').click()
    page.wait_for_function("liveManifest?.riot_patch==='16.24'",timeout=15000)
    assert '26.24' in page.locator('#sourceHelp').inner_text()
    assert not errors,errors
    print('PASS: all five lanes + in-memory same-patch refresh + new patch + source lag + no JS errors')
    page.screenshot(path='/mnt/data/rift_draft_autoupdate_preview.png')
    b.close()
